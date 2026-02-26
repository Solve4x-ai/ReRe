@echo off
cd /d "%~dp0"
set "PROJECT_ROOT=%CD%"
echo Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (echo pip install failed. & pause & exit /b 1)

echo.
echo Building Python application (PyInstaller)...
python -m PyInstaller --onedir ^
            --noconsole ^
            --uac-admin ^
            --name "ReRe" ^
            --distpath "dist" ^
            --add-data "macros;macros" ^
            --add-data "assets;assets" ^
            --hidden-import=src ^
            --hidden-import=src.config ^
            --hidden-import=src.input_backend ^
            --hidden-import=src.recorder ^
            --hidden-import=src.player ^
            --hidden-import=src.macro_storage ^
            --hidden-import=src.utils ^
            --hidden-import=src.settings_manager ^
            --hidden-import=src.controllers.playback_controller ^
            --hidden-import=PIL ^
            --hidden-import=PIL.Image ^
            --hidden-import=PIL.ImageTk ^
            src/main.py
if errorlevel 1 (echo PyInstaller failed. & pause & exit /b 1)

echo.
if not exist "dist\ReRe\ReRe.exe" (
    echo ERROR: PyInstaller did not produce dist\ReRe\ReRe.exe
    pause
    exit /b 1
)
echo [OK] Application built: %PROJECT_ROOT%\dist\ReRe\ReRe.exe
echo      (Full folder: %PROJECT_ROOT%\dist\ReRe\)

echo.
echo Building professional installer (Inno Setup)...
if not exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    echo WARNING: Inno Setup 6 not found at default path.
    echo Skipping installer. Run the app from: dist\ReRe\ReRe.exe
    echo.
    goto :summary
)
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "installer\setup.iss"
if errorlevel 1 (
    echo Inno Setup failed. Run the app from: dist\ReRe\ReRe.exe
    goto :summary
)

:summary
echo ========================================
echo OUTPUT LOCATIONS:
echo   App (run without installer): %PROJECT_ROOT%\dist\ReRe\ReRe.exe
echo   Installer (if built):       %PROJECT_ROOT%\installer\Output\ReRe_Setup_v1.0.exe
echo ========================================
pause
