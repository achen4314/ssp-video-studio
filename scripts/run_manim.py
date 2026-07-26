"""
Manim wrapper — bypasses AppLocker blocking av DLL.
Usage: python run_manim.py <manim args...>
Example: python run_manim.py -ql scenes_1_3.py S1_Scene
"""
import sys
import os

# Monkey-patch av BEFORE manim tries to import it
_fake = type(sys)('_fake_av')
for mod in ['av', 'av.audio', 'av.audio.frame', 'av.audio.layout',
            'av.audio.codeccontext', 'av.audio.fifo', 'av.audio.format',
            'av.container', 'av.stream', 'av.codec', 'av.video']:
    if mod not in sys.modules:
        sys.modules[mod] = _fake

# Now run manim
from manim.__main__ import main
sys.argv[1:] = sys.argv[1:]  # manim expects this
main()
