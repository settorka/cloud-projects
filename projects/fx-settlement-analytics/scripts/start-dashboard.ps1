$ErrorActionPreference='Stop'
$process=Start-Process 'F:\fx\app\.venv\Scripts\python.exe' -ArgumentList @(
 '-m','streamlit','run','F:\fx\app\app.py','--server.address=127.0.0.1','--server.port=8501',
 '--server.headless=true','--browser.gatherUsageStats=false','--server.fileWatcherType=none'
) -WorkingDirectory 'F:\fx\app' -RedirectStandardOutput 'F:\fx\dashboard-logs\stdout.log' -RedirectStandardError 'F:\fx\dashboard-logs\stderr.log' -Wait -PassThru -NoNewWindow
exit $process.ExitCode
