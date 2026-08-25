@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 python -m pip install pyinstaller
if errorlevel 1 goto :error

python -m PyInstaller --clean AutoFTBQ-v2.spec
if errorlevel 1 goto :error

echo.
echo 打包完成：dist\AutoFTBQ-v2.exe
pause
exit /b 0

:error
echo.
echo v2 打包失败，请查看上方信息。
pause
exit /b 1
