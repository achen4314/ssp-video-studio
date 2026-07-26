"""Render orchestration — Manim, TTS, ffmpeg + real-time SSE logs"""
from flask import Blueprint, request, jsonify
import os, json, subprocess, threading, time, shutil, re, queue
from pathlib import Path
from datetime import datetime

bp = Blueprint('render', __name__)

from backend.database import get_db, Project, Scene, RenderJob
from backend.config import PROJECTS_DIR, AI_KEPU_DIR
from backend.app import emit_log

@bp.route('/api/projects/<int:pid>/render/manim', methods=['POST'])
def render_manim(pid):
    data = request.get_json() or {}
    quality = data.get('quality', 'ql')
    
    db = get_db()
    try:
        p = db.query(Project).get(pid)
        if not p:
            return jsonify({'error': 'not_found'}), 404
        
        project_dir = PROJECTS_DIR / p.slug
        script_files = list(project_dir.glob('scenes_*.py'))
        
        if not script_files:
            kepu_dir = AI_KEPU_DIR / p.slug
            if kepu_dir.exists():
                script_files = list(kepu_dir.glob('scenes_*.py'))
        
        if not script_files:
            return jsonify({'error': 'no scene scripts found — generate scripts first'}), 400
        
        emit_log(pid, f'🎬 Starting Manim render ({quality}) — {len(script_files)} files')
        
        jobs = []
        for sf in script_files:
            with open(sf, 'r', encoding='utf-8') as f:
                code = f.read()
            scene_classes = re.findall(r'class\s+(S\d+_\w+)\(KepuScene\)', code)
            if not scene_classes:
                continue
            
            cmd = f'cd "{project_dir}" && manim -{quality} {sf.name} {" ".join(scene_classes)}'
            
            job = RenderJob(project_id=pid, job_type=f'manim_{quality}', command=cmd, status='queued')
            db.add(job)
            db.flush()
            jobs.append(job.id)
            emit_log(pid, f'  📝 Queued: {sf.name} → {", ".join(scene_classes)}')
        
        db.commit()
        
        p.status = 'rendering'
        p.progress = 10
        db.commit()
        
        # Background render
        t = threading.Thread(target=_run_render_jobs, args=(pid, jobs), daemon=True)
        t.start()
        
        return jsonify({'status': 'started', 'jobs': len(jobs)})
    finally:
        db.close()

@bp.route('/api/projects/<int:pid>/render/tts', methods=['POST'])
def render_tts(pid):
    db = get_db()
    try:
        p = db.query(Project).get(pid)
        if not p:
            return jsonify({'error': 'not_found'}), 404
        
        project_dir = PROJECTS_DIR / p.slug
        audio_dir = project_dir / 'audio'
        audio_dir.mkdir(exist_ok=True)
        
        scenes = db.query(Scene).filter_by(project_id=pid).order_by(Scene.scene_number).all()
        if not scenes:
            return jsonify({'error': 'no scenes'}), 400
        
        emit_log(pid, f'🔊 Starting TTS — {len(scenes)} scenes')
        
        tts_jobs = []
        for s in scenes:
            if not s.narration_text:
                continue
            
            txt_path = audio_dir / f'{s.name}.txt'
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(s.narration_text)
            
            mp3_path = audio_dir / f'{s.name}.mp3'
            cmd = f'edge-tts --voice zh-CN-XiaoxiaoNeural -f "{txt_path}" --write-media "{mp3_path}"'
            
            job = RenderJob(project_id=pid, scene_id=s.id, job_type='tts', command=cmd, status='queued')
            db.add(job)
            db.flush()
            tts_jobs.append(job.id)
        
        db.commit()
        
        p.status = 'tts'
        p.progress = 50
        db.commit()
        
        t = threading.Thread(target=_run_tts_jobs, args=(pid, tts_jobs), daemon=True)
        t.start()
        
        return jsonify({'status': 'started', 'jobs': len(tts_jobs)})
    finally:
        db.close()

