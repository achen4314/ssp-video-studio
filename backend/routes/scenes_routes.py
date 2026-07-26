"""Scene management + script generation routes"""
from flask import Blueprint, request, jsonify
import os, json, re
from pathlib import Path

bp = Blueprint('scenes', __name__)

from backend.database import get_db, Project, Scene, Evidence
from backend.config import PROJECTS_DIR, AI_KEPU_DIR

@bp.route('/api/projects/<int:pid>/scenes', methods=['GET'])
def list_scenes(pid):
    db = get_db()
    try:
        scenes = db.query(Scene).filter_by(project_id=pid).order_by(Scene.scene_number).all()
        return jsonify([{
            'id': s.id, 'name': s.name, 'scene_number': s.scene_number,
            'status': s.status, 'narration_text': s.narration_text,
            'audio_file': s.audio_file, 'video_file': s.video_file,
            'duration_s': s.duration_s, 'claims_covered': s.claims_covered,
        } for s in scenes])
    finally:
        db.close()

@bp.route('/api/projects/<int:pid>/scenes/extract-narration', methods=['POST'])
def extract_narration(pid):
    db = get_db()
    try:
        p = db.query(Project).get(pid)
        if not p:
            return jsonify({'error': 'not_found'}), 404
        
        project_dir = PROJECTS_DIR / p.slug
        scene_files = list(project_dir.glob('scenes_*.py'))
        
        if not scene_files:
            kepu_dir = AI_KEPU_DIR / p.slug
            if kepu_dir.exists():
                scene_files = list(kepu_dir.glob('scenes_*.py'))
        
        all_narrations = {}
        for sf in scene_files:
            with open(sf, 'r', encoding='utf-8') as f:
                code = f.read()
            matches = re.findall(r'self\.say\("(.+?)"\)', code, re.DOTALL)
            cleaned = []
            for m in matches:
                m = re.sub(r'"\s*\n\s*"', '', m)
                m = re.sub(r'\s+', '', m)
                if m:
                    cleaned.append(m)
            all_narrations[sf.name] = cleaned
        
        scenes = db.query(Scene).filter_by(project_id=pid).order_by(Scene.scene_number).all()
        all_texts = []
        for narr_list in all_narrations.values():
            all_texts.extend(narr_list)
        
        for i, s in enumerate(scenes):
            if i < len(all_texts):
                s.narration_text = all_texts[i]
        
        db.commit()
        return jsonify({
            'files_processed': len(all_narrations),
            'total_narrations': len(all_texts),
            'narrations': all_narrations,
        })
    finally:
        db.close()

