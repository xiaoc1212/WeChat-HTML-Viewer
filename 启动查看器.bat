@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PY_CMD="
python --version >nul 2>nul
if not errorlevel 1 (
    set "PY_CMD=python"
    goto :found_py
)

py -3 --version >nul 2>nul
if not errorlevel 1 (
    set "PY_CMD=py -3"
    goto :found_py
)

for /f "delims=" %%I in ('where conda 2^>nul') do (
    for %%D in ("%%~dpI..") do (
        if exist "%%~fD\python.exe" (
            "%%~fD\python.exe" --version >nul 2>nul
            if not errorlevel 1 (
                set "PY_CMD="%%~fD\python.exe""
                goto :found_py
            )
        )
    )
)

for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
    "%USERPROFILE%\anaconda3\python.exe"
    "%USERPROFILE%\miniconda3\python.exe"
    "C:\ProgramData\anaconda3\python.exe"
    "C:\ProgramData\miniconda3\python.exe"
) do (
    if exist %%P (
        set "PY_CMD=%%P"
        goto :found_py
    )
)

:no_py
echo.
echo [错误] 未检测到可用的 Python 3 环境，请先安装 Python 3.9 及以上版本。
echo 下载地址: https://www.python.org/downloads/
echo 提示: 安装时请勾选 "Add Python to PATH"。
echo.
pause
exit /b 1

:found_py
echo ============================================================
echo   WeChat-HTML-Viewer 正在启动...
echo   提示: 也可直接把 WechatExporter 导出文件夹拖到本图标上打开
echo ============================================================
echo.

if "%~1"=="" goto :run_default
if exist "%~1\*" goto :run_dir
%PY_CMD% viewer_server.py %*
goto :check_err

:run_dir
%PY_CMD% viewer_server.py --dir "%~1" %2 %3 %4
goto :check_err

:run_default
%PY_CMD% viewer_server.py

:check_err
if errorlevel 1 (
    echo.
    pause
)
