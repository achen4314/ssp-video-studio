"""Evidence image management routes"""
from flask import Blueprint, request, jsonify, send_file
import os, json, shutil
from pathlib import Path
from datetime import datetime

bp = Blueprint('evidence', __name__)

from backend.database import get_db, Project, Evidence
from backend.config import PROJECTS_DIR, SCRIPTS_DIR

@bp.route('/api/projects/<int:pid>/evidence', methods=['GET'])
def list_evidence(pid):
    db = get_db()
    try:
        items = db.query(Evidence).filter_by(project_id=pid).all()
        return jsonify([{
            'id': e.id, 'filename': e.filename, 'grade': e.grade,
            'resolution': e.resolution, 'size_kb': e.size_kb,
            'claims_linked': e.claims_linked, 'status': e.status,
            'source_doi': e.source_doi, 'chart_type': e.chart_type,
        } for e in items])
    finally:
        db.close()

@bp.route('/api/projects/<int:pid>/evidence/upload', methods=['POST'])
def upload_evidence(pid):
    """Upload evidence images"""
    db = get_db()
    try:
        p = db.query(Project).get(pid)
        if not p:
            return jsonify({'error': 'project not found'}), 404
        
        project_dir = PROJECTS_DIR / p.slug / 'evidence'
        project_dir.mkdir(exist_ok=True)
        
        uploaded = []
        for key in request.files:
            file = request.files[key]
            if file.filename:
                fname = file.filename
                fpath = project_dir / fname
                file.save(str(fpath))
                
                size_kb = fpath.stat().st_size / 1024
                
                # Quick resolution check
                try:
                    from PIL import Image
                    img = Image.open(fpath)
                    w, h = img.size
                    resolution = f'{w}×{h}'
                    grade = 'A' if w >= 1200 else ('B' if w >= 800 else 'C')
                except:
                    resolution = 'unknown'
                    grade = '?'
                
                e = Evidence(
                    project_id=pid, filename=fname,
                    original_path=str(fpath),
                    resolution=resolution, size_kb=round(size_kb, 1),
                    grade=grade, status='pending'
                )
                db.add(e)
                uploaded.append({'filename': fname, 'grade': grade, 'resolution': resolution})
        
        db.commit()
        return jsonify({'uploaded': uploaded, 'count': len(uploaded)}), 201
    finally:
        db.close()

@bp.route('/api/projects/<int:pid>/evidence/import-from-vault', methods=['POST'])
def import_from_vault(pid):
    """Import evidence images from Obsidian vault"""
    data = request.get_json() or {}
    image_paths = data.get('images', [])  # list of paths relative to vault images/
    
    db = get_db()
    try:
        p = db.query(Project).get(pid)
        if not p:
            return jsonify({'error': 'project not found'}), 404
        
        project_evidence_dir = PROJECTS_DIR / p.slug / 'evidence'
        project_evidence_dir.mkdir(exist_ok=True)
        
        vault_images = Path(os.path.expanduser('~/Desktop/微信公众号内容/images'))
        
        imported = []
        for img_path in image_paths:
            src = vault_images / img_path
            if not src.exists():
                imported.append({'path': img_path, 'status': 'not_found'})
                continue
            
            fname = src.name
            dst = project_evidence_dir / fname
            shutil.copy2(src, dst)
            
            size_kb = dst.stat().st_size / 1024
            try:
                from PIL import Image
                img = Image.open(dst)
                w, h = img.size
                resolution = f'{w}×{h}'
                grade = 'A' if w >= 1200 else ('B' if w >= 800 else 'C')
            except:
                resolution = 'unknown'
                grade = '?'
            
            e = Evidence(
                project_id=pid, filename=fname,
                original_path=str(dst),
                resolution=resolution, size_kb=round(size_kb, 1),
                grade=grade, status='ready'
            )
            db.add(e)
            imported.append({'path': img_path, 'status': 'imported', 'grade': grade})
        
        db.commit()
        return jsonify({'imported': imported, 'count': len([i for i in imported if i['status'] == 'imported'])})
    finally:
        db.close()

