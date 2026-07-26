"""
Manim wrapper: mock av → render PNG frames → ffmpeg convert to MP4.
"""
import sys, os, re, glob, subprocess
from pathlib import Path
from collections import defaultdict

# ═══ Mock av ═══
class FM: pass
for mn in ['av','av.audio','av.audio.frame','av.audio.layout','av.audio.codeccontext',
           'av.audio.fifo','av.audio.format','av.container','av.stream','av.codec',
           'av.video','av.video.frame','av.video.format','av.video.codeccontext',
           'av.error','av.filter','av.packet','av.sidedata','av.subtitles',
           'av.datasets','av.bitstream']:
    if mn not in sys.modules: sys.modules[mn] = FM()
av = sys.modules['av']
av.open = type('C',(),{'__init__':lambda s,*a,**kw:None,'__enter__':lambda s:s,'__exit__':lambda s,*a:None,'add_stream':lambda s,*a,**kw:type('S',(),{'encode':lambda s,f=None:[]})(),'close':lambda s:None,'streams':type('SS',(),{'video':[type('VS',(),{'encode':lambda s,f=None:[]})()]})()})()
av.VideoFrame = type('VF',(),{'from_ndarray':staticmethod(lambda a,**kw:a),'from_image':staticmethod(lambda i:i)})()
av.AudioFrame = type('AF',(),{'from_ndarray':staticmethod(lambda a,**kw:a)})()
av.AudioResampler = type('AR',(),{'__init__':lambda s,*a,**kw:None,'resample':lambda s,f:f})()
av.CodecContext = type('CC',(),{'create':staticmethod(lambda *a,**kw:None)})()
av.error = FM()
av.error.InvalidArgument = type('E',(Exception,),{})

# ═══ Parse args ═══
args = sys.argv[1:]
quality = '-ql'
for a in args:
    if a.startswith('-q'): quality = a; break
QMAP = {'-ql': ('480p15',15), '-qm': ('720p30',30), '-qh': ('1080p60',60)}
res_key, fps = QMAP.get(quality, ('480p15',15))
RES_MAP = {'-ql': '854,480', '-qm': '1280,720', '-qh': '1920,1080'}

# Build manim args
manim_args = []
for a in args:
    if not a.startswith('-q'): manim_args.append(a)
manim_args = ['--format=png', '-r', RES_MAP.get(quality,'854,480')] + manim_args
sys.argv = ['manim'] + manim_args

# ═══ Step 1: Render PNGs ═══
print("[SSP] Rendering PNG frames...", flush=True)
from manim.__main__ import main
try:
    main()
except SystemExit:
    pass

# ═══ Step 2: Convert PNGs → MP4 ═══
media = Path('media')
images_dir = media / 'images'
if not images_dir.exists():
    print("[SSP] No images — done", flush=True)
    sys.exit(0)

converted = 0
for script_dir in images_dir.iterdir():
    if not script_dir.is_dir(): continue
    
    # Group PNGs by scene name prefix
    scene_frames = defaultdict(list)
    for png in sorted(script_dir.glob('*.png')):
        stem = png.stem
        # Remove trailing digits to get scene name
        scene_name = re.sub(r'\d+$', '', stem)
        scene_frames[scene_name].append(png)
    
    for scene_name, frames in scene_frames.items():
        if len(frames) < 2: continue  # need at least 2 frames
        
        video_dir = media / 'videos' / script_dir.name / res_key
        video_dir.mkdir(parents=True, exist_ok=True)
        out = video_dir / f'{scene_name}.mp4'
        
        # Write concat file
        concat = video_dir / f'{scene_name}_concat.txt'
        with open(concat, 'w') as f:
            for p in sorted(frames):
                f.write(f"file '{p.absolute()}'\n")
        
        cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-r', str(fps),
               '-i', str(concat), '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
               '-pix_fmt', 'yuv420p', str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        
        if out.exists():
            print(f"[SSP] ✅ {scene_name} → {out.stat().st_size//1024}KB", flush=True)
            converted += 1
        else:
            print(f"[SSP] ❌ {scene_name}: {r.stderr[:150]}", flush=True)

print(f"[SSP] Done: {converted} MP4s", flush=True)
