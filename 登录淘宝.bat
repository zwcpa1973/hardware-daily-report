@echo off
rem 双击登录淘宝：弹出窗口后用淘宝/手机淘宝 App 扫码，或输账号密码
cd /d "W:\codexplaceoffice\其他\硬件日报" 2>nul
if not exist scripts\login_watchdog.py pushd "\\DESKTOP-ULL4GFD\office-D\codexplaceoffice\其他\硬件日报"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title 淘宝登录 - 硬件日报
echo 正在打开登录窗口，总时长 20 分钟，可随时扫码……
echo 登录成功后所有窗口会自动关闭，并显示 DONE。
echo.
py -3.10 scripts\login_watchdog.py taobao 20
echo.
echo ================================
echo 若上方显示 DONE，说明登录态已保存成功，
echo 之后每天 17:00 硬件日报自动抓取淘宝报价。
echo ================================
pause
