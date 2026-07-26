"""Obsidian vault integration routes"""
from flask import Blueprint, request, jsonify
import os, re, json
from pathlib import Path

bp = Blueprint('obsidian', __name__)

from backend.config import OBSIDIAN_VAULT

@bp.route('/api/obsidian/vault-info', methods=['GET'])
def vault_info():
    """Get Obsidian vault status and available notes"""
    if not OBSIDIAN_VAULT.exists():
        return jsonify({'error': 'vault not found', 'path': str(OBSIDIAN_VAULT)}), 404
    
    # List content directories
    dirs = []
    for d in OBSIDIAN_VAULT.iterdir():
        if d.is_dir() and not d.name.startswith('.') and d.name != 'hermes-kb':
            dirs.append(d.name)
    
    return jsonify({
        'path': str(OBSIDIAN_VAULT),
        'exists': True,
        'content_dirs': dirs,
    })

@bp.route('/api/obsidian/notes', methods=['GET'])
def list_notes():
    """List all .md notes in the vault with basic stats"""
    category = request.args.get('category', '')  # 运动营养, 运动训练, etc.
    
    search_dir = OBSIDIAN_VAULT
    if category:
        search_dir = OBSIDIAN_VAULT / category
    
    if not search_dir.exists():
        return jsonify({'error': f'directory not found: {search_dir}'}), 404
    
    notes = []
    for md_file in search_dir.rglob('*.md'):
        # Skip hidden dirs and hermes-kb
        if any(p.startswith('.') for p in md_file.parts):
            continue
        if 'hermes-kb' in str(md_file):
            continue
        
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except:
            continue
        
        size_kb = len(content.encode('utf-8')) / 1024
        h2_count = len(re.findall(r'^##\s', content, re.MULTILINE))
        refs = len(re.findall(r'\([A-Z][a-z]+\s*\d{4}[a-z]?\)', content))
        images = len(re.findall(r'!\[\[.*?\]\]', content))
        data_pts = len(re.findall(r'\d+\.?\d*\s*%', content))
        
        # Compute relative path from vault root
        rel_path = str(md_file.relative_to(OBSIDIAN_VAULT)).replace('\\', '/')
        
        notes.append({
            'path': rel_path,
            'name': md_file.stem,
            'size_kb': round(size_kb, 1),
            'h2_sections': h2_count,
            'references': refs,
            'embedded_images': images,
            'data_points': data_pts,
        })
    
    # Sort by size (largest first)
    notes.sort(key=lambda n: n['size_kb'], reverse=True)
    
    return jsonify({'notes': notes, 'count': len(notes), 'category': category or '全部'})

@bp.route('/api/obsidian/notes/<path:note_path>', methods=['GET'])
def get_note(note_path):
    """Read a specific note"""
    full_path = OBSIDIAN_VAULT / note_path
    if not full_path.exists():
        return jsonify({'error': 'not found'}), 404
    
    with open(full_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract embedded images
    images = re.findall(r'!\[\[(.*?)\]\]', content)
    
    # Extract references
    refs = re.findall(r'\(([A-Z][a-z]+(?:\s+et\s+al\.?)?\s+\d{4}[a-z]?)\)', content)
    pmids = re.findall(r'PMID:?\s*(\d+)', content)
    dois = re.findall(r'(10\.\d{4,}/[^\s]+)', content)
    
    return jsonify({
        'path': note_path,
        'content': content,
        'size_kb': round(len(content.encode('utf-8')) / 1024, 1),
        'images': images,
        'references': refs,
        'pmids': pmids,
        'dois': dois,
    })

@bp.route('/api/obsidian/score', methods=['POST'])
def score_note():
    """Score a note for video production readiness"""
    data = request.get_json() or {}
    note_path = data.get('path', '')
    
    if not note_path:
        return jsonify({'error': 'path required'}), 400
    
    full_path = OBSIDIAN_VAULT / note_path
    if not full_path.exists():
        return jsonify({'error': f'not found: {full_path}'}), 404
    
    with open(full_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    size_kb = len(content.encode('utf-8')) / 1024
    h2_count = len(re.findall(r'^##\s', content, re.MULTILINE))
    h3_count = len(re.findall(r'^###\s', content, re.MULTILINE))
    refs = len(re.findall(r'\([A-Z][a-z]+\s*\d{4}[a-z]?\)', content))
    pmids = len(re.findall(r'PMID', content))
    dois = len(re.findall(r'DOI', content))
    images = len(re.findall(r'!\[\[.*?\]\]', content))
    data_pts = len(re.findall(r'\d+\.?\d*\s*%', content))
    practical = sum(content.count(kw) for kw in ['建议','应用','剂量','方案','策略','指南','实操'])
    visual = sum(content.count(kw) for kw in ['图','表','曲线','通路','机制','结构','流程','对比'])
    
    # Scoring
    if size_kb >= 50 and h2_count >= 5: completeness = 5
    elif size_kb >= 30 and h2_count >= 4: completeness = 4
    elif size_kb >= 15 and h2_count >= 3: completeness = 3
    elif size_kb >= 8 and h2_count >= 2: completeness = 2
    else: completeness = 1
    
    total_refs = refs + pmids + dois
    if total_refs >= 15 and images >= 7: evidence_score = 5
    elif total_refs >= 10 and images >= 5: evidence_score = 4
    elif total_refs >= 5 and images >= 3: evidence_score = 3
    elif total_refs >= 3: evidence_score = 2
    else: evidence_score = 1
    
    if data_pts >= 20: data_score = 5
    elif data_pts >= 12: data_score = 4
    elif data_pts >= 6: data_score = 3
    elif data_pts >= 3: data_score = 2
    else: data_score = 1
    
    if practical >= 8: practical_score = 5
    elif practical >= 5: practical_score = 4
    elif practical >= 3: practical_score = 3
    elif practical >= 1: practical_score = 2
    else: practical_score = 1
    
    if visual >= 10: visual_score = 5
    elif visual >= 6: visual_score = 4
    elif visual >= 3: visual_score = 3
    else: visual_score = 2
    
    weighted = completeness * 0.30 + evidence_score * 0.30 + data_score * 0.15 + practical_score * 0.15 + visual_score * 0.10
    
    if weighted >= 4.0: verdict = '可直接制作完整版视频'
    elif weighted >= 3.0: verdict = '可制作，但需补充证据图或数据'
    elif weighted >= 2.0: verdict = '建议先扩充源材料'
    else: verdict = '源材料不足，不适合视频化'
    
    return jsonify({
        'path': note_path,
        'size_kb': round(size_kb, 1),
        'h2_sections': h2_count,
        'h3_sections': h3_count,
        'references': total_refs,
        'embedded_images': images,
        'data_points': data_pts,
        'scores': {
            'completeness': completeness,
            'evidence': evidence_score,
            'data_density': data_score,
            'practical_value': practical_score,
            'visual_potential': visual_score,
        },
        'weighted_total': round(weighted, 2),
        'verdict': verdict,
    })

@bp.route('/api/obsidian/images', methods=['GET'])
def list_vault_images():
    """List all images in the vault"""
    images_dir = OBSIDIAN_VAULT / 'images'
    if not images_dir.exists():
        return jsonify({'images': [], 'count': 0})
    
    all_images = []
    for img in images_dir.rglob('*'):
        if img.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
            rel = str(img.relative_to(images_dir)).replace('\\', '/')
            all_images.append({
                'path': rel,
                'size_kb': round(img.stat().st_size / 1024, 1),
                'category': rel.split('/')[0] if '/' in rel else '',
            })
    
    return jsonify({'images': all_images, 'count': len(all_images)})
