$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$python='C:\Python312\python.exe'
$uv='C:\Python312\Scripts\uv.exe'
if(-not (Test-Path $uv)) {
 & $python -m pip install --disable-pip-version-check 'uv==0.13.5'
 if($LASTEXITCODE -ne 0) {throw 'uv installation failed.'}
}
$env:UV_CACHE_DIR='F:\fx\uv-cache'
$env:UV_PYTHON_DOWNLOADS='never'
& $uv sync --frozen --no-dev --python $python --project 'F:\fx\app'
if($LASTEXITCODE -ne 0) {throw 'Locked dashboard dependency installation failed.'}
New-Item -ItemType Directory -Force -Path 'F:\fx\dashboard-logs' | Out-Null
& icacls 'F:\fx\app' /grant 'NT AUTHORITY\LOCAL SERVICE:(OI)(CI)RX' /T /Q | Out-Null
if($LASTEXITCODE -ne 0) {throw 'Dashboard source read permissions failed.'}
& icacls 'F:\fx\dashboard-logs' /grant 'NT AUTHORITY\LOCAL SERVICE:(OI)(CI)M' /T /Q | Out-Null
if($LASTEXITCODE -ne 0) {throw 'Dashboard log permissions failed.'}
$principal=New-ScheduledTaskPrincipal -UserId 'NT AUTHORITY\LOCAL SERVICE' -LogonType ServiceAccount -RunLevel Limited
# Verify the backend and actual Streamlit app under the limited runtime identity.
$smokeScript=@'
$process=Start-Process 'F:\fx\app\.venv\Scripts\python.exe' -ArgumentList @('-m','scripts.smoke_dashboard') -WorkingDirectory 'F:\fx\app' -RedirectStandardOutput 'F:\fx\dashboard-logs\smoke.stdout.log' -RedirectStandardError 'F:\fx\dashboard-logs\smoke.stderr.log' -Wait -PassThru -NoNewWindow
exit $process.ExitCode
'@
$smokeScript | Set-Content 'F:\fx\app\scripts\run-dashboard-smoke.ps1' -Encoding UTF8
$smokeAction=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File F:\fx\app\scripts\run-dashboard-smoke.ps1' -WorkingDirectory 'F:\fx\app'
Register-ScheduledTask -TaskName 'FxDashboardSmoke' -Action $smokeAction -Principal $principal -Settings (New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5)) -Force | Out-Null
Start-ScheduledTask -TaskName 'FxDashboardSmoke'
$complete=$false
for($i=0;$i -lt 90;$i++) {
 Start-Sleep -Seconds 2
 $task=Get-ScheduledTask -TaskName 'FxDashboardSmoke'
 $info=Get-ScheduledTaskInfo -TaskName 'FxDashboardSmoke'
 if($task.State -ne 'Running' -and $info.LastRunTime.Year -gt 2020) {$complete=$true;break}
}
if(-not $complete -or $info.LastTaskResult -ne 0) {
 Get-Content 'F:\fx\dashboard-logs\smoke.stdout.log' -Tail 10 -ErrorAction SilentlyContinue
 Get-Content 'F:\fx\dashboard-logs\smoke.stderr.log' -Tail 30 -ErrorAction SilentlyContinue
 throw 'Limited-identity dashboard smoke failed.'
}
Get-Content 'F:\fx\dashboard-logs\smoke.stdout.log' -Tail 1
$existing=Get-ScheduledTask -TaskName 'FxDashboard' -ErrorAction SilentlyContinue
if($existing) {Stop-ScheduledTask -TaskName 'FxDashboard'}
$action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File F:\fx\app\scripts\start-dashboard.ps1' -WorkingDirectory 'F:\fx\app'
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
Register-ScheduledTask -TaskName 'FxDashboard' -Action $action -Principal $principal -Trigger (New-ScheduledTaskTrigger -AtStartup) -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName 'FxDashboard'
$healthy=$false
for($i=0;$i -lt 15;$i++) {
 Start-Sleep -Seconds 2
 try {if((Invoke-WebRequest 'http://127.0.0.1:8501/_stcore/health' -UseBasicParsing).Content -eq 'ok') {$healthy=$true;break}} catch {}
}
if(-not $healthy) {Get-Content 'F:\fx\dashboard-logs\stderr.log' -Tail 30;throw 'Streamlit health endpoint unavailable.'}
Write-Output 'PASS: read-only dashboard identity, Streamlit control smoke and loopback health endpoint.'
