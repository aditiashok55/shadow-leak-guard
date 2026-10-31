#!/usr/bin/env bash
# Milestone 1: reproduce the leak with a single command.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Ingesting corpus into ChromaDB (ACL stored, not enforced)..."
python src/ingest.py

echo
echo "==> BASELINE (no ACL): intern asks a benign question"
python src/pipeline.py \
  --role intern \
  --query "What's the plan for next quarter's team changes?"
