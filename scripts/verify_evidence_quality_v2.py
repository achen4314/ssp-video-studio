#!/usr/bin/env python3
"""
verify_evidence_quality_v2.py — 多维度证据图质量检测
用法: python verify_evidence_quality_v2.py <image_path>
输出: JSON 质量报告
"""
import sys, os, json
from PIL import Image, ImageStat

CHART_TYPE_SPECS = {
    'forest_plot':   {'min_w': 800, 'rec_w': 1400, 'min_h': 600},
    'funnel_plot':   {'min_w': 800, 'rec_w': 1200, 'min_h': 800},
    'bar_chart':     {'min_w': 800, 'rec_w': 1200, 'min_h': 600},
    'line_chart':    {'min_w': 900, 'rec_w': 1400, 'min_h': 600},
    'scatter_plot':  {'min_w': 800, 'rec_w': 1200, 'min_h': 800},
    'flow_diagram':  {'min_w': 800, 'rec_w': 1000, 'min_h': 1000},
    'pathway':       {'min_w': 1000, 'rec_w': 1600, 'min_h': 700},
    'heatmap':       {'min_w': 800, 'rec_w': 1200, 'min_h': 600},
    'microscopy':    {'min_w': 1200, 'rec_w': 2000, 'min_h': 900},
    'table':         {'min_w': 1000, 'rec_w': 1400, 'min_h': 600},
    'title_page':    {'min_w': 800, 'rec_w': 1000, 'min_h': 1100},
    'formula':       {'min_w': 600, 'rec_w': 1000, 'min_h': 400},
    'unknown':       {'min_w': 800, 'rec_w': 1200, 'min_h': 800},
}

def detect_chart_type(filename):
    name_lower = filename.lower()
    if any(kw in name_lower for kw in ['forest', 'forestplot', '森林']): return 'forest_plot'
    if any(kw in name_lower for kw in ['funnel', '漏斗']): return 'funnel_plot'
    if any(kw in name_lower for kw in ['fig', 'bar', '柱', 'chart']): return 'bar_chart'
    if any(kw in name_lower for kw in ['line', 'time', 'trend', 'curve', '曲线']): return 'line_chart'
    if any(kw in name_lower for kw in ['scatter', 'corr', '散点', '相关']): return 'scatter_plot'
    if any(kw in name_lower for kw in ['prisma', 'flow', 'flowchart', '筛选']): return 'flow_diagram'
    if any(kw in name_lower for kw in ['pathway', '通路', 'metabolism', '代谢']): return 'pathway'
    if any(kw in name_lower for kw in ['heat', '热力', 'heatmap']): return 'heatmap'
    if any(kw in name_lower for kw in ['micro', 'he', 'stain', '染色', '组织']): return 'microscopy'
    if any(kw in name_lower for kw in ['table', 'tab', '表']): return 'table'
    if any(kw in name_lower for kw in ['title', '标题', 'abstract', '摘要']): return 'title_page'
    return 'unknown'

def assess_image(path):
    try:
        img = Image.open(path)
        w, h = img.size
        size_kb = os.path.getsize(path) / 1024
        
        chart_type = detect_chart_type(os.path.basename(path))
        spec = CHART_TYPE_SPECS.get(chart_type, CHART_TYPE_SPECS['unknown'])
        
        if w >= spec['rec_w'] and h >= spec['min_h']:
            res_grade = 'S'
        elif w >= spec['min_w'] and h >= spec['min_h']:
            res_grade = 'A' if w >= 1200 else 'B'
        elif w >= 800:
            res_grade = 'C'
        else:
            res_grade = 'F'
        
        stat = ImageStat.Stat(img)
        std = sum(stat.stddev) / len(stat.stddev)
        if std > 60: sharp_grade = 'A'
        elif std > 40: sharp_grade = 'B'
        elif std > 25: sharp_grade = 'C'
        else: sharp_grade = 'F'
        
        extrema = img.convert('L').getextrema()
        contrast_range = extrema[1] - extrema[0]
        if contrast_range > 180: contrast_grade = 'A'
        elif contrast_range > 120: contrast_grade = 'B'
        else: contrast_grade = 'C'
        
        grades = {'resolution': res_grade, 'sharpness': sharp_grade, 'contrast': contrast_grade}
        grade_values = {'S': 5, 'A': 4, 'B': 3, 'C': 2, 'F': 0}
        composite = sum(grade_values.get(g, 0) for g in grades.values()) / 3
        
        if composite >= 4.5: overall = 'S'
        elif composite >= 3.5: overall = 'A'
        elif composite >= 2.5: overall = 'B'
        elif composite >= 1.5: overall = 'C'
        else: overall = 'F'
        
        issues = []
        if res_grade == 'C': issues.append(f'分辨率不足: {w}×{h}, 建议 ≥ {spec["rec_w"]}×{spec["min_h"]}')
        if res_grade == 'F': issues.append(f'分辨率严重不足: {w}×{h}')
        if sharp_grade in ('C', 'F'): issues.append('图像模糊')
        if contrast_grade == 'C': issues.append('对比度低')
        
        return {
            'path': path,
            'filename': os.path.basename(path),
            'resolution': f'{w}×{h}',
            'size_kb': round(size_kb, 1),
            'detected_type': chart_type,
            'grades': grades,
            'overall': overall,
            'issues': issues,
            'usable': overall not in ('C', 'F'),
            'recommend_enhance': overall == 'B',
            'blocking': overall == 'F',
        }
    except Exception as e:
        return {'path': path, 'error': str(e), 'overall': 'F', 'usable': False, 'blocking': True}

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(json.dumps({'error': 'usage: python verify_evidence_quality_v2.py <image_path>'}, ensure_ascii=False))
        sys.exit(1)
    result = assess_image(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
