"""Project CRUD routes"""
from flask import Blueprint, request, jsonify
from sqlalchemy import desc
import os, json, re, shutil, time
from pathlib import Path

bp = Blueprint('projects', __name__)

from backend.database import get_db, Project, Scene, Evidence
from backend.config import PROJECTS_DIR, OBSIDIAN_VAULT, AI_KEPU_DIR

@bp.route('/api/projects', methods=['GET'])
def list_projects():
    db = get_db()
    try:
        projects = db.query(Project).order_by(desc(Project.updated_at)).all()
        return jsonify([{
            'id': p.id, 'name': p.name, 'slug': p.slug,
            'status': p.status, 'progress': p.progress,
            'source_score': p.source_score,
            'source_note': p.source_note,
            'created_at': p.created_at.isoformat() if p.created_at else None,
            'updated_at': p.updated_at.isoformat() if p.updated_at else None,
        } for p in projects])
    finally:
        db.close()

@bp.route('/api/projects/<int:pid>', methods=['GET'])
def get_project(pid):
    db = get_db()
    try:
        p = db.query(Project).get(pid)
        if not p:
            return jsonify({'error': 'not_found'}), 404
        scenes = db.query(Scene).filter_by(project_id=pid).order_by(Scene.scene_number).all()
        evidence = db.query(Evidence).filter_by(project_id=pid).all()
        return jsonify({
            'id': p.id, 'name': p.name, 'slug': p.slug,
            'status': p.status, 'progress': p.progress,
            'source_note': p.source_note, 'source_score': p.source_score,
            'plan_md': p.plan_md, 'claims_json': p.claims_json,
            'evidence_map': p.evidence_map,
            'scenes': [{
                'id': s.id, 'name': s.name, 'scene_number': s.scene_number,
                'status': s.status, 'narration_text': s.narration_text,
                'audio_file': s.audio_file, 'video_file': s.video_file,
                'duration_s': s.duration_s, 'claims_covered': s.claims_covered,
            } for s in scenes],
            'evidence_items': [{
                'id': e.id, 'filename': e.filename, 'grade': e.grade,
                'resolution': e.resolution, 'size_kb': e.size_kb,
                'claims_linked': e.claims_linked, 'status': e.status,
            } for e in evidence],
            'created_at': p.created_at.isoformat() if p.created_at else None,
            'updated_at': p.updated_at.isoformat() if p.updated_at else None,
        })
    finally:
        db.close()

@bp.route('/api/projects', methods=['POST'])
def create_project():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    source_note = data.get('source_note', '').strip()
    
    if not name:
        return jsonify({'error': 'name required'}), 400
    
    slug = re.sub(r'[^a-z0-9\u4e00-\u9fff]+', '-', name.lower().strip()).strip('-')
    if not slug or all('\u4e00' <= c <= '\u9fff' for c in slug):
        slug = f'project-{int(time.time())}'
    
    db = get_db()
    try:
        existing = db.query(Project).filter_by(slug=slug).first()
        if existing:
            slug = f'{slug}-{int(__import__("time").time())}'
        
        p = Project(name=name, slug=slug, source_note=source_note, status='draft')
        db.add(p)
        db.commit()
        
        # Create project directory
        project_dir = PROJECTS_DIR / slug
        project_dir.mkdir(exist_ok=True)
        (project_dir / 'evidence').mkdir(exist_ok=True)
        (project_dir / 'audio').mkdir(exist_ok=True)
        
        return jsonify({'id': p.id, 'slug': p.slug, 'name': p.name}), 201
    finally:
        db.close()

@bp.route('/api/projects/<int:pid>', methods=['PATCH'])
def update_project(pid):
    data = request.get_json() or {}
    db = get_db()
    try:
        p = db.query(Project).get(pid)
        if not p:
            return jsonify({'error': 'not_found'}), 404
        
        for field in ['name', 'status', 'plan_md', 'claims_json', 'evidence_map', 'source_note', 'progress']:
            if field in data:
                setattr(p, field, data[field])
        
        db.commit()
        return jsonify({'ok': True})
    finally:
        db.close()

