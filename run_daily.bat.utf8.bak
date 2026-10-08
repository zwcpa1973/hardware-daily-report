@echo off
rem 硬件日报每日任务入口（计划任务 17:00 调用，使用 Python 3.10）
rem pushd 兼容网络盘/UNC 路径
pushd "%~dp0" || exit /b 1
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist output mkdir output
echo ================================ >> output\daily_log.txt
echo %date% %time% 开始 >> output\daily_log.txt
py -3.10 scripts\run_daily.py >> output\daily_log.txt 2>&1
echo %date% %time% 结束 >> output\daily_log.txt
popd
