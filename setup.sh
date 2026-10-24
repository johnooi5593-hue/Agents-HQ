#!/usr/bin/env bash
# Agents HQ, one-time setup: checks ffmpeg and Node, installs a local speech-to-text engine, creates the folders.
set -e
cd "$(dirname "$0")"
command -v ffmpeg >/dev/null || { echo "Install ffmpeg first (macOS: brew install ffmpeg, Debian/Ubuntu: sudo apt install ffmpeg)"; exit 1; }
command -v npx >/dev/null || { echo "Install Node.js 18+ first (it runs the shared-brain memory server)"; exit 1; }
command -v claude >/dev/null || echo "Note: Claude Code is not on PATH yet. Install it from https://claude.com/claude-code"
python3 -m pip install --quiet numpy pillow
if python3 -m pip install --quiet faster-whisper; then
  echo "speech-to-text: faster-whisper (downloads its model on first use)"
else
  echo "faster-whisper did not install, using sherpa-onnx Whisper instead"
  python3 -m pip install --quiet sherpa-onnx
  mkdir -p .claude/skills/reel/scripts/models
  curl -L -o /tmp/whisper-tiny.en.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-whisper-tiny.en.tar.bz2
  tar xjf /tmp/whisper-tiny.en.tar.bz2 -C .claude/skills/reel/scripts/models
fi
mkdir -p inbox/radar inbox/stats out done brain
[ -f brain/memory.jsonl ] || echo '{"type":"entity","name":"Brand rules","entityType":"style_guide","observations":[]}' > brain/memory.jsonl
python3 hq/status.py
echo
echo "Agents HQ is ready."
echo "  1. Put raw clips in inbox/, comments in inbox/radar/, analytics CSVs in inbox/stats/"
echo "  2. Start Claude Code here:  claude"
echo "  3. Type /standup to see the desk, or /edit-clips to put the team to work"