@bp.route('/api/projects/<int:pid>', methods=['DELETE'])
def delete_project(pid):
    db = get_db()
    try:
        p = db.query(Project).get(pid)
        if not p:
            return jsonify({'error': 'not_found'}), 404
        
        # Delete project directory
        import shutil
        project_dir = PROJECTS_DIR / p.slug
        if project_dir.exists():
            shutil.rmtree(project_dir)
        
        db.delete(p)
        db.commit()
        return jsonify({'ok': True})
    finally:
        db.close()

@bp.route('/api/projects/<int:pid>/score-source', methods=['POST'])
def score_source(pid):
    """Run score_source.py on the project's source note"""
    db = get_db()
    try:
        p = db.query(Project).get(pid)
        if not p or not p.source_note:
            return jsonify({'error': 'no source note'}), 400
        
        # Check source exists
        source_path = OBSIDIAN_VAULT / p.source_note
        if not source_path.exists():
            # Try alternative path
            alt = Path(os.path.expanduser(f'~/Desktop/微信公众号内容/{p.source_note}'))
            if alt.exists():
                source_path = alt
            else:
                return jsonify({'error': f'source not found: {source_path}'}), 404
        
        # Run scoring
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'score_source', 
            Path(__file__).resolve().parent.parent.parent / 'scripts' / 'score_source.py'
        )
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            result = mod.score_note(str(source_path))
        else:
            # Fallback: simple inline scoring
            result = _simple_score(str(source_path))
        
        p.source_score = result.get('weighted_total', 0)
        db.commit()
        
        return jsonify({'score': result, 'weighted_total': result.get('weighted_total', 0)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@bp.route('/api/projects/<int:pid>/auto-setup', methods=['POST'])
def auto_setup(pid):
    """一键自动搭建：读取Obsidian笔记 → 提取章节→生成场景→搜索证据图→评分→生成策划"""
    db = get_db()
    try:
        p = db.query(Project).get(pid)
        if not p or not p.source_note:
            return jsonify({'error': 'project has no source note'}), 400
        
        # Find source file
        source_path = None
        candidates = [
            OBSIDIAN_VAULT / p.source_note,
            Path(os.path.expanduser(f'~/Desktop/微信公众号内容/{p.source_note}')),
        ]
        for c in candidates:
            if c.exists():
                source_path = c
                break
        
        if not source_path:
            return jsonify({'error': f'source not found: {p.source_note}'}), 404
        
        with open(source_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        log = []
        project_dir = PROJECTS_DIR / p.slug
        project_dir.mkdir(exist_ok=True)
        
        # ==== Step 1: Score ====
        score = _simple_score(str(source_path))
        p.source_score = score['weighted_total']
        log.append(f'✅ 评分: {score["weighted_total"]:.1f}/5 ({score["verdict"]})')
        
        # ==== Step 2: Extract chapters → create scenes ====
        sections = re.findall(r'^#{1,3}\s+(.+)$', content, re.MULTILINE)
        
        # Get section content
        h2_blocks = re.split(r'\n(?=##\s)', content)
        h2_blocks = [b for b in h2_blocks if b.strip()]
        
        # Map chapters to scenes
        scene_count = 0
        evidence_dir = project_dir / 'evidence'
        evidence_dir.mkdir(exist_ok=True)
        
        for i, block in enumerate(h2_blocks[:9]):  # Max 9 scenes
            title_match = re.match(r'^#{1,3}\s+(.+)$', block, re.MULTILINE)
            if not title_match:
                continue
            title = title_match.group(1)[:30]
            
            # Extract data points from this section
            data_pts = re.findall(r'\d+\.?\d*\s*%', block)
            refs = re.findall(r'\(([A-Z][a-z]+(?:\s+et\s+al\.?)?\s+\d{4}[a-z]?)\)', block)
            pmids = re.findall(r'PMID:?\s*(\d+)', block)
            
            # Create safe scene name
            safe_title = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "", title)[:20]
            scene_name = f'S{i+1}_{safe_title}'
            
            # Extract first 200 chars as narration
            clean_block = re.sub(r'^#+\s+.+\n', '', block).strip()
            clean_block = re.sub(r'!\[\[.*?\]\]', '', clean_block)  # remove images
            narration = clean_block[:300].strip()
            
            existing = db.query(Scene).filter_by(project_id=pid, name=scene_name).first()
            if not existing:
                s = Scene(
                    project_id=pid, name=scene_name, scene_number=i+1,
                    narration_text=narration,
                    claims_covered=json.dumps([f'S{i+1}_{j:03d}' for j in range(len(data_pts)+len(refs))]),
                    status='pending'
                )
                db.add(s)
                scene_count += 1
            
            log.append(f'  📝 S{i+1}: "{title}" ({len(data_pts)}数据点, {len(refs)}引用)')
        
        log.append(f'✅ 场景生成: {scene_count} 个')
        
        # ==== Step 3: Extract evidence from note images ====
        vault_images = re.findall(r'!\[\[(.*?)\]\]', content)
        evidence_count = 0
        images_dir = Path(os.path.expanduser('~/Desktop/微信公众号内容/images'))
        
        for img_rel in vault_images:
            img_path = images_dir / img_rel
            if img_path.exists():
                dst = evidence_dir / img_path.name
                shutil.copy2(img_path, dst)
                
                try:
                    from PIL import Image
                    img = Image.open(dst)
                    w, h = img.size
                    grade = 'A' if w >= 1200 else ('B' if w >= 800 else 'C')
                except:
                    w, h = 0, 0
                    grade = '?'
                
                e = Evidence(
                    project_id=pid, filename=img_path.name,
                    original_path=str(dst),
                    resolution=f'{w}×{h}' if w else 'unknown',
                    size_kb=round(dst.stat().st_size/1024, 1),
                    grade=grade, status='ready'
                )
                db.add(e)
                evidence_count += 1
                log.append(f'  🖼️ {img_path.name} ({grade}级)')
        
        log.append(f'✅ 证据图导入: {evidence_count} 张（来自笔记嵌入图片）')
        
        # ==== Step 4: Generate basic plan.md ====
        plan = f"""# {p.name} — 自动生成策划

## 基本信息
- 源笔记: {p.source_note}
- 源评分: {score['weighted_total']:.1f}/5
- 场景数: {scene_count}
- 证据图: {evidence_count} 张

## 叙事结构
"""
        for i in range(scene_count):
            if i == 0:
                role = '钩子 — 核心判断与定位'
            elif i < 3:
                role = '机制 — 科学原理深度拆解'
            elif i < scene_count - 2:
                role = '证据 — 关键研究数据分析'
            elif i < scene_count - 1:
                role = '应用 — 实战场景映射'
            else:
                role = '收尾 — 结论与建议'
            plan += f"{i+1}. S{i+1}: {role}\n"
        
        p.plan_md = plan
        p.status = 'planning'
        p.progress = 20
        
        db.commit()
        log.append(f'✅ 策划书已生成')
        log.append(f'🏁 自动搭建完成！状态: 策划中 → 下一步: 生成脚本')
        
        return jsonify({
            'status': 'done',
            'scenes_created': scene_count,
            'evidence_imported': evidence_count,
            'source_score': score['weighted_total'],
            'log': log,
        })
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e), 'log': log if 'log' in dir() else []}), 500
    finally:
        db.close()

