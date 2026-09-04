#!/usr/bin/env bash
# Top Picks Today — IDX (Yahoo+QC) + US + Crypto (safe filters)
# Portable for Linux cloud / local. Output: reports/top-picks/
#
# Usage:
#   ./run_top_picks.sh
#   STRICTNESS=strict LIMIT=3 ./run_top_picks.sh
#   SKIP_CRYPTO=1 ./run_top_picks.sh
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

export PYTHONIOENCODING=utf-8
export PYTHONUNBUFFERED=1

STRICTNESS="${STRICTNESS:-balanced}"
LIMIT="${LIMIT:-5}"
SKIP_IDX="${SKIP_IDX:-0}"
SKIP_US="${SKIP_US:-0}"
SKIP_CRYPTO="${SKIP_CRYPTO:-0}"

TODAY="$(date +%Y-%m-%d)"
OUT_DIR="reports/top-picks"
RAW_DIR="${OUT_DIR}/_raw"
TMP_DIR="_tmp/top-picks"

mkdir -p "$OUT_DIR" "$RAW_DIR" "$TMP_DIR" reports/idx reports/us reports/crypto

case "$STRICTNESS" in
  loose)
    MIN_PCT="10"
    MIN_Q_STOCK="Fair"
    MIN_Q_CRYPTO="Bagus"
    CRYPTO_EXTRA=(--safe-only)
    ;;
  strict)
    MIN_PCT="25"
    MIN_Q_STOCK="Best"
    MIN_Q_CRYPTO="Best"
    CRYPTO_EXTRA=(--safe-only --ta-confirm --macro-filter)
    ;;
  *)
    STRICTNESS="balanced"
    MIN_PCT="15"
    MIN_Q_STOCK="Bagus"
    MIN_Q_CRYPTO="Best"
    CRYPTO_EXTRA=(--safe-only --ta-confirm --macro-filter)
    ;;
esac

CRYPTO_GATE="${CRYPTO_EXTRA[*]}"
ST_IDX="skip"; ST_US="skip"; ST_CRYPTO="skip"

# Placeholder bodies so assemble always has files
echo "(skip)" >"${TMP_DIR}/idx.md"
echo "(skip)" >"${TMP_DIR}/us.md"
echo "(skip)" >"${TMP_DIR}/crypto.md"

echo "Top Picks Today | ${TODAY} | Strictness=${STRICTNESS} | Limit=${LIMIT}"

# --- IDX: Yahoo → JSON → QC (Yahoo-only, no idx.co.id) ---
if [ "$SKIP_IDX" != "1" ]; then
  echo "=== IDX top picks + QC ==="
  IDX_JSON="${TMP_DIR}/idx.json"
  IDX_MD="${TMP_DIR}/idx.md"
  if python screeners/idx/scripts/idx_yahoo_screener.py \
      --universe liquid \
      --min-pct "$MIN_PCT" \
      --min-quality "$MIN_Q_STOCK" \
      --limit "$LIMIT" \
      --format json \
      --output "$IDX_JSON" \
      >"${RAW_DIR}/idx-screener.log" 2>&1; then
    if python screeners/idx/scripts/qc_enrichment.py \
        --from-json "$IDX_JSON" \
        --no-idx \
        --print-screener \
        >"$IDX_MD" 2>"${RAW_DIR}/idx-qc.err"; then
      ST_IDX="OK"
      cp "$IDX_MD" "reports/idx/${TODAY}.md"
      cp "$IDX_MD" reports/idx/latest.md
    else
      if python screeners/idx/scripts/idx_yahoo_screener.py \
          --universe liquid \
          --min-pct "$MIN_PCT" \
          --min-quality "$MIN_Q_STOCK" \
          --limit "$LIMIT" \
          --format markdown \
          >"$IDX_MD" 2>>"${RAW_DIR}/idx-screener.log"; then
        ST_IDX="OK (tanpa QC)"
        cp "$IDX_MD" "reports/idx/${TODAY}.md"
        cp "$IDX_MD" reports/idx/latest.md
      else
        ST_IDX="cek log"
        echo "(IDX gagal — lihat ${RAW_DIR}/idx-screener.log)" >"$IDX_MD"
      fi
    fi
  else
    ST_IDX="cek log"
    echo "(IDX gagal — lihat ${RAW_DIR}/idx-screener.log)" >"$IDX_MD"
  fi
  echo "IDX status: $ST_IDX"
fi

# --- US ---
if [ "$SKIP_US" != "1" ]; then
  echo "=== US top picks ==="
  US_MD="${TMP_DIR}/us.md"
  if python screeners/us/scripts/us_undervalued_screener.py \
      --universe liquid \
      --min-pct "$MIN_PCT" \
      --min-quality "$MIN_Q_STOCK" \
      --limit "$LIMIT" \
      --format markdown \
      >"$US_MD" 2>"${RAW_DIR}/us.err"; then
    ST_US="OK"
    cp "$US_MD" "reports/us/${TODAY}.md"
    cp "$US_MD" reports/us/latest.md
  else
    ST_US="cek log"
    echo "(US gagal — lihat ${RAW_DIR}/us.err)" >"$US_MD"
  fi
  echo "US status: $ST_US"
fi

# --- Crypto (safe) ---
if [ "$SKIP_CRYPTO" != "1" ]; then
  echo "=== Crypto top picks (safe) ==="
  CRYPTO_MD="${TMP_DIR}/crypto.md"
  if python screeners/crypto/scripts/crypto_undervalued_screener.py \
      --universe top100 \
      --min-pct "$MIN_PCT" \
      --min-quality "$MIN_Q_CRYPTO" \
      --limit "$LIMIT" \
      --format markdown \
      "${CRYPTO_EXTRA[@]}" \
      >"$CRYPTO_MD" 2>"${RAW_DIR}/crypto.err"; then
    ST_CRYPTO="OK"
    cp "$CRYPTO_MD" "reports/crypto/${TODAY}.md"
    cp "$CRYPTO_MD" reports/crypto/latest.md
  else
    ST_CRYPTO="cek log"
    echo "(Crypto gagal — lihat ${RAW_DIR}/crypto.err)" >"$CRYPTO_MD"
  fi
  echo "Crypto status: $ST_CRYPTO"
fi

python assemble_top_picks.py \
  --today "$TODAY" \
  --strictness "$STRICTNESS" \
  --limit "$LIMIT" \
  --min-pct "$MIN_PCT" \
  --min-q-stock "$MIN_Q_STOCK" \
  --min-q-crypto "$MIN_Q_CRYPTO" \
  --crypto-gate "$CRYPTO_GATE" \
  --st-idx "$ST_IDX" \
  --st-us "$ST_US" \
  --st-crypto "$ST_CRYPTO" \
  --body-idx "${TMP_DIR}/idx.md" \
  --body-us "${TMP_DIR}/us.md" \
  --body-crypto "${TMP_DIR}/crypto.md" \
  --out-dir "$OUT_DIR"

echo ""
echo "Selesai! Top picks tersimpan:"
echo "  ${OUT_DIR}/${TODAY}.md"
echo "  ${OUT_DIR}/latest.md"
echo "  IDX=${ST_IDX}  US=${ST_US}  Crypto=${ST_CRYPTO}"
