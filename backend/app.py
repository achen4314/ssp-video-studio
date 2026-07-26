"""
SSP Video Studio — AI运动科学科普视频本地/云端生产平台
======================================================
技术栈：Flask 3 + SQLAlchemy 2.0 + SQLite + gunicorn
本地: python backend/app.py          → http://127.0.0.1:5199
云端: gunicorn backend.app:app        → Render 自动分配端口
"""
import os, sys, json, threading, time, subprocess, shutil, re
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from flask_cors import CORS

# ═══════════════════════════════════
# App Init
# ═══════════════════════════════════
app = Flask(__name__,
            static_folder='static',
            template_folder='templates')
CORS(app)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'ssp-video-studio-2026')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB for video uploads

# ═══════════════════════════════════
# Imports (no circular deps)
# ═══════════════════════════════════
from backend.database import get_db, Project, Scene, Evidence, RenderJob
from backend.config import (
    BASE_DIR, DATA_DIR, PROJECTS_DIR, SCRIPTS_DIR,
    OBSIDIAN_VAULT, AI_KEPU_DIR, IS_RENDER
)
from backend.log_stream import get_log_stream, emit_log

# ═══════════════════════════════════
# Register blueprints
# ═══════════════════════════════════
from backend.routes.projects import bp as projects_bp
from backend.routes.evidence_routes import bp as evidence_bp
from backend.routes.scenes_routes import bp as scenes_bp
from backend.routes.render_routes import bp as render_bp
from backend.routes.qc_routes import bp as qc_bp
from backend.routes.obsidian_routes import bp as obsidian_bp

app.register_blueprint(projects_bp)
app.register_blueprint(evidence_bp)
app.register_blueprint(scenes_bp)
app.register_blueprint(render_bp)
app.register_blueprint(qc_bp)
app.register_blueprint(obsidian_bp)

# ═══════════════════════════════════
# Routes
# ═══════════════════════════════════
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/health')
def health():
    """Health check + capability detection"""
    # Try detecting manim via wrapper
    manim_ok = False
    try:
        wrapper = SCRIPTS_DIR / 'run_manim.py'
        r = subprocess.run(['python', str(wrapper), '--help'], capture_output=True, timeout=15)
        manim_ok = r.returncode == 0
    except:
        pass
    
    ffmpeg_ok = shutil.which('ffmpeg') is not None
    tts_ok = True  # edge-tts is pip-installed
    
    return jsonify({
        'status': 'ok',
        'version': '2.1.0',
        'render_mode': 'cloud' if IS_RENDER else 'local',
        'capabilities': {
            'manim': manim_ok,
            'manim_note': 'AppLocker blocks av DLL in this env; run manim in your own terminal' if not manim_ok else '',
            'ffmpeg': ffmpeg_ok,
            'edge_tts': tts_ok,
            'obsidian_vault': OBSIDIAN_VAULT.exists() if not IS_RENDER else False,
        },
        'paths': {
            'data_dir': str(DATA_DIR),
            'projects_dir': str(PROJECTS_DIR),
        }
    })

@app.route('/api/projects/<int:pid>/logs/stream')
def stream_logs(pid):
    """SSE endpoint for real-time render logs"""
    def generate():
        q = get_log_stream(pid)
        yield f'data: {json.dumps({"time": datetime.now().strftime("%H:%M:%S"), "level": "info", "message": "Stream connected"})}\n\n'
        while True:
            try:
                msg = q.get(timeout=30)
                yield f'data: {json.dumps(msg)}\n\n'
            except queue.Empty:
                yield f'data: {json.dumps({"time": datetime.now().strftime("%H:%M:%S"), "level": "heartbeat", "message": ""})}\n\n'
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )

@app.route('/api/projects/<int:pid>/video')
def serve_video(pid):
    """Serve the final assembled video"""
    from backend.database import get_db
    db = get_db()
    try:
        p = db.query(Project).get(pid)
        if not p:
            return jsonify({'error': 'not_found'}), 404
        final_path = PROJECTS_DIR / p.slug / 'final.mp4'
        if not final_path.exists():
            return jsonify({'error': 'video not yet assembled'}), 404
        from flask import send_file
        return send_file(final_path, mimetype='video/mp4')
    finally:
        db.close()

# ═══════════════════════════════════
# Startup
# ═══════════════════════════════════
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5199))
    debug = not IS_RENDER
    print(f"\n  🎬 SSP Video Studio v2.1")
    print(f"  ───────────────────────")
    print(f"  模式: {'☁️ 云端 (Render)' if IS_RENDER else '💻 本地'}")
    print(f"  地址: http://127.0.0.1:{port}" if not IS_RENDER else f"  端口: {port}")
    print(f"  数据: {DATA_DIR}")
    print(f"  项目: {PROJECTS_DIR}")
    print(f"  知识库: {OBSIDIAN_VAULT} ({'✓' if OBSIDIAN_VAULT.exists() else '✗ 不可用'})")
    print(f"\n  按 Ctrl+C 停止\n")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
