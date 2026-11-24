@echo off
setlocal
if exist "%~dp0.build\translation-runtime\ctranslate2" set "PYTHONPATH=%~dp0.build\translation-runtime;%PYTHONPATH%"
where python.exe >nul 2>nul
if errorlevel 1 (
    echo Python 3 with Tcl/Tk is required.
    pause
    exit /b 1
)
python.exe -c "import PIL, ctranslate2, sentencepiece, win32gui" >nul 2>nul
if errorlevel 1 (
    echo Install the development dependencies with python -m pip install -r "%~dp0requirements.txt".
    pause
    exit /b 1
)
python.exe -B "%~dp0tunnelguard.py" %*
set "tg_exit=%ERRORLEVEL%"
if not "%tg_exit%"=="0" pause
exit /b %tg_exit%
