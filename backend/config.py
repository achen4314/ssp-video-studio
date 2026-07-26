"""
Configuration — paths and settings.
All paths are configurable via environment variables for cloud deployment.
"""
import os
from pathlib import Path

# Base directory (works both locally and on Render)
BASE_DIR = Path(__file__).resolve().parent.parent

# Data directory — configurable for Render's /opt/render/project
DATA_DIR = Path(os.environ.get('DATA_DIR', BASE_DIR / 'data'))
PROJECTS_DIR = DATA_DIR / 'projects'
SCRIPTS_DIR = BASE_DIR / 'scripts'

# Obsidian vault path (local only; cloud uses upload flow)
OBSIDIAN_VAULT = Path(os.environ.get('OBSIDIAN_VAULT', 
    os.path.expanduser('~/Desktop/微信公众号内容')))

# Manim projects dir
AI_KEPU_DIR = Path(os.environ.get('AI_KEPU_DIR', 'D:/ai-kepu'))

# Database
DB_PATH = DATA_DIR / 'studio.db'

# Render mode detection
IS_RENDER = bool(os.environ.get('RENDER'))

# Ensure directories
for d in [DATA_DIR, PROJECTS_DIR, SCRIPTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)