@bp.route('/api/projects/<int:pid>/evidence/<int:eid>/check-quality', methods=['POST'])
def check_quality(pid, eid):
    """Run quality check on a single evidence image"""
    db = get_db()
    try:
        e = db.query(Evidence).get(eid)
        if not e or not e.original_path:
            return jsonify({'error': 'not found'}), 404
        
        # Run verify_evidence_quality_v2
        script = SCRIPTS_DIR / 'verify_evidence_quality_v2.py'
        if not script.exists():
            # Fallback: simple PIL check
            return jsonify(_simple_quality_check(e.original_path))
        
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, str(script), e.original_path],
            capture_output=True, text=True, timeout=30
        )
        
        # Try to parse JSON output
        try:
            qr = json.loads(result.stdout)
        except:
            qr = _simple_quality_check(e.original_path)
        
        e.grade = qr.get('overall', e.grade)
        e.resolution = qr.get('resolution', e.resolution)
        e.status = 'ready' if qr.get('usable', True) else 'blocked'
        db.commit()
        
        return jsonify(qr)
    except Exception as ex:
        return jsonify({'error': str(ex)}), 500
    finally:
        db.close()

@bp.route('/api/projects/<int:pid>/evidence/batch-check', methods=['POST'])
def batch_check_quality(pid):
    """Run quality check on all evidence for a project"""
    db = get_db()
    try:
        items = db.query(Evidence).filter_by(project_id=pid).all()
        results = []
        for e in items:
            if e.original_path:
                qr = _simple_quality_check(e.original_path)
                e.grade = qr.get('overall', e.grade)
                e.resolution = qr.get('resolution', e.resolution)
                e.status = 'ready' if qr.get('usable', True) else 'blocked'
                results.append({'filename': e.filename, **qr})
        db.commit()
        
        summary = {
            'total': len(results),
            'S': sum(1 for r in results if r.get('overall') == 'S'),
            'A': sum(1 for r in results if r.get('overall') == 'A'),
            'B': sum(1 for r in results if r.get('overall') == 'B'),
            'C': sum(1 for r in results if r.get('overall') == 'C'),
            'F': sum(1 for r in results if r.get('overall') == 'F'),
        }
        return jsonify({'summary': summary, 'details': results})
    finally:
        db.close()

@bp.route('/api/projects/<int:pid>/evidence/<int:eid>/enhance', methods=['POST'])
def enhance_evidence(pid, eid):
    """Enhance a single evidence image"""
    db = get_db()
    try:
        e = db.query(Evidence).get(eid)
        if not e or not e.original_path:
            return jsonify({'error': 'not found'}), 404
        
        from PIL import Image, ImageEnhance, ImageFilter
        img = Image.open(e.original_path).convert('RGB')
        orig_w, orig_h = img.size
        
        # Simple enhancement
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.3)
        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(1.5)
        
        # Save enhanced
        p = db.query(Project).get(pid)
        enhanced_dir = PROJECTS_DIR / p.slug / 'evidence' / 'enhanced'
        enhanced_dir.mkdir(exist_ok=True)
        enhanced_path = enhanced_dir / e.filename
        img.save(enhanced_path, quality=95)
        
        e.enhanced_path = str(enhanced_path)
        e.status = 'ready'
        db.commit()
        
        return jsonify({
            'filename': e.filename,
            'original_size': f'{orig_w}×{orig_h}',
            'enhanced_path': str(enhanced_path),
            'status': 'enhanced',
        })
    except Exception as ex:
        return jsonify({'error': str(ex)}), 500
    finally:
        db.close()

def _simple_quality_check(image_path):
    """Simple quality check without external script dependency"""
    try:
        from PIL import Image, ImageStat
        img = Image.open(image_path)
        w, h = img.size
        
        if w >= 1600: grade = 'S'
        elif w >= 1200: grade = 'A'
        elif w >= 800: grade = 'B'
        elif w >= 400: grade = 'C'
        else: grade = 'F'
        
        stat = ImageStat.Stat(img)
        std = sum(stat.stddev) / len(stat.stddev)
        sharp_ok = std > 30
        
        return {
            'overall': grade,
            'resolution': f'{w}×{h}',
            'usable': grade not in ('C', 'F'),
            'sharp_ok': sharp_ok,
            'recommend_enhance': grade == 'B',
        }
    except Exception as e:
        return {'overall': 'F', 'error': str(e), 'usable': False}
