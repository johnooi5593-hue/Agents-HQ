#!/usr/bin/env bash
# Hosted Agents HQ: keep the owner's folders on the volume at $HQ_DATA, check the secrets, start the app.
# Runs when the container starts; it is not one of the team's commands.
set -e
cd "$(dirname "$0")/.."
DATA="${HQ_DATA:-/data}"

[ -n "$HQ_PASSWORD" ] || { echo "Set HQ_PASSWORD (the login password) before starting the hosted app."; exit 1; }
[ -n "$ANTHROPIC_API_KEY" ] || echo "Warning: ANTHROPIC_API_KEY is not set, the lead cannot run (claude -p needs it on a server)."

for d in inbox inbox/radar inbox/stats out done approved brain cache; do mkdir -p "$DATA/$d"; done
[ -f "$DATA/brain/memory.jsonl" ] || cp brain/memory.jsonl "$DATA/brain/memory.jsonl"    # seed the brain once

# the repository copies of these folders are replaced by links into the volume, so uploads and work survive restarts
for d in inbox out done approved brain; do
  if [ ! -L "$d" ]; then rm -rf "$d"; ln -s "$DATA/$d" "$d"; fi
done

exec python3 hq/server.py --no-browser