@bp.route('/api/projects/<int:pid>/scenes/generate-scripts', methods=['POST'])
def generate_scene_scripts(pid):
    """Generate Manim scene script files from DB scenes"""
    db = get_db()
    try:
        p = db.query(Project).get(pid)
        if not p:
            return jsonify({'error': 'not_found'}), 404
        
        project_dir = PROJECTS_DIR / p.slug
        
        # Copy kepu_utils.py to project
        kepu_srcs = [
            Path('D:/ai-kepu/e02-beta-alanine/kepu_utils.py'),
            Path(__file__).resolve().parent.parent.parent / 'scripts' / 'kepu_utils.py',
        ]
        for src in kepu_srcs:
            if src.exists():
                import shutil
                shutil.copy2(src, project_dir / 'kepu_utils.py')
                break
        
        # Read scenes from DB
        db_scenes = db.query(Scene).filter_by(project_id=pid).order_by(Scene.scene_number).all()
        if not db_scenes:
            return jsonify({'error': 'no scenes — run auto-setup first'}), 400
        
        evidence_files = [e.filename for e in db.query(Evidence).filter_by(project_id=pid).all()]
        
        scenes_data = []
        for s in db_scenes:
            ev_idx = (s.scene_number - 1) % max(1, len(evidence_files))
            ev_file = evidence_files[ev_idx] if evidence_files else None
            
            scenes_data.append({
                'name': s.name,
                'number': s.scene_number,
                'narration': s.narration_text or '...',
                'title': s.name.replace('S', '').replace('_', ' ')[:20],
                'claims': json.loads(s.claims_covered) if s.claims_covered else [],
                'evidence_files': [ev_file] if ev_file else [],
            })
        
        # Split into 3 groups
        n = len(scenes_data)
        group_size = max(1, (n + 2) // 3)
        
        files_created = []
        for group_idx in range(3):
            start = group_idx * group_size
            end = min(start + group_size, n)
            if start >= n:
                break
            
            scene_group = scenes_data[start:end]
            filename = f'scenes_{start+1}_{end}.py'
            filepath = project_dir / filename
            
            code = _generate_code(scene_group, p.name)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(code)
            
            files_created.append(filename)
        
        # Update DB
        for i, s in enumerate(db_scenes):
            g = i // group_size
            s.script_file = f'scenes_{g*group_size+1}_{min((g+1)*group_size, n)}.py'
            s.status = 'scripted'
        
        p.status = 'scripting'
        p.progress = 30
        db.commit()
        
        return jsonify({
            'files_created': files_created,
            'scene_count': n,
            'status': 'scripting',
        })
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

def _safe(s, max_len=300):
    """Sanitize string for embedding in generated Python code"""
    if not s:
        return '...'
    s = s.replace('\\', '\\\\')
    s = s.replace('"', "'")
    s = s.replace('\n', ' ')
    s = s.replace('\r', '')
    s = re.sub(r'[#]', '', s)
    if len(s) > max_len:
        s = s[:max_len-3] + '...'
    return s

def _generate_code(scene_group, project_name):
    """Generate a complete scene file"""
    lines = []
    lines.append(f'"""\n{project_name} - Auto-generated by SSP Video Studio\n"""')
    lines.append('import sys, os')
    lines.append('sys.path.insert(0, os.path.dirname(__file__))')
    lines.append('from kepu_utils import KepuScene, BG, GREEN, GOLD, TEXT_C, MUTED, CARD_BG, DANGER, CN, MONO')
    lines.append('from manim import *')
    lines.append('')
    lines.append('TEXT = TEXT_C')
    lines.append('E = os.path.join(os.path.dirname(__file__), "evidence")')
    lines.append('')
    lines.append('def ev(path):')
    lines.append('    p = os.path.join(E, path)')
    lines.append('    return p if os.path.exists(p) else None')
    lines.append('')
    lines.append('def ev_img(path, h=3.5):')
    lines.append('    full = ev(path)')
    lines.append('    if full is None: return None')
    lines.append('    img = ImageMobject(full)')
    lines.append('    img.set_height(h)')
    lines.append('    return img')
    
    for sn in scene_group:
        name = sn.get('name', 'S1_Scene')
        title = _safe(sn.get('title', name), 30)
        narration = _safe(sn.get('narration', ''), 500)
        ev_files = sn.get('evidence_files', [])
        claims = sn.get('claims', [])
        
        lines.append('')
        lines.append(f'class {name}(KepuScene):')
        c_str = ', '.join(str(c) for c in claims[:3]) if claims else 'none'
        e_str = ', '.join(ev_files[:2]) if ev_files else 'none'
        lines.append(f'    """Claims: {c_str} | Evidence: {e_str}"""')
        lines.append('')
        lines.append('    def construct(self):')
        lines.append('        self.camera.background_color = BG')
        lines.append(f'        t = Text("{title}", font=CN, font_size=46, color=GREEN, weight=BOLD)')
        lines.append('        t.to_edge(UP, buff=0.5)')
        lines.append('        self.play(FadeIn(t), run_time=1.0)')
        lines.append('        self.wait(0.5)')
        lines.append(f'        self.say("{narration}")')
        
        for evf in ev_files[:2]:
            lines.append(f'        img = ev_img("{evf}", h=3.5)')
            lines.append('        if img:')
            lines.append('            self.play(FadeIn(img), run_time=0.8)')
            lines.append('            self.wait(2.5)')
            lines.append('            self.play(FadeOut(img), run_time=0.6)')
        
        lines.append('        self.play(FadeOut(Group(*self.mobjects)), run_time=0.8)')
    
    return '\n'.join(lines)
