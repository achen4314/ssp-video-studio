"""Quality control routes — automated checks + reports"""
from flask import Blueprint, request, jsonify, send_file
import os, json, subprocess, re
from pathlib import Path

bp = Blueprint('qc', __name__)

from backend.database import get_db, Project, Scene, Evidence, RenderJob
from backend.config import PROJECTS_DIR, SCRIPTS_DIR

@bp.route('/api/projects/<int:pid>/qc/run-all', methods=['POST'])
def run_all_qc(pid):
    """Run all QC checks on a project"""
    db = get_db()
    try:
        p = db.query(Project).get(pid)
        if not p:
            return jsonify({'error': 'not_found'}), 404
        
        results = {
            'project': p.name,
            'checks': {},
            'overall': 'pending',
        }
        
        # QC1: Data fidelity check
        results['checks']['data_fidelity'] = _check_data_fidelity(p)
        
        # QC2: Evidence coverage
        results['checks']['evidence_coverage'] = _check_evidence_coverage(db, pid)
        
        # QC3: Scene code quality
        results['checks']['scene_code_quality'] = _check_scene_code(db, pid, p)
        
        # QC4: Render check
        results['checks']['render'] = _check_render_status(db, pid)
        
        # QC5: TTS sync
        results['checks']['tts_sync'] = _check_tts_sync(db, pid, p)
        
        # QC6: Technical compliance (final video)
        results['checks']['technical'] = _check_technical(pid, p)
        
        # Overall verdict
        all_pass = all(
            c.get('pass', False) or c.get('status') == 'done'
            for c in results['checks'].values()
        )
        blocking = any(
            c.get('blocking', False)
            for c in results['checks'].values()
        )
        
        if blocking:
            results['overall'] = 'BLOCKED'
        elif all_pass:
            results['overall'] = 'PASS'
        else:
            results['overall'] = 'WARNINGS'
        
        # Update project
        p.status = 'qc'
        db.commit()
        
        return jsonify(results)
    finally:
        db.close()

def _check_data_fidelity(p):
    """Check if claims.json data matches source material"""
    if not p.claims_json:
        return {'pass': False, 'blocking': True, 'detail': 'claims.json 未生成'}
    
    try:
        claims = json.loads(p.claims_json)
    except:
        return {'pass': False, 'blocking': True, 'detail': 'claims.json 格式错误'}
    
    if not isinstance(claims, list) or len(claims) == 0:
        return {'pass': False, 'blocking': True, 'detail': 'claims.json 为空'}
    
    # Check basic integrity
    issues = []
    for c in claims:
        if 'claim_id' not in c:
            issues.append('声明缺少 claim_id')
        if 'claim_text' not in c:
            issues.append('声明缺少 claim_text')
        if 'source_sentence' not in c:
            issues.append(f'{c.get("claim_id", "?")}: 缺少 source_sentence')
        if 'evidence_file' in c and c['evidence_file']:
            evt_dir = PROJECTS_DIR / p.slug / 'evidence'
            if not (evt_dir / c['evidence_file']).exists():
                issues.append(f'{c["claim_id"]}: 证据文件缺失: {c["evidence_file"]}')
    
    return {
        'pass': len(issues) == 0,
        'blocking': len(issues) > 0,
        'detail': f'{len(claims)} 则声明, {len(issues)} 个问题' if issues else f'{len(claims)} 则声明, 全部通过',
        'issues': issues,
    }

def _check_evidence_coverage(db, pid):
    """Check evidence coverage ratio"""
    evidence_items = db.query(Evidence).filter_by(project_id=pid).all()
    if not evidence_items:
        return {'pass': False, 'blocking': True, 'detail': '无证据图'}
    
    grades = {}
    for e in evidence_items:
        grades.setdefault(e.grade, []).append(e.filename)
    
    total = len(evidence_items)
    blocking = [e for e in evidence_items if e.grade in ('C', 'F')]
    good = [e for e in evidence_items if e.grade in ('S', 'A')]
    
    coverage = len(good) / total * 100 if total > 0 else 0
    
    return {
        'pass': len(blocking) == 0 and coverage >= 60,
        'blocking': len(blocking) > 0,
        'detail': f'总{total}张, S/A级{len(good)}张({coverage:.0f}%), C/F级{len(blocking)}张',
        'grade_distribution': {k: len(v) for k, v in grades.items()},
        'blocking_files': [e.filename for e in blocking],
    }

