#!/usr/bin/env bash
# Evaluation scorecard runner — checkpoint & gate tracking
#
# Usage:
#   ./run_evaluation.sh                    # auto checkpoint/gate
#   ./run_evaluation.sh checkpoint       # paksa checkpoint
#   ./run_evaluation.sh gate1            # paksa evaluasi gate 1
#   LESSONS="INKP lemah" ./run_evaluation.sh
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

export PYTHONIOENCODING=utf-8
export PYTHONUNBUFFERED=1

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo "python3/python tidak ditemukan" >&2
  exit 1
fi

EVAL_TYPE="${1:-auto}"
LESSONS="${LESSONS:-}"
IMPROVEMENTS="${IMPROVEMENTS:-}"

ARGS=(--type "$EVAL_TYPE")
[ -n "$LESSONS" ] && ARGS+=(--lessons "$LESSONS")
[ -n "$IMPROVEMENTS" ] && ARGS+=(--improvements "$IMPROVEMENTS")

echo "▶ Evaluation scorecard | type=${EVAL_TYPE} | $(date +%Y-%m-%d)"

if ! "$PYTHON" evaluate_cycle.py "${ARGS[@]}"; then
  echo "❌ Evaluation gagal" >&2
  exit 1
fi

echo ""
echo "📁 Output:"
echo "   reports/evaluation/cycles.json"
echo "   reports/evaluation/reports/latest.md"
echo "   reports/evaluation/snapshots/"
