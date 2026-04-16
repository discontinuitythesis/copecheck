#!/usr/bin/env bash
# CopeCheck v2 pipeline runner
set -euo pipefail
cd "$(dirname "$0")"
source .env 2>/dev/null || true
export STRAICO_API_KEY ORACLE_MODEL ORACLE_FALLBACK COPECHECK_PORT COPECHECK_MAX_NEW COPECHECK_MAX_ANALYSE
mkdir -p logs
exec ./venv/bin/python3 pipeline.py "${1:-all}" >> logs/pipeline.log 2>&1