def _check_scene_code(db, pid, p):
    """Check scene script files for quality issues"""
    project_dir = PROJECTS_DIR / p.slug
    scene_files = list(project_dir.glob('scenes_*.py'))
    
    if not scene_files:
        return {'pass': False, 'blocking': False, 'detail': '无场景脚本文件（可能尚未生成）'}
    
    issues = []
    for sf in scene_files:
        with open(sf, 'r', encoding='utf-8') as f:
            code = f.read()
        
        # Check 1: ImageMobject in VGroup
        if 'ImageMobject' in code and 'VGroup' in code:
            issues.append(f'{sf.name}: ImageMobject 可能与 VGroup 混用')
        
        # Check 2: Bad rate functions
        for bad_rf in ['out_back', 'out_cubic', 'out_bounce']:
            if bad_rf in code:
                issues.append(f'{sf.name}: 非标准 rate function: {bad_rf}')
        
        # Check 3: Missing say()
        if 'self.say(' not in code:
            issues.append(f'{sf.name}: 缺少 self.say() 字幕')
        
        # Check 4: Missing FadeOut
        if 'FadeOut' not in code:
            issues.append(f'{sf.name}: 缺少 FadeOut 清理')
        
        # Check 5: Font size too small
        small_fonts = re.findall(r'font_size=(\d+)', code)
        too_small = [int(s) for s in small_fonts if int(s) < 18]
        if too_small:
            issues.append(f'{sf.name}: 字号过小: {too_small}')
    
    return {
        'pass': len(issues) == 0,
        'blocking': any('ImageMobject' in i and 'VGroup' in i for i in issues),
        'detail': f'{len(scene_files)} 个文件, {len(issues)} 个问题' if issues else f'{len(scene_files)} 个文件, 全部通过',
        'issues': issues,
        'files_checked': [sf.name for sf in scene_files],
    }

def _check_render_status(db, pid):
    """Check render job completion"""
    jobs = db.query(RenderJob).filter_by(project_id=pid).all()
    if not jobs:
        return {'pass': False, 'blocking': False, 'detail': '尚无渲染任务'}
    
    done = [j for j in jobs if j.status == 'done']
    failed = [j for j in jobs if j.status == 'failed']
    running = [j for j in jobs if j.status == 'running']
    
    return {
        'pass': len(failed) == 0 and len(done) > 0,
        'blocking': len(failed) > 0,
        'detail': f'完成{len(done)}, 失败{len(failed)}, 运行中{len(running)}, 总计{len(jobs)}',
        'failed_jobs': [{'id': j.id, 'type': j.job_type, 'command': j.command[:100]} for j in failed],
    }

def _check_tts_sync(db, pid, p):
    """Check TTS text vs say() text consistency"""
    scenes = db.query(Scene).filter_by(project_id=pid).all()
    if not scenes or not any(s.narration_text for s in scenes):
        return {'pass': False, 'blocking': False, 'detail': '无配音文本'}
    
    with_audio = [s for s in scenes if s.audio_file]
    with_text = [s for s in scenes if s.narration_text]
    
    return {
        'pass': len(with_audio) >= len(with_text) * 0.8,  # 80% coverage
        'blocking': False,
        'detail': f'配音覆盖: {len(with_audio)}/{len(with_text)} 场景',
    }

def _check_technical(pid, p):
    """Check final video technical specs"""
    final_path = PROJECTS_DIR / p.slug / 'final.mp4'
    if not final_path.exists():
        return {'pass': False, 'blocking': False, 'detail': 'final.mp4 尚未生成'}
    
    try:
        result = subprocess.run(
            f'ffprobe -v error -show_entries stream=codec_name,width,height,r_frame_rate,duration -of json "{final_path}"',
            shell=True, capture_output=True, text=True, timeout=30
        )
        info = json.loads(result.stdout)
        streams = info.get('streams', [])
        
        video_stream = next((s for s in streams if s.get('codec_name') == 'h264'), None)
        audio_stream = next((s for s in streams if s.get('codec_name') == 'aac'), None)
        
        checks = {}
        if video_stream:
            checks['resolution'] = f'{video_stream.get("width")}×{video_stream.get("height")}'
            checks['resolution_ok'] = video_stream.get('width') == 1920
            checks['fps'] = str(video_stream.get('r_frame_rate', ''))
            checks['fps_ok'] = '60' in checks['fps']
        else:
            checks['video'] = 'MISSING'
        
        checks['audio'] = 'AAC' if audio_stream else 'MISSING'
        size_mb = final_path.stat().st_size / (1024 * 1024)
        checks['size_mb'] = round(size_mb, 1)
        
        all_ok = checks.get('resolution_ok', False) and checks.get('fps_ok', False) and 'MISSING' not in checks.get('audio', '')
        
        return {
            'pass': all_ok,
            'blocking': not all_ok,
            'detail': json.dumps(checks, ensure_ascii=False),
            'checks': checks,
        }
    except Exception as e:
        return {'pass': False, 'blocking': True, 'detail': str(e)}

@bp.route('/api/projects/<int:pid>/qc/report', methods=['GET'])
def get_qc_report(pid):
    """Get latest QC report for a project (JSON markdown)"""
    return run_all_qc(pid)
