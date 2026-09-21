@echo off
rem Analyse du tapping PsychoPy — double-cliquer, ou déposer des fichiers/dossiers dessus.
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (py -3 analyser_tapping.py %*) || (python analyser_tapping.py %*)
if errorlevel 1 pause
endlocal
