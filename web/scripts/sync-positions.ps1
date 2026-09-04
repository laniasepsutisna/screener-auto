# Sync paper-trade entry snapshots -> positions.json (untuk live price API)
param(
  [switch]$Push,
  [string]$Message = ""
)

$ErrorActionPreference = "Stop"
$Python = "C:\Users\Kimia Farma\.local\bin\python3.14.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Skills = Join-Path $env:USERPROFILE ".cursor\skills"
$env:SCREENER_REPO = $RepoRoot
$env:SCREENER_SKILLS = $Skills

& $Python -c @"
import json, os
from pathlib import Path
from datetime import datetime

skills = Path(os.environ['SCREENER_SKILLS'])
repo = Path(os.environ['SCREENER_REPO'])

idx_dir = skills / 'idx-undervalued-screener' / 'dry-run'
idx_files = sorted(idx_dir.glob('portfolio-*.json'), reverse=True)
if not idx_files:
    raise SystemExit('IDX portfolio JSON tidak ada')
idx = json.loads(idx_files[0].read_text(encoding='utf-8'))
us = json.loads((skills / 'us-undervalued-screener' / 'dry-run' / 'portfolio-latest.json').read_text(encoding='utf-8'))
cry = json.loads((skills / 'crypto-undervalued-screener' / 'dry-run' / 'portfolio-latest.json').read_text(encoding='utf-8'))

out = {
    'synced_at': datetime.now().astimezone().isoformat(timespec='seconds'),
    'mode': 'Paper',
    'books': {
        'idx': {
            'id': 'idx', 'label': 'IDX', 'currency': 'IDR',
            'portfolio_id': idx.get('id'),
            'entry_date': str(idx.get('created_at', ''))[:10],
            'review_at': idx.get('review_at'),
            'capital': float(idx.get('virtual_capital_idr', 100_000_000)),
            'positions': [{
                'symbol': p['symbol'], 'yahoo': f\"{p['symbol']}.JK\",
                'name': p.get('name', p['symbol']),
                'weight_pct': float(p.get('weight_pct', 0)),
                'entry_price': float(p['entry_price']),
                'stop_loss': p.get('stop_loss'), 'take_profit': p.get('take_profit'),
                'quality': p.get('entry_quality', ''), 'thesis': p.get('thesis', ''),
            } for p in idx.get('positions', [])],
        },
        'us': {
            'id': 'us', 'label': 'US', 'currency': 'USD',
            'portfolio_id': us.get('id'),
            'entry_date': str(us.get('created_at', ''))[:10],
            'review_at': us.get('review_at'),
            'capital': float(us.get('virtual_capital_usd', 10000)),
            'cash_pct': float(us.get('cash_pct', 0)),
            'positions': [{
                'symbol': p['symbol'], 'yahoo': p.get('yahoo_symbol') or p['symbol'],
                'name': p.get('name', p['symbol']),
                'weight_pct': float(p.get('weight_pct', 0)),
                'entry_price': float(p['entry_price']),
                'stop_loss': p.get('stop_loss'), 'take_profit': p.get('take_profit'),
                'quality': p.get('entry_quality', ''), 'thesis': p.get('thesis', ''),
            } for p in us.get('positions', [])],
        },
        'crypto': {
            'id': 'crypto', 'label': 'Crypto', 'currency': 'USD',
            'portfolio_id': cry.get('id'),
            'entry_date': str(cry.get('created_at', ''))[:10],
            'review_at': cry.get('review_at'),
            'capital': float(cry.get('virtual_capital_usd', 10000)),
            'cash_pct': float(cry.get('cash_pct', 0)),
            'positions': [{
                'symbol': p['symbol'],
                'coingecko_id': p.get('coin_id') or p.get('coingecko_id'),
                'name': p.get('name', p['symbol']),
                'weight_pct': float(p.get('weight_pct', 0)),
                'entry_price': float(p['entry_price']),
                'stop_loss': p.get('stop_loss'), 'take_profit': p.get('take_profit'),
                'quality': p.get('entry_quality', ''), 'thesis': p.get('thesis', ''),
                'allocation_usd': p.get('allocation_usd'),
            } for p in cry.get('positions', [])],
        },
    },
}

dest1 = repo / 'reports' / 'portfolio' / 'positions.json'
dest2 = repo / 'web' / 'public' / 'data' / 'positions.json'
dest1.parent.mkdir(parents=True, exist_ok=True)
dest2.parent.mkdir(parents=True, exist_ok=True)
text = json.dumps(out, ensure_ascii=False, indent=2)
dest1.write_text(text, encoding='utf-8')
dest2.write_text(text, encoding='utf-8')
print(dest1)
print(dest2)
"@

Write-Host "positions.json synced" -ForegroundColor Green

if (-not $Push) { exit 0 }

Push-Location $RepoRoot
try {
  git add -- "reports/portfolio/positions.json" "web/public/data/positions.json"
  if (-not (git diff --cached --name-only)) {
    Write-Host "Tidak ada perubahan positions." -ForegroundColor Yellow
    exit 0
  }
  if (-not $Message) {
    $Message = "Sync portfolio positions for live prices $(Get-Date -Format yyyy-MM-dd)."
  }
  git commit -m $Message
  git push origin HEAD
  Write-Host "Pushed positions.json" -ForegroundColor Green
}
finally {
  Pop-Location
}
