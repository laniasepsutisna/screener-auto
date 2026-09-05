#!/usr/bin/env bash
# Daily automation pipeline: top picks + evaluation scorecard (+ optional git commit)
#
# Usage:
#   ./run_daily.sh
#   GIT_COMMIT=1 ./run_daily.sh
#   SKIP_TOP_PICKS=1 ./run_daily.sh          # evaluation saja
#   EVAL_TYPE=checkpoint ./run_daily.sh
#   EVAL_TYPE=auto ./run_daily.sh            # auto: checkpoint / gate1 di end_date
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

export PYTHONIOENCODING=utf-8
export PYTHONUNBUFFERED=1

SKIP_TOP_PICKS="${SKIP_TOP_PICKS:-0}"
EVAL_TYPE="${EVAL_TYPE:-auto}"
GIT_COMMIT="${GIT_COMMIT:-0}"
STRICTNESS="${STRICTNESS:-balanced}"
LIMIT="${LIMIT:-5}"

TODAY="$(date +%Y-%m-%d)"
echo "══════════════════════════════════════════"
echo " Daily Pipeline | ${TODAY}"
echo " Top picks: $([ "$SKIP_TOP_PICKS" = "1" ] && echo skip || echo on)"
echo " Evaluation: ${EVAL_TYPE}"
echo " Git commit: $([ "$GIT_COMMIT" = "1" ] && echo on || echo off)"
echo "══════════════════════════════════════════"

ST_TOP="skip"
ST_EVAL="fail"

# --- Top picks (IDX + US + Crypto) ---
if [ "$SKIP_TOP_PICKS" != "1" ]; then
  echo ""
  echo "▶ [1/2] Top picks screener..."
  if STRICTNESS="$STRICTNESS" LIMIT="$LIMIT" ./run_top_picks.sh; then
    ST_TOP="OK"
  else
    ST_TOP="cek log"
    echo "⚠️ Top picks gagal — lanjut evaluation" >&2
  fi
else
  echo ""
  echo "▶ [1/2] Top picks — SKIP"
fi

# --- Evaluation scorecard ---
echo ""
echo "▶ [2/2] Evaluation scorecard..."
if ./run_evaluation.sh "$EVAL_TYPE"; then
  ST_EVAL="OK"
else
  echo "❌ Evaluation gagal" >&2
  exit 1
fi

# --- Optional git commit ---
if [ "$GIT_COMMIT" = "1" ]; then
  echo ""
  echo "▶ Git commit & push..."
  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "⚠️ Bukan git repo — skip commit" >&2
  else
    git add \
      reports/top-picks/ \
      reports/idx/ \
      reports/us/ \
      reports/crypto/ \
      reports/evaluation/ 2>/dev/null || true

    if git diff --staged --quiet; then
      echo "ℹ️ Tidak ada perubahan untuk di-commit"
    else
      git commit -m "chore: daily pipeline ${TODAY} (top=${ST_TOP}, eval=${ST_EVAL})"
      if git push; then
        echo "✅ Pushed ke remote"
      else
        echo "⚠️ Push gagal — commit lokal tersimpan" >&2
      fi
    fi
  fi
fi

echo ""
echo "══════════════════════════════════════════"
echo " Selesai | ${TODAY}"
echo " Top picks: ${ST_TOP}"
echo " Evaluation: ${ST_EVAL}"
echo "══════════════════════════════════════════"
