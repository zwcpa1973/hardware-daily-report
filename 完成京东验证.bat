@echo off
rem 双击完成京东安全验证：在弹出窗口里拖动滑块即可
cd /d "W:\codexplaceoffice\其他\硬件日报" 2>nul
if not exist scripts\solve_captcha.py pushd "\\DESKTOP-ULL4GFD\office-D\codexplaceoffice\其他\硬件日报"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title 京东验证 - 硬件日报
echo 正在打开验证窗口，请在窗口里拖动滑块完成拼图（15 分钟内有效）……
py -3.10 scripts\solve_captcha.py
echo.
echo 若显示 OK，说明验证完成，硬件日报抓价已恢复。
pause
