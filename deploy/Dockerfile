# Agents HQ, hosted: the app, Claude Code, ffmpeg and local speech-to-text in one image.
# Build from the repository root:  docker build -f deploy/Dockerfile -t agents-hq .
FROM node:22-bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pip ffmpeg git ca-certificates bash \
 && rm -rf /var/lib/apt/lists/*
RUN npm install -g @anthropic-ai/claude-code \
 && pip3 install --no-cache-dir --break-system-packages numpy pillow faster-whisper

WORKDIR /app
COPY . .

# the owner's data (inbox, out, done, approved, brain, model cache) lives on the volume at /data
ENV HQ_HOST=0.0.0.0 HQ_PORT=7331 HQ_DATA=/data HF_HOME=/data/cache WHISPER_MODEL=small.en
VOLUME ["/data"]
EXPOSE 7331
ENTRYPOINT ["bash", "deploy/entrypoint.sh"]
