"""SSE log stream — shared between app.py and render_routes.py"""
import queue
from datetime import datetime

_log_streams = {}  # project_id → queue.Queue

def get_log_stream(project_id):
    if project_id not in _log_streams:
        _log_streams[project_id] = queue.Queue()
    return _log_streams[project_id]

def emit_log(project_id, message, level='info'):
    """Push a log message to the SSE stream for a project"""
    if project_id in _log_streams:
        try:
            _log_streams[project_id].put_nowait({
                'time': datetime.now().strftime('%H:%M:%S'),
                'level': level,
                'message': message,
            })
        except queue.Full:
            pass
