"""Project CRUD routes"""
from flask import Blueprint, request, jsonify
from sqlalchemy import desc
import os, json, re
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
