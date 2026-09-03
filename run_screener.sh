#!/usr/bin/env bash
# Unified screener runner for Render Cron Jobs
# Usage: ./run_screener.sh <idx|crypto|us|all>
set -euo pipefail

TODAY=$(date +%Y-%m-%d)
SCREENER="${1:-all}"

mkdir -p reports/idx reports/crypto reports/us

run_idx() {
    echo "▶ [$TODAY] Running IDX screener..."
    if [ -n "${STOCKBIT_TOKEN:-}" ]; then
        echo "$STOCKBIT_TOKEN" > ~/.stockbit_token
    fi
    python screeners/idx/scripts/tuntun_undervalued_screener.py \
        --universe "${IDX_UNIVERSE:-IHSG}" --limit "${IDX_LIMIT:-30}" \
        --format markdown --output "reports/idx/${TODAY}.md"
    cp "reports/idx/${TODAY}.md" reports/idx/latest.md
    echo "✅ IDX done → reports/idx/${TODAY}.md"
}

run_crypto() {
    echo "▶ [$TODAY] Running Crypto screener..."
    python screeners/crypto/scripts/crypto_undervalued_screener.py \
        --universe "${CRYPTO_UNIVERSE:-top100}" --limit "${CRYPTO_LIMIT:-20}" \
        --format markdown --output "reports/crypto/${TODAY}.md"
    cp "reports/crypto/${TODAY}.md" reports/crypto/latest.md
    echo "✅ Crypto done → reports/crypto/${TODAY}.md"
}

run_us() {
    echo "▶ [$TODAY] Running US screener..."
    python screeners/us/scripts/us_undervalued_screener.py \
        --universe "${US_UNIVERSE:-liquid}" --limit "${US_LIMIT:-30}" \
        --format markdown --output "reports/us/${TODAY}.md"
    cp "reports/us/${TODAY}.md" reports/us/latest.md
    echo "✅ US done → reports/us/${TODAY}.md"
}

case "$SCREENER" in
    idx)    run_idx ;;
    crypto) run_crypto ;;
    us)     run_us ;;
    all)
        run_idx || echo "⚠️ IDX failed, continuing..."
        run_crypto || echo "⚠️ Crypto failed, continuing..."
        run_us || echo "⚠️ US failed, continuing..."
        ;;
    *)
        echo "❌ Unknown screener: $SCREENER (use: idx, crypto, us, all)"
        exit 1
        ;;
esac

echo "🏁 Done at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
