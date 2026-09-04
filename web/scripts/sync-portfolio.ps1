# Sync portfolio-review skill report → screener-auto/reports/portfolio/
# Lalu push main agar Vercel rebuild otomatis.

param(
  [string]$SkillReports = "$env:USERPROFILE\.cursor\skills\portfolio-review\reports",
  [string]$Dest = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not $Dest) {
  $Dest = Join-Path $RepoRoot "reports\portfolio"
}

if (-not (Test-Path (Join-Path $SkillReports "latest.md"))) {
  throw "Tidak ada latest.md di $SkillReports — jalankan portfolio_review.ps1 dulu."
}

New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$today = Get-Date -Format "yyyy-MM-dd"
Copy-Item (Join-Path $SkillReports "latest.md") (Join-Path $Dest "latest.md") -Force
$dated = Join-Path $SkillReports "$today.md"
if (Test-Path $dated) {
  Copy-Item $dated (Join-Path $Dest "$today.md") -Force
} else {
  Copy-Item (Join-Path $Dest "latest.md") (Join-Path $Dest "$today.md") -Force
}

Write-Host "Synced → $Dest"
Write-Host "Commit & push reports/portfolio/ agar web update."
