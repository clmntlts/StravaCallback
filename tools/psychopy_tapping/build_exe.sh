#!/bin/bash
# Fabrique un exécutable autonome dans dist/ (macOS / Linux).
set -e
cd "$(dirname "$0")"
python3 -m pip install --upgrade pyinstaller pandas numpy openpyxl matplotlib
python3 -m PyInstaller --noconfirm --onefile --name AnalyseTapping \
  --hidden-import tap_analysis --hidden-import plots \
  --collect-submodules matplotlib analyser_tapping.py
echo "Exécutable généré : dist/AnalyseTapping"
