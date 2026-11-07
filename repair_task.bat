@echo off
cd /d "%~dp0"
echo [1/3] Re-register HardwareDaily scheduled task (F: paths) ...
powershell -NoProfile -Command "Register-ScheduledTask -TaskName 'HardwareDaily' -Xml (Get-Content -Raw -Encoding UTF8 '%~dp0task_hardware_daily.xml') -Force"
echo [2/3] Rebuild today's report/charts from existing data ...
py -3.10 scripts\run_daily.py --no-scrape --no-email --no-push
echo [3/3] Done. The task now runs daily at 17:00 from F: paths.
echo If JD/Taobao login has expired, double-click the desktop login icons to re-scan.
pause
