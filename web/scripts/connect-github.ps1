# Connect GitHub → Vercel (auto rebuild)
# Jalankan SETELAH install Vercel GitHub App:
#   https://github.com/apps/vercel/installations/new
# Pilih akun laniasepsutisna, centang repo screener-auto (atau All repos).

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot\..

Write-Host "==> Connecting GitHub repo to Vercel project screener-dashboard ..."
npx --yes vercel git connect https://github.com/laniasepsutisna/screener-auto --yes

Write-Host "==> Ensure Root Directory = web"
npx --yes vercel project update screener-dashboard --root-directory web --yes

Write-Host "==> Done. Push ke main akan rebuild https://screener-auto.vercel.app"
npx --yes vercel project inspect screener-dashboard
