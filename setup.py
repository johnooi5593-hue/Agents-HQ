"""Agents HQ, one-time setup for any OS (Windows, macOS, Linux). Same steps as setup.sh.

usage: python setup.py      (python3 setup.py on macOS/Linux)
"""
import json, os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
py = sys.executable

if sys.version_info < (3, 10):
    sys.exit("Python 3.10 or newer is needed. Install it from https://www.python.org/downloads/")
if not shutil.which("ffmpeg"):
    sys.exit("Install ffmpeg first (Windows: winget install -e --id Gyan.FFmpeg, then open a new window; macOS: brew install ffmpeg)")
if not shutil.which("npx"):
    sys.exit("Install Node.js 18+ first (it runs the shared-brain memory server): https://nodejs.org")
if not shutil.which("claude"):
    print("Note: Claude Code is not on PATH yet. Install it with: npm install -g @anthropic-ai/claude-code")

subprocess.check_call([py, "-m", "pip", "install", "--quiet", "numpy", "pillow"])
if subprocess.call([py, "-m", "pip", "install", "--quiet", "faster-whisper"]) == 0:
    print("speech-to-text: faster-whisper (downloads its model on first use)")
else:
    print("faster-whisper did not install. Captions will not work until it does: python -m pip install faster-whisper")

for d in ("inbox/radar", "inbox/stats", "out", "done", "approved", "brain"):
    os.makedirs(d, exist_ok=True)
if not os.path.isfile("brain/memory.jsonl"):
    with open("brain/memory.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "entity", "name": "Brand rules", "entityType": "style_guide", "observations": []}) + "\n")

subprocess.call([py, os.path.join("hq", "status.py")])
open_cmd = "double-click 'Open Agents HQ.bat'" if os.name == "nt" else "double-click 'Open Agents HQ.command'"
print("\nAgents HQ is ready.")
print(f"  Open the app:        python hq/server.py   (or {open_cmd})")
print("  Or use the terminal: claude   then type /standup")
