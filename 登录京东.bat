@echo off
rem 双击登录京东：弹出窗口后，用京东 App 扫码并在手机上点「确认登录」即可
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo 正在打开登录窗口（总时长 20 分钟，二维码自动保持有效，可随时扫）……
echo 登录成功后所有窗口会自动关闭。
py -3.10 scripts\login_watchdog.py jd 20
echo.
echo ================================
echo 登录流程结束。若上方显示 DONE，说明登录态已保存，
echo 之后每天 17:00 硬件日报会自动使用，无需再登录（约 1 个月有效）。
echo ================================
pause
