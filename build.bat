@echo off
cd /d "%~dp0"
echo Installing dependencies...
pip install -r requirements.txt

set KEY=%RANDOM%%RANDOM%%RANDOM%%RANDOM%

echo Building Python application...
python -m PyInstaller --onedir ^
            --noconsole ^
            --uac-admin ^
            --name "ReRe" ^
            --distpath "dist" ^
            --key=%KEY% ^
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

REM Optional: UPX compress (if UPX in PATH) - uncomment next line
REM for %%f in (dist\%EXENAME%\*.pyd dist\%EXENAME%\_internal\*.pyd) do upx --best "%%f" 2>nul

REM Optional: Nuitka standalone (uncomment to try)
REM nuitka --standalone --onefile --enable-plugin=tk-inter --output-filename=%EXENAME%.exe src/main.py

echo Building professional installer...
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\setup.iss

echo ========================================
echo Build complete! Installer ready in installer\Output\
pause
