"""Scene management + script generation routes"""
from flask import Blueprint, request, jsonify
import os, json, re
from pathlib import Path

bp = Blueprint('scenes', __name__)

from backend.database import get_db, Project, Scene
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

@bp.route('/api/projects/<int:pid>/scenes', methods=['POST'])
def create_scenes(pid):
    """Create scene entries from plan"""
    data = request.get_json() or {}
    scene_names = data.get('scenes', [])  # [{'name': 'S1_Overview', 'number': 1}, ...]
    
    db = get_db()
    try:
        created = []
        for sn in scene_names:
            s = Scene(
                project_id=pid,
                name=sn.get('name', ''),
                scene_number=sn.get('number', len(created) + 1),
                narration_text=sn.get('narration', ''),
                claims_covered=json.dumps(sn.get('claims', [])),
                status='pending'
            )
            db.add(s)
            created.append(s.name)
        db.commit()
        return jsonify({'created': created, 'count': len(created)}), 201
    finally:
        db.close()

@bp.route('/api/projects/<int:pid>/scenes/<int:sid>', methods=['PATCH'])
def update_scene(pid, sid):
    data = request.get_json() or {}
    db = get_db()
    try:
        s = db.query(Scene).get(sid)
        if not s:
            return jsonify({'error': 'not_found'}), 404
        
        for field in ['name', 'status', 'narration_text', 'audio_file', 'video_file', 'duration_s', 'script_file', 'claims_covered']:
            if field in data:
                setattr(s, field, data[field])
        
        db.commit()
        return jsonify({'ok': True})
    finally:
        db.close()

@bp.route('/api/projects/<int:pid>/scenes/extract-narration', methods=['POST'])
def extract_narration(pid):
    """Extract narration text from scene script files"""
    db = get_db()
    try:
        p = db.query(Project).get(pid)
        if not p:
            return jsonify({'error': 'not_found'}), 404
        
        project_dir = PROJECTS_DIR / p.slug
        scene_files = list(project_dir.glob('scenes_*.py'))
        
        if not scene_files:
            # Try AI_KEPU_DIR
            kepu_dir = AI_KEPU_DIR / p.slug
            if kepu_dir.exists():
                scene_files = list(kepu_dir.glob('scenes_*.py'))
        
        all_narrations = {}
        for sf in scene_files:
            with open(sf, 'r', encoding='utf-8') as f:
                code = f.read()
            # Extract all self.say() calls — handle multi-line strings
            pattern = r'self\.say\("(.+?)"\)'
            matches = re.findall(pattern, code, re.DOTALL)
            # Clean multi-line concatenation
            cleaned = []
            for m in matches:
                m = re.sub(r'"\s*\n\s*"', '', m)
                m = re.sub(r'\s+', '', m)
                if m:
                    cleaned.append(m)
            all_narrations[sf.name] = cleaned
        
        # Update scenes in DB
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
    """Generate scene script files with kepu_utils template"""
    data = request.get_json() or {}
    scenes_data = data.get('scenes', [])
    
    db = get_db()
    try:
        p = db.query(Project).get(pid)
        if not p:
            return jsonify({'error': 'not_found'}), 404
        
        project_dir = PROJECTS_DIR / p.slug
        
        # Copy kepu_utils.py to project
        kepu_src = Path('D:/ai-kepu/e02-beta-alanine/kepu_utils.py')
        if kepu_src.exists():
            import shutil
            shutil.copy2(kepu_src, project_dir / 'kepu_utils.py')
        
        # Split scenes into 3 groups
        n = len(scenes_data)
        group_size = max(1, (n + 2) // 3)
        
        files_created = []
        for group_idx in range(3):
            start = group_idx * group_size
            end = min(start + group_size, n)
            if start >= n:
                break
            
            scene_group = scenes_data[start:end]
            group_start = start + 1
            group_end = end
            
            filename = f'scenes_{group_start}_{group_end}.py'
            filepath = project_dir / filename
            
            code = _generate_scene_file_code(scene_group, p.name)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(code)
            
            files_created.append(filename)
        
        # Save scenes to DB
        for sn in scenes_data:
            existing = db.query(Scene).filter_by(project_id=pid, name=sn.get('name', '')).first()
            if not existing:
                s = Scene(
                    project_id=pid,
                    name=sn.get('name', f'S{len(db.query(Scene).filter_by(project_id=pid).all())+1}'),
                    scene_number=sn.get('number', len(db.query(Scene).filter_by(project_id=pid).all()) + 1),
                    narration_text=sn.get('narration', ''),
                    claims_covered=json.dumps(sn.get('claims', [])),
                    script_file=filename if group_idx == sn.get('number', 1) // group_size else filename,
                )
                db.add(s)
        
        p.status = 'scripting'
        db.commit()
        
        return jsonify({'files_created': files_created, 'scene_count': n})
    finally:
        db.close()

def _generate_scene_file_code(scene_group, project_name):
    """Generate a complete scene file from scene data"""
    code = f'''"""
{project_name} — Scenes {scene_group[0].get('number', 1)}-{scene_group[-1].get('number', len(scene_group))}
Auto-generated by SSP Video Studio
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from kepu_utils import KepuScene, BG, GREEN, GOLD, TEXT_C, MUTED, CARD_BG, DANGER, CN, MONO
from manim import *

TEXT = TEXT_C
E = os.path.join(os.path.dirname(__file__), "evidence")

def ev(path):
    p = os.path.join(E, path)
    return p if os.path.exists(p) else None

def ev_img(path, h=3.5):
    full = ev(path)
    if full is None:
        return None
    img = ImageMobject(full)
    img.set_height(h)
    return img

'''
    
    for sn in scene_group:
        scene_name = sn.get('name', f'S{sn.get("number", 1)}')
        narration = sn.get('narration', '...')
        evidence_files = sn.get('evidence_files', [])
        claims = sn.get('claims', [])
        
        code += f'''
class {scene_name}(KepuScene):
    """Claims: {', '.join(claims) if claims else 'none'}
    Evidence: {', '.join(evidence_files) if evidence_files else 'none'}"""
    
    def construct(self):
        self.camera.background_color = BG
        
        # Title
        t = Text("{sn.get('title', scene_name)}", font=CN, font_size=46, color=GREEN, weight=BOLD)
        t.to_edge(UP, buff=0.5)
        self.play(FadeIn(t), run_time=1.0)
        self.wait(0.5)
        
        # Narration — claim: {', '.join(claims) if claims else 'none'}
        self.say("{narration}")
        
'''
        
        for evf in evidence_files:
            code += f'''        # Show evidence: {evf}
        img = ev_img("{evf}", h=3.5)
        if img:
            self.play(FadeIn(img), run_time=0.8)
            self.wait(2.5)
            self.play(FadeOut(img), run_time=0.6)
        
'''
        
        code += '''        # Cleanup
        self.play(FadeOut(Group(*self.mobjects)), run_time=0.8)

'''
    
    return code
