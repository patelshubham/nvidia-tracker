# Registers a Windows Scheduled Task that runs the tracker every N minutes.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 [-Minutes 10]
# Remove: Unregister-ScheduledTask -TaskName NvdaTracker -Confirm:$false
param([int]$Minutes = 10)

$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\pythonw.exe"   # pythonw = no console window flashing
$action = New-ScheduledTaskAction -Execute $py -Argument "-m nvda_tracker check" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $Minutes)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName "NvdaTracker" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Alerts on abnormal NVDA volume, price momentum and news" -Force | Out-Null
Write-Host "Registered NvdaTracker: runs every $Minutes minutes."
