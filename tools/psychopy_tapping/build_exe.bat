@echo off
rem Fabrique un exécutable autonome AnalyseTapping.exe dans dist\ (Windows).
setlocal
cd /d "%~dp0"
python -m pip install --upgrade pyinstaller pandas numpy openpyxl matplotlib || goto :fin
python -m PyInstaller --noconfirm --onefile --windowed --name AnalyseTapping ^
  --hidden-import tap_analysis --hidden-import plots ^
  --collect-submodules matplotlib analyser_tapping.py
echo.
echo Executable genere : dist\AnalyseTapping.exe
:fin
pause
endlocal