@bp.route('/api/projects/<int:pid>/render/assemble', methods=['POST'])
def assemble_video(pid):
    db = get_db()
    try:
        p = db.query(Project).get(pid)
        if not p:
            return jsonify({'error': 'not_found'}), 404
        
        project_dir = PROJECTS_DIR / p.slug
        audio_dir = project_dir / 'audio'
        scenes = db.query(Scene).filter_by(project_id=pid).order_by(Scene.scene_number).all()
        
        emit_log(pid, f'🎬 Starting assembly — {len(scenes)} scenes')
        
        concat_entries = []
        for s in scenes:
            video_path = None
            search_dirs = [project_dir / 'media' / 'videos', AI_KEPU_DIR / p.slug / 'media' / 'videos']
            for sd in search_dirs:
                if sd.exists():
                    for vf in sd.rglob(f'{s.name}.mp4'):
                        if '1080p60' in str(vf) or '480p15' in str(vf):
                            video_path = vf
                            break
                if video_path:
                    break
            
            if not video_path:
                emit_log(pid, f'  ⚠️ {s.name}: video not found', 'warn')
                continue
            
            audio_path = audio_dir / f'{s.name}.mp3'
            
            if audio_path.exists():
                out_path = project_dir / f'{s.name}_audio.mp4'
                cmd = (f'ffmpeg -y -stream_loop -1 -i "{video_path}" -i "{audio_path}" '
                       f'-c:v libx264 -preset fast -crf 18 -c:a aac -b:a 128k '
                       f'-shortest -movflags +faststart "{out_path}"')
                r = subprocess.run(cmd, shell=True, capture_output=True, timeout=120)
                if r.returncode == 0:
                    concat_entries.append(str(out_path))
                    emit_log(pid, f'  ✅ {s.name}: audio synced')
                else:
                    emit_log(pid, f'  ❌ {s.name}: sync failed', 'error')
            else:
                concat_entries.append(str(video_path))
                emit_log(pid, f'  ⚠️ {s.name}: no audio')
        
        if not concat_entries:
            emit_log(pid, '❌ No videos to assemble', 'error')
            return jsonify({'error': 'no videos', 'status': 'failed'}), 400
        
        concat_path = project_dir / 'concat.txt'
        with open(concat_path, 'w') as f:
            for entry in concat_entries:
                f.write(f"file '{entry}'\n")
        
        final_path = project_dir / 'final.mp4'
        cmd = f'ffmpeg -y -f concat -safe 0 -i "{concat_path}" -c copy -movflags +faststart "{final_path}"'
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=180)
        
        if final_path.exists():
            size_mb = final_path.stat().st_size / (1024 * 1024)
            emit_log(pid, f'✅ Assembly complete: {size_mb:.1f}MB')
            
            try:
                probe = subprocess.run(
                    f'ffprobe -v error -show_entries stream=codec_name,width,height,r_frame_rate,duration '
                    f'-of json "{final_path}"',
                    shell=True, capture_output=True, text=True, timeout=30
                )
                info = json.loads(probe.stdout)
                for s in info.get('streams', []):
                    emit_log(pid, f'  📹 {s.get("codec_name")} {s.get("width")}×{s.get("height")} {s.get("r_frame_rate")}')
            except:
                pass
            
            p.status = 'done'
            p.progress = 100
        else:
            emit_log(pid, f'❌ Assembly failed: {r.stderr[:300]}', 'error')
        
        db.commit()
        
        return jsonify({
            'status': 'done' if final_path.exists() else 'failed',
            'final_video': str(final_path) if final_path.exists() else None,
            'size_mb': round(size_mb, 1) if final_path.exists() else 0,
        })
    except Exception as e:
        emit_log(pid, f'❌ Error: {str(e)}', 'error')
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@bp.route('/api/render/jobs', methods=['GET'])
def list_jobs():
    pid = request.args.get('project_id')
    db = get_db()
    try:
        q = db.query(RenderJob)
        if pid:
            q = q.filter_by(project_id=int(pid))
        jobs = q.order_by(RenderJob.id.desc()).limit(50).all()
        return jsonify([{
            'id': j.id, 'project_id': j.project_id, 'job_type': j.job_type,
            'status': j.status, 'command': j.command[:200] if j.command else '',
            'log': (j.log or '')[-3000:],
            'started_at': j.started_at.isoformat() if j.started_at else None,
            'finished_at': j.finished_at.isoformat() if j.finished_at else None,
            'duration_s': j.duration_s,
        } for j in jobs])
    finally:
        db.close()

