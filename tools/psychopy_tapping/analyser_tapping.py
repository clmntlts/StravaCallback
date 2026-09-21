#!/usr/bin/env python3
"""Analyse du tapping PsychoPy — point d'entrée « tout-en-un ».

Trois façons de le lancer :

* **double-clic** (ou `analyser_tapping.bat` / `.command`) : une fenêtre de
  sélection s'ouvre, on choisit les fichiers PsychoPy (ou un dossier) ;
* **glisser-déposer** de fichiers/dossiers sur le lanceur ;
* **ligne de commande** :
  `python3 analyser_tapping.py data/ --out resultats/ --target-iti 0.333`

Il produit, dans un dossier `analyse_tapping_<date>` créé à côté des données :
`tapping_metrics.xlsx` (+ les CSV) et toutes les figures — par essai, par
condition et par participant — puis ouvre le dossier.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

DATA_SUFFIXES = {".xlsx", ".xlsm", ".xls", ".csv"}
GENERATED = {"trials.csv", "taps_long.csv", "summary.csv", "tapping_metrics.xlsx"}
MISSING_DEPS = (
    "Dépendances manquantes : {names}\n"
    "Installer avec :\n    pip install pandas numpy openpyxl matplotlib"
)


# ------------------------------------------------------------ entrées -------


def collect_inputs(paths: list[Path]) -> list[Path]:
    """Développe dossiers et fichiers en une liste de fichiers de données."""
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if (child.is_file() and child.suffix.lower() in DATA_SUFFIXES
                        and child.name not in GENERATED
                        and not child.name.startswith("~$")
                        and "analyse_tapping" not in child.parent.name):
                    found.append(child)
        elif path.is_file():
            found.append(path)
        else:
            print(f"[ignoré] introuvable : {path}")
    # dédoublonnage en gardant l'ordre
    return list(dict.fromkeys(found))


def ask_for_inputs() -> list[Path]:
    """Fenêtre de sélection (fichiers, puis dossier) — sans dépendance externe."""
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
    except ImportError:
        print("Aucun fichier fourni et tkinter n'est pas disponible.\n"
              "Relancer en indiquant les fichiers :\n"
              "    python3 analyser_tapping.py mes_donnees/")
        return []

    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo(
        "Analyse du tapping",
        "Choisissez les fichiers de données PsychoPy (.xlsx ou .csv).\n\n"
        "Annulez pour sélectionner un dossier entier à la place.",
    )
    files = filedialog.askopenfilenames(
        title="Fichiers PsychoPy",
        filetypes=[("Données PsychoPy", "*.xlsx *.xls *.xlsm *.csv"), ("Tous", "*.*")],
    )
    if files:
        root.destroy()
        return [Path(f) for f in files]
    folder = filedialog.askdirectory(title="Dossier contenant les données PsychoPy")
    root.destroy()
    return [Path(folder)] if folder else []


def default_out_dir(inputs: list[Path]) -> Path:
    base = inputs[0].parent if inputs[0].is_file() else inputs[0]
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    return base / f"analyse_tapping_{stamp}"


def open_folder(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606 — ouverture de l'explorateur
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception:  # l'ouverture est un confort, jamais un échec
        pass


def check_deps(need_plots: bool) -> None:
    missing = []
    for name in ("pandas", "numpy"):
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    if need_plots:
        try:
            __import__("matplotlib")
        except ImportError:
            missing.append("matplotlib")
    if missing:
        raise SystemExit(MISSING_DEPS.format(names=", ".join(missing)))


# ------------------------------------------------------------- pipeline -----


def run(inputs: list[Path], out_dir: Path, opts: SimpleNamespace) -> dict:
    import pandas as pd

    import plots
    import tap_analysis as ta

    log: list[str] = []
    all_trials, all_taps = [], []
    for path in inputs:
        try:
            trials, taps = ta.analyse_file(path, opts)
        except SystemExit as exc:            # fichier sans composant souris
            log.append(f"[ignoré] {path.name} : {exc}")
            print(f"[ignoré] {path.name} : {exc}")
            continue
        except Exception as exc:             # fichier illisible / corrompu
            log.append(f"[erreur] {path.name} : {exc}")
            print(f"[erreur] {path.name} : {exc}")
            continue
        if trials.empty:
            log.append(f"[ignoré] {path.name} : aucun essai avec des appuis")
            print(f"[ignoré] {path.name} : aucun essai avec des appuis")
            continue
        log.append(f"[ok] {path.name} : {len(trials)} essai(s), {len(taps)} appui(s)")
        print(f"[ok] {path.name} : {len(trials)} essai(s), {len(taps)} appui(s)")
        all_trials.append(trials)
        all_taps.append(taps)

    if not all_trials:
        raise SystemExit("Aucun tapping trouvé dans les fichiers sélectionnés.")

    trials = pd.concat(all_trials, ignore_index=True)
    taps = pd.concat(all_taps, ignore_index=True)
    trials, taps = ta.add_labels(trials, taps)
    summary = ta.condition_summary(trials, opts.by)

    tables = ta.write_tables(trials, taps, summary, out_dir)
    figures = []
    if not opts.no_plots:
        figures = plots.make_all(taps, trials, out_dir, group_cols=opts.by,
                                 per_trial=not opts.no_trial_plots)

    (out_dir / "journal.txt").write_text(
        "Analyse du tapping PsychoPy — "
        + dt.datetime.now().strftime("%Y-%m-%d %H:%M") + "\n\n"
        + "Fichiers traités\n"
        + "\n".join(log)
        + f"\n\nTotal : {len(trials)} essai(s), {len(taps)} appui(s), "
          f"{trials['participant_id'].nunique()} participant(s)\n\n"
        + "Sorties\n"
        + "\n".join(f"- {p.name}" for p in tables + figures) + "\n",
        encoding="utf-8",
    )
    return {"trials": trials, "taps": taps, "tables": tables, "figures": figures}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Analyse du tapping PsychoPy : métriques et figures.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("inputs", nargs="*", type=Path,
                   help="fichiers .xlsx/.csv ou dossiers (vide = fenêtre de sélection)")
    p.add_argument("--out", type=Path, help="dossier de sortie")
    p.add_argument("--component", help="nom du composant souris (défaut : détecté)")
    p.add_argument("--button", choices=["left", "mid", "right", "any"], default="left")
    p.add_argument("--min-iti", type=float, default=0.05,
                   help="anti-rebond : fusionne les appuis à moins de X s (défaut 0.05)")
    p.add_argument("--pause-factor", type=float, default=2.5,
                   help="ITI > facteur × médiane de l'essai = pause (défaut 2.5)")
    p.add_argument("--target-iti", type=float,
                   help="tempo consigne en s → métriques de synchronisation")
    p.add_argument("--by", nargs="*", default=["Condition", "Type"],
                   help="colonnes de regroupement (défaut : Condition Type)")
    p.add_argument("--keep", nargs="*", default=[],
                   help="colonnes supplémentaires à reporter")
    p.add_argument("--no-plots", action="store_true", help="tables seulement")
    p.add_argument("--no-trial-plots", action="store_true",
                   help="pas de figures par essai (utile au-delà de ~500 essais)")
    p.add_argument("--no-open", action="store_true",
                   help="ne pas ouvrir le dossier de résultats à la fin")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    interactive = not args.inputs

    inputs = collect_inputs(args.inputs) if args.inputs else collect_inputs(ask_for_inputs())
    if not inputs:
        print("Aucun fichier à analyser.")
        return 1

    check_deps(need_plots=not args.no_plots)
    out_dir = args.out or default_out_dir(inputs)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n{len(inputs)} fichier(s) à analyser → {out_dir}\n")

    opts = SimpleNamespace(
        component=args.component, button=args.button, min_iti=args.min_iti,
        pause_factor=args.pause_factor, target_iti=args.target_iti,
        keep=args.keep, by=args.by, no_plots=args.no_plots,
        no_trial_plots=args.no_trial_plots,
    )
    result = run(inputs, out_dir, opts)

    trials = result["trials"]
    print(f"\n{len(trials)} essai(s) · {trials['participant_id'].nunique()} participant(s) · "
          f"{len(result['figures'])} figure(s)")
    print(f"Résultats : {out_dir}")
    if not args.no_open:
        open_folder(out_dir)
    if interactive:
        input("\nTerminé — appuyez sur Entrée pour fermer.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as exc:
        if exc.code not in (0, None) and not sys.argv[1:] and sys.stdin.isatty():
            print(f"\n{exc}")
            input("\nAppuyez sur Entrée pour fermer.")
        raise
