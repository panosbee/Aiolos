#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════
#  XDART-Φ — Initialize Data Volume
#
#  Copies character_state.json and other identity files into
#  the Docker volume on first deployment. Run ONCE.
#
#  Usage: ./deploy/init-data.sh
# ══════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

GREEN='\033[0;32m'
NC='\033[0m'
info() { echo -e "${GREEN}[✓]${NC} $1"; }

echo "Initializing XDART-Φ data volume..."

# Ensure the volume exists
docker volume create xdart-phi_xdart-data 2>/dev/null || true

# Copy initial state files into the volume
docker run --rm \
    -v "$PWD":/src:ro \
    -v xdart-phi_xdart-data:/app/data \
    alpine sh -c '
        cp /src/character_state.json /app/data/
        cp /src/immediate_memory.json /app/data/
        cp /src/self_awareness_brief.json /app/data/
        cp /src/wisdom_calibration.json /app/data/
        # Create empty journals if they do not exist
        touch /app/data/introspection_log.jsonl
        touch /app/data/self_evolution_journal.jsonl
        touch /app/data/core_change_log.jsonl
        touch /app/data/curiosity_journal.jsonl
        echo "{}" > /app/data/curiosity_state.json 2>/dev/null || true
        # Create qdrant directory
        mkdir -p /app/data/qdrant_storage
        # Copy existing qdrant data if present
        if [ -d /src/qdrant_storage ] && [ "$(ls -A /src/qdrant_storage 2>/dev/null)" ]; then
            cp -r /src/qdrant_storage/* /app/data/qdrant_storage/ 2>/dev/null || true
        fi
        # Fix permissions (uid 999 = xdart user in container)
        chown -R 999:999 /app/data
    '

info "Data volume initialized with identity files"
info "Files in volume:"
docker run --rm -v xdart-phi_xdart-data:/app/data alpine ls -la /app/data/
