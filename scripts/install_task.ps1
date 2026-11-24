# Keeps the NVDA watcher running on this PC: starts hidden at every logon, and right now.
#   Install / update:  powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1
#   Remove:            powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 -Remove
#   Logs:              data\watch.log
#
# Why a startup entry and not Task Scheduler: on this machine every Task Scheduler task failed with
# 0xC0000142 (even `cmd /c echo`). A per-user Run entry starts inside your real desktop session,
# which is also what toast pop-ups need.
param([switch]$Remove)

$run = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$name = "NvdaTracker"

function Stop-Watcher {
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -match "nvda_tracker" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
}

Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue  # old, broken
if ($Remove) {
    Remove-ItemProperty -Path $run -Name $name -ErrorAction SilentlyContinue
    Stop-Watcher
    Write-Host "Removed startup entry and stopped the watcher."
    return
}

$root = Split-Path -Parent $PSScriptRoot
$vbs = Join-Path $root "scripts\run_hidden.vbs"
$cmd = "wscript.exe //B //Nologo `"$vbs`""
Set-ItemProperty -Path $run -Name $name -Value $cmd
Stop-Watcher                                   # never leave two watchers (duplicate alerts)
Start-Process wscript.exe -ArgumentList "//B", "//Nologo", "`"$vbs`""
Write-Host "Installed. The watcher is running now and will start at every logon."
