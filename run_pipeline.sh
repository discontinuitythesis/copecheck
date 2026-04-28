#!/usr/bin/env bash
# CopeCheck v2 pipeline runner
set -euo pipefail
cd "$(dirname "$0")"
export $(grep -v '^#' .env | grep -v '^$' | xargs)
mkdir -p logs
exec ./venv/bin/python3 pipeline.py "${1:-all}" >> logs/pipeline.log 2>&1