def _run_render_jobs(pid, job_ids):
    db = get_db()
    try:
        for jid in job_ids:
            job = db.query(RenderJob).get(jid)
            if not job: continue
            
            job.status = 'running'
            job.started_at = datetime.now()
            db.commit()
            
            emit_log(pid, f'  ▶️ Running: {job.job_type}')
            
            try:
                result = subprocess.run(
                    job.command, shell=True,
                    capture_output=True, text=True,
                    timeout=900,  # 15 min
                    cwd=str(PROJECTS_DIR / db.query(Project).get(pid).slug)
                )
                job.log = (result.stdout[-5000:] + '\n---STDERR---\n' + result.stderr[-2000:])
                job.status = 'done' if result.returncode == 0 else 'failed'
                emit_log(pid, f'  {"✅" if result.returncode == 0 else "❌"} Done: {job.job_type} (rc={result.returncode})')
            except subprocess.TimeoutExpired:
                job.status = 'failed'
                job.log = 'TIMEOUT (15 min)'
                emit_log(pid, f'  ⏰ Timeout: {job.job_type}', 'error')
            except Exception as e:
                job.status = 'failed'
                job.log = str(e)
                emit_log(pid, f'  ❌ Error: {e}', 'error')
            
            job.finished_at = datetime.now()
            job.duration_s = (job.finished_at - job.started_at).total_seconds()
            db.commit()
        
        p = db.query(Project).get(pid)
        jobs_done = db.query(RenderJob).filter_by(project_id=pid, status='done').count()
        jobs_total = db.query(RenderJob).filter_by(project_id=pid).count()
        if jobs_done == jobs_total:
            p.status = 'scripting'
        p.progress = min(90, int(30 + jobs_done / max(1, jobs_total) * 60))
        db.commit()
        emit_log(pid, f'🏁 Render phase complete: {jobs_done}/{jobs_total} jobs done')
    finally:
        db.close()

def _run_tts_jobs(pid, job_ids):
    db = get_db()
    try:
        p = db.query(Project).get(pid)
        project_dir = PROJECTS_DIR / p.slug
        
        for jid in job_ids:
            job = db.query(RenderJob).get(jid)
            if not job: continue
            
            job.status = 'running'
            job.started_at = datetime.now()
            db.commit()
            
            try:
                result = subprocess.run(job.command, shell=True, capture_output=True, text=True, timeout=120)
                job.log = result.stdout[-1000:] + '\n' + result.stderr[-500:]
                job.status = 'done' if result.returncode == 0 else 'failed'
                
                if result.returncode == 0 and job.scene_id:
                    scene = db.query(Scene).get(job.scene_id)
                    if scene:
                        scene.audio_file = str(project_dir / 'audio' / f'{scene.name}.mp3')
                        scene.status = 'audio_done'
                
                emit_log(pid, f'  {"✅" if result.returncode == 0 else "❌"} TTS: {job.job_type}')
            except Exception as e:
                job.status = 'failed'
                job.log = str(e)
                emit_log(pid, f'  ❌ TTS error: {e}', 'error')
            
            job.finished_at = datetime.now()
            job.duration_s = (job.finished_at - job.started_at).total_seconds()
            db.commit()
        
        p.status = 'qc'
        p.progress = 80
        db.commit()
        emit_log(pid, '🏁 TTS phase complete')
    finally:
        db.close()