def _simple_score(md_path):
    """Fallback inline scoring when score_source.py not available"""
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    size_kb = len(content.encode('utf-8')) / 1024
    h2_count = len(re.findall(r'^##\s', content, re.MULTILINE))
    refs = len(re.findall(r'\([A-Z][a-z]+\s*\d{4}[a-z]?\)', content))
    images = len(re.findall(r'!\[\[.*?\]\]', content))
    data_pts = len(re.findall(r'\d+\.?\d*\s*%', content))
    practical = sum(content.count(kw) for kw in ['建议','应用','剂量','方案','策略','指南'])
    
    completeness = min(5, max(1, int(size_kb / 10)))
    evidence_score = min(5, max(1, (refs + len(re.findall(r'PMID|DOI', content))) // 3))
    data_score = min(5, max(1, data_pts // 4))
    
    weighted = completeness * 0.3 + evidence_score * 0.3 + min(5, max(1, practical // 2)) * 0.15 + data_score * 0.15 + min(5, max(2, h2_count)) * 0.1
    
    verdict = 'ready' if weighted >= 3.5 else ('needs_work' if weighted >= 2.5 else 'insufficient')
    
    return {
        'size_kb': round(size_kb, 1),
        'h2_sections': h2_count,
        'references': refs,
        'data_points': data_pts,
        'weighted_total': round(weighted, 2),
        'verdict': verdict,
    }
