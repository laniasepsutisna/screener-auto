<# 
    Setup Windows Task Scheduler for all 3 screeners
    Run as Administrator: powershell -ExecutionPolicy Bypass -File setup_schedule.ps1
#>

$BaseDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BatFile = Join-Path $BaseDir "run_screener.bat"

if (-not (Test-Path $BatFile)) {
    Write-Host "ERROR: $BatFile not found" -ForegroundColor Red
    exit 1
}

# --- IDX: Senin-Jumat 16:30 WIB ---
$taskName = "Screener-IDX-Daily"
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$BatFile`" idx" -WorkingDirectory $BaseDir
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "16:30"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "IDX Undervalued Screener - Senin-Jumat 16:30 WIB"
Write-Host "✅ $taskName registered (Senin-Jumat 16:30 WIB)" -ForegroundColor Green

# --- Crypto: Setiap hari 06:00 WIB ---
$taskName = "Screener-Crypto-Daily"
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$BatFile`" crypto" -WorkingDirectory $BaseDir
$trigger = New-ScheduledTaskTrigger -Daily -At "06:00"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "Crypto Undervalued Screener - Setiap hari 06:00 WIB"
Write-Host "✅ $taskName registered (Setiap hari 06:00 WIB)" -ForegroundColor Green

# --- US: Senin-Jumat 22:00 WIB ---
$taskName = "Screener-US-Daily"
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$BatFile`" us" -WorkingDirectory $BaseDir
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "22:00"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "US Undervalued Screener - Senin-Jumat 22:00 WIB"
Write-Host "✅ $taskName registered (Senin-Jumat 22:00 WIB)" -ForegroundColor Green

Write-Host ""
Write-Host "=== Semua jadwal terdaftar ===" -ForegroundColor Cyan
Get-ScheduledTask -TaskName "Screener-*" | Format-Table TaskName, State, @{N="NextRun";E={(Get-ScheduledTaskInfo -InputObject $_).NextRunTime}} -AutoSize
