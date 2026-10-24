#!/usr/bin/env bash
# Starts the shared brain (the memory MCP server) on brain/memory.jsonl in this repository,
# whatever folder Claude Code was started from. Used by .mcp.json.
cd "$(dirname "$0")/.." || exit 1
export MEMORY_FILE_PATH="$PWD/brain/memory.jsonl"
exec npx -y @modelcontextprotocol/server-memory
