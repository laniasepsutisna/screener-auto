# Sync portfolio-review skill report -> screener-auto/reports/portfolio/
# Optional: commit + push main agar Vercel rebuild otomatis.
#
# Contoh:
#   .\sync-portfolio.ps1
#   .\sync-portfolio.ps1 -Push
#   .\sync-portfolio.ps1 -Push -Message "Update portfolio review 2026-09-04"

param(
  [string]$SkillReports = "$env:USERPROFILE\.cursor\skills\portfolio-review\reports",
  [string]$Dest = "",
  [switch]$Push,
  [string]$Message = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $Dest) {
  $Dest = Join-Path $RepoRoot "reports\portfolio"
}

$latestSrc = Join-Path $SkillReports "latest.md"
if (-not (Test-Path $latestSrc)) {
  throw "Tidak ada latest.md di $SkillReports - jalankan portfolio_review.ps1 dulu."
}

New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$today = Get-Date -Format "yyyy-MM-dd"
Copy-Item $latestSrc (Join-Path $Dest "latest.md") -Force

$datedSrc = Join-Path $SkillReports "$today.md"
$datedDest = Join-Path $Dest "$today.md"
if (Test-Path $datedSrc) {
  Copy-Item $datedSrc $datedDest -Force
} else {
  Copy-Item (Join-Path $Dest "latest.md") $datedDest -Force
}

Write-Host "Synced -> $Dest" -ForegroundColor Green

if (-not $Push) {
  Write-Host "Tip: jalankan dengan -Push untuk commit & push ke main (auto-rebuild Vercel)." -ForegroundColor DarkGray
  exit 0
}

Push-Location $RepoRoot
try {
  git add -- "reports/portfolio/latest.md" "reports/portfolio/$today.md"
  $staged = git diff --cached --name-only
  if (-not $staged) {
    Write-Host "Tidak ada perubahan portfolio untuk di-commit." -ForegroundColor Yellow
    exit 0
  }

  if (-not $Message) {
    $Message = "Update portfolio review report $today."
  }

  git commit -m $Message
  git push origin HEAD
  Write-Host "Pushed. Vercel akan rebuild https://screener-auto.vercel.app/" -ForegroundColor Green
}
finally {
  Pop-Location
}
