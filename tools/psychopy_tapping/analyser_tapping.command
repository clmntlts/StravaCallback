#!/bin/bash
# Analyse du tapping PsychoPy — double-cliquer (macOS), ou lancer depuis le terminal.
cd "$(dirname "$0")" || exit 1
python3 analyser_tapping.py "$@"
