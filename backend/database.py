"""
Database models + session factory.
Uses config.DB_PATH — works locally (SQLite file) and on Render.
"""
import json
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Session, relationship

from backend.config import DB_PATH

class Base(DeclarativeBase):
    pass

engine = create_engine(f'sqlite:///{DB_PATH}', echo=False, 
                        connect_args={'check_same_thread': False})

class Project(Base):
    __tablename__ = 'projects'
    id = Column(Integer, primary_key=True)
    name = Column(String(200))
    slug = Column(String(100), unique=True)
    source_note = Column(String(500))
    source_score = Column(Float, default=0)
    status = Column(String(30), default='draft')
    plan_md = Column(Text, default='')
    claims_json = Column(Text, default='')
    evidence_map = Column(Text, default='')
    progress = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    scenes = relationship('Scene', back_populates='project', cascade='all, delete-orphan')
    evidence_items = relationship('Evidence', back_populates='project', cascade='all, delete-orphan')

class Scene(Base):
    __tablename__ = 'scenes'
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey('projects.id'))
    name = Column(String(100))
    scene_number = Column(Integer)
    script_file = Column(String(300))
    narration_text = Column(Text)
    audio_file = Column(String(300))
    video_file = Column(String(300))
    claims_covered = Column(Text)
    status = Column(String(30), default='pending')
    render_log = Column(Text)
    duration_s = Column(Float)
    
    project = relationship('Project', back_populates='scenes')

class Evidence(Base):
    __tablename__ = 'evidence'
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey('projects.id'))
    filename = Column(String(200))
    original_path = Column(String(500))
    enhanced_path = Column(String(500))
    claims_linked = Column(Text)
    grade = Column(String(5))
    resolution = Column(String(20))
    size_kb = Column(Float)
    source_doi = Column(String(200))
    chart_type = Column(String(50))
    status = Column(String(30), default='pending')
    
    project = relationship('Project', back_populates='evidence_items')

class RenderJob(Base):
    __tablename__ = 'render_jobs'
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey('projects.id'))
    scene_id = Column(Integer, ForeignKey('scenes.id'), nullable=True)
    job_type = Column(String(30))
    command = Column(Text)
    status = Column(String(30), default='queued')
    log = Column(Text, default='')
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    duration_s = Column(Float)

Base.metadata.create_all(engine)

def get_db():
    return Session(engine)
