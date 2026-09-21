#!/usr/bin/env python3
"""Analyse du tapping (clics souris / pédale) enregistré par un composant Mouse PsychoPy.

Entrée  : un ou plusieurs fichiers de données PsychoPy (.xlsx ou .csv), avec un
          composant souris dont l'état est sauvegardé (colonnes `<comp>.time`,
          `<comp>.leftButton`, ...). Chaque ligne = un essai.
Sortie  : - `taps_long.csv`      : un tap par ligne (essai, index, temps, ITI)
          - `trials.csv`         : une ligne par essai, toutes les métriques
          - `summary.csv`        : moyennes par condition (si colonne trouvée)
          - graphiques optionnels (`--plots`)

Métriques par essai
-------------------
Cadence      : n_taps, tap_rate_hz (= 1/ITI moyen), tap_rate_per_min,
               rate_first_half / rate_second_half
Régularité   : iti_sd, iti_cv (SD/moyenne, indice classique de variabilité
               temporelle), rmssd (variabilité locale d'un tap au suivant),
               cv_rmssd, lag1_autocorr, iti_iqr, iti_mad
Dérive       : iti_slope_s_per_tap (régression ITI ~ index), iti_slope_r,
               drift_ratio (ITI 2e moitié / 1re moitié)
Isochronie   : isochrony_sd_s / isochrony_max_dev_s — écart des temps de tap
               à la meilleure droite « métronome » (variabilité globale, par
               opposition à la variabilité locale du RMSSD)
Pauses       : n_pauses, longest_gap_s, paused_time_s, et toutes les métriques
               de régularité recalculées hors pauses (suffixe `_clean`)
Qualité      : n_short_merged (rebonds < --min-iti fusionnés),
               frame_quantized (ITI multiples de la période écran)

Usage
-----
    python3 tap_analysis.py data/*.xlsx --out results/ --plots
    python3 tap_analysis.py data.csv --component foot_tapping --target-iti 0.333

Dépendances : pandas, numpy (+ openpyxl pour .xlsx, matplotlib pour --plots).
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- parsing ---

# Les cellules PsychoPy contiennent p.ex. "[np.float64(0.23), np.float64(0.61)]"
# ou "[1, 1, 1]". On extrait simplement tous les nombres de la chaîne.
_NUM_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def parse_list_cell(cell) -> list[float] | None:
    """Renvoie la liste de nombres contenue dans une cellule PsychoPy, ou None."""
    if cell is None or (isinstance(cell, float) and math.isnan(cell)):
        return None
    if isinstance(cell, (list, tuple, np.ndarray)):
        return [float(v) for v in cell]
    text = str(cell).strip()
    if not text or text.lower() in {"nan", "none", "[]"}:
        return None
    if not text.startswith("["):
        return None
    return [float(m) for m in _NUM_RE.findall(text.replace("np.float64", ""))]


def find_components(columns) -> list[str]:
    """Noms de composants souris présents (base du nom, préfixe de boucle retiré)."""
    comps = []
    for col in columns:
        if col.endswith(".time"):
            base = col[: -len(".time")].split(".")[-1]
            if base not in comps:
                comps.append(base)
    return comps


def columns_for(columns, component: str, field: str) -> list[str]:
    """Toutes les colonnes `<...>.<component>.<field>` (copies de boucle incluses)."""
    suffix = f"{component}.{field}"
    return [c for c in columns if c == suffix or c.endswith("." + suffix)]


def loop_of(column: str, component: str, field: str = "time") -> str:
    """Nom de la boucle porteuse de la colonne ('' si colonne non préfixée)."""
    suffix = f"{component}.{field}"
    return column[: -len(suffix)].rstrip(".") if column.endswith(suffix) else ""


def row_series(row, cols) -> tuple[list[float] | None, str]:
    """Première liste non vide parmi `cols` + la colonne d'origine.

    PsychoPy duplique les colonnes d'un composant : une version nue et une
    version préfixée par la boucle (`Practice.foot_tapping.time`). On préfère
    la version préfixée, qui porte le nom de la boucle.
    """
    for col in sorted(cols, key=lambda c: -c.count(".")):
        values = parse_list_cell(row.get(col))
        if values:
            return values, col
    return None, ""


# ---------------------------------------------------------------- taps -------


def extract_taps(
    row,
    component: str,
    columns,
    button: str = "left",
    min_iti: float = 0.0,
) -> dict:
    """Extrait les temps d'appui d'un essai.

    PsychoPy enregistre soit un échantillon par clic (« on click »), soit un
    échantillon par frame (« every frame »). Dans le second cas les colonnes
    boutons contiennent des 0 : on ne garde alors que les transitions 0 -> 1.
    """
    times, time_col = row_series(row, columns_for(columns, component, "time"))
    if not times:
        return {"times": [], "loop": "", "n_short_merged": 0, "sampling": "none"}

    loop = loop_of(time_col, component)
    order = np.argsort(times)
    times = list(np.asarray(times, dtype=float)[order])

    buttons = None
    if button != "any":
        field = {"left": "leftButton", "mid": "midButton", "right": "rightButton"}[button]
        raw, _ = row_series(row, columns_for(columns, component, field))
        if raw and len(raw) == len(order):
            buttons = np.asarray(raw, dtype=float)[order]

    if buttons is not None and np.any(buttons == 0):
        sampling = "every_frame"
        pressed = buttons > 0
        onsets = pressed & ~np.r_[False, pressed[:-1]]
        times = list(np.asarray(times)[onsets])
    else:
        sampling = "on_click"
        if buttons is not None:
            times = list(np.asarray(times)[buttons > 0])

    # Anti-rebond : fusionne deux appuis séparés de moins de `min_iti`.
    merged = 0
    if min_iti > 0 and times:
        kept = [times[0]]
        for t in times[1:]:
            if t - kept[-1] < min_iti:
                merged += 1
            else:
                kept.append(t)
        times = kept

    return {"times": times, "loop": loop, "n_short_merged": merged, "sampling": sampling}


# ------------------------------------------------------------- métriques ----


def _lin_fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """Pente, ordonnée à l'origine, r de Pearson (nan si indéfini)."""
    if len(x) < 3 or np.ptp(x) == 0 or np.std(y) == 0:
        return float("nan"), float("nan"), float("nan")
    slope, intercept = np.polyfit(x, y, 1)
    r = float(np.corrcoef(x, y)[0, 1])
    return float(slope), float(intercept), r


def _regularity(itis: np.ndarray, prefix: str = "") -> dict:
    """Bloc de métriques de régularité pour une série d'ITI."""
    out = {}
    n = len(itis)
    if n == 0:
        keys = ["iti_mean", "iti_median", "iti_sd", "iti_cv", "iti_iqr", "iti_mad",
                "iti_min", "iti_max", "rmssd", "cv_rmssd", "lag1_autocorr",
                "tap_rate_hz", "tap_rate_per_min"]
        return {prefix + k: float("nan") for k in keys} | {prefix + "n_itis": 0}

    mean = float(np.mean(itis))
    sd = float(np.std(itis, ddof=1)) if n > 1 else float("nan")
    diffs = np.diff(itis)
    rmssd = float(np.sqrt(np.mean(diffs**2))) if len(diffs) else float("nan")

    if n > 2 and np.std(itis) > 0:
        centred = itis - mean
        lag1 = float(np.sum(centred[:-1] * centred[1:]) / np.sum(centred**2))
    else:
        lag1 = float("nan")

    out[prefix + "n_itis"] = n
    out[prefix + "iti_mean"] = mean
    out[prefix + "iti_median"] = float(np.median(itis))
    out[prefix + "iti_sd"] = sd
    out[prefix + "iti_cv"] = sd / mean if mean else float("nan")
    out[prefix + "iti_iqr"] = float(np.percentile(itis, 75) - np.percentile(itis, 25))
    out[prefix + "iti_mad"] = float(np.median(np.abs(itis - np.median(itis))))
    out[prefix + "iti_min"] = float(np.min(itis))
    out[prefix + "iti_max"] = float(np.max(itis))
    out[prefix + "rmssd"] = rmssd
    out[prefix + "cv_rmssd"] = rmssd / mean if mean else float("nan")
    out[prefix + "lag1_autocorr"] = lag1
    out[prefix + "tap_rate_hz"] = 1.0 / mean if mean else float("nan")
    out[prefix + "tap_rate_per_min"] = 60.0 / mean if mean else float("nan")
    return out


def trial_metrics(
    times: list[float],
    pause_factor: float = 2.5,
    target_iti: float | None = None,
    frame_rate: float | None = None,
) -> dict:
    """Toutes les métriques d'un essai à partir de ses temps d'appui."""
    n = len(times)
    m: dict[str, float] = {"n_taps": n}
    if n < 2:
        m.update(_regularity(np.array([])))
        m.update({
            "t_first": times[0] if n else float("nan"),
            "t_last": times[0] if n else float("nan"),
            "tap_window_s": float("nan"),
            "n_pauses": 0, "longest_gap_s": float("nan"), "paused_time_s": 0.0,
            "iti_slope_s_per_tap": float("nan"), "iti_slope_r": float("nan"),
            "drift_ratio": float("nan"),
            "rate_first_half_hz": float("nan"), "rate_second_half_hz": float("nan"),
            "isochrony_sd_s": float("nan"), "isochrony_max_dev_s": float("nan"),
            "fitted_period_s": float("nan"),
        })
        return m

    t = np.asarray(times, dtype=float)
    itis = np.diff(t)

    m["t_first"], m["t_last"] = float(t[0]), float(t[-1])
    m["tap_window_s"] = float(t[-1] - t[0])
    m.update(_regularity(itis))

    # Pauses = ITI anormalement longs (multiple de la médiane de l'essai).
    threshold = pause_factor * float(np.median(itis))
    is_pause = itis > threshold
    m["pause_threshold_s"] = threshold
    m["n_pauses"] = int(is_pause.sum())
    m["longest_gap_s"] = float(itis.max())
    m["paused_time_s"] = float(itis[is_pause].sum()) if is_pause.any() else 0.0

    # Régularité hors pauses : une seule longue interruption suffit à faire
    # exploser le CV, d'où la version nettoyée.
    m.update(_regularity(itis[~is_pause], prefix="clean_"))

    # Dérive de cadence au fil de l'essai (pauses exclues).
    idx = np.arange(len(itis))[~is_pause]
    kept = itis[~is_pause]
    slope, _, r = _lin_fit(idx.astype(float), kept)
    m["iti_slope_s_per_tap"], m["iti_slope_r"] = slope, r

    half = len(kept) // 2
    if half >= 1:
        first, second = kept[:half], kept[half:]
        m["rate_first_half_hz"] = float(1 / np.mean(first))
        m["rate_second_half_hz"] = float(1 / np.mean(second))
        m["drift_ratio"] = float(np.mean(second) / np.mean(first))
    else:
        m["rate_first_half_hz"] = m["rate_second_half_hz"] = m["drift_ratio"] = float("nan")

    # Isochronie : écart à la meilleure droite temps ~ index (variabilité
    # globale, insensible à un ITI moyen « faux » mais régulier).
    order = np.arange(n, dtype=float)
    slope_t, intercept_t, _ = _lin_fit(order, t)
    if not math.isnan(slope_t):
        resid = t - (slope_t * order + intercept_t)
        m["fitted_period_s"] = float(slope_t)
        m["isochrony_sd_s"] = float(np.std(resid, ddof=1))
        m["isochrony_max_dev_s"] = float(np.max(np.abs(resid)))
    else:
        m["fitted_period_s"] = m["isochrony_sd_s"] = m["isochrony_max_dev_s"] = float("nan")

    # Synchronisation à un tempo cible (métronome, consigne) si fourni.
    if target_iti:
        phase = 2 * np.pi * (t % target_iti) / target_iti
        r_vec = np.abs(np.mean(np.exp(1j * phase)))
        m["target_iti_s"] = target_iti
        m["phase_locking_r"] = float(r_vec)             # 0 = aléatoire, 1 = parfait
        m["circular_sd_rad"] = float(np.sqrt(-2 * np.log(r_vec))) if r_vec > 0 else float("nan")
        m["iti_bias_s"] = float(np.mean(itis) - target_iti)  # >0 = trop lent

    # Les temps PsychoPy sont échantillonnés à la frame : les ITI sont
    # quantifiés (plancher de variabilité ~ période écran / sqrt(6)).
    if frame_rate and frame_rate > 0:
        period = 1.0 / frame_rate
        resid = np.abs(itis / period - np.round(itis / period))
        m["frame_quantized"] = bool(np.all(resid < 0.2))
        m["frame_period_s"] = period
    return m


# ---------------------------------------------------------------- I/O -------


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(path, sheet_name=0)
    return pd.read_csv(path)


def guess_frame_rate(df: pd.DataFrame) -> float | None:
    if "frameRate" not in df.columns:
        return None
    values = pd.to_numeric(df["frameRate"], errors="coerce").dropna()
    if values.empty:
        return None
    fr = float(values.iloc[0])
    # Certains exports Excel perdent le séparateur décimal (60 -> 5993960485655321).
    while fr > 480:
        fr /= 10
    return fr if 10 <= fr <= 480 else None


def warn_decimal_loss(df: pd.DataFrame, path: Path) -> None:
    """Alerte si l'export a perdu les séparateurs décimaux (export Excel FR).

    Les temps d'horloge (`.started`, `.stopped`, `.rt`) deviennent alors des
    entiers géants (29.25 -> 2925028760000714). Les listes de taps, stockées en
    texte, ne sont pas touchées : l'analyse reste valide, mais les colonnes de
    timing de PsychoPy sont inexploitables telles quelles.
    """
    suspects = []
    for col in df.columns:
        if not re.search(r"\.(started|stopped|rt|duration)$", col) and col != "frameRate":
            continue
        values = pd.to_numeric(df[col], errors="coerce").dropna().abs()
        if not values.empty and values.max() > 1e6:
            suspects.append(col)
    if suspects:
        print(
            f"[attention] {path.name} : {len(suspects)} colonnes de timing semblent avoir "
            f"perdu leur séparateur décimal (p. ex. {suspects[0]}). Les temps de taps ne "
            f"sont pas affectés ; pour exploiter les onsets, repartir du .csv PsychoPy.",
            file=sys.stderr,
        )


DEFAULT_KEEP = [
    "participant", "session", "date", "expName", "psychopyVersion",
    "Stimuli", "Location", "Condition", "CorrAns", "Type", "notes",
]


def keep_columns(df: pd.DataFrame, extra: list[str]) -> list[str]:
    cols = [c for c in DEFAULT_KEEP + list(extra) if c in df.columns]
    cols += [c for c in df.columns
             if re.search(r"\.this(N|TrialN|RepN|Index)$", c) and c not in cols]
    return cols


def analyse_file(path: Path, args) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = read_table(path)
    comps = find_components(df.columns)
    if args.component:
        if args.component not in comps:
            raise SystemExit(
                f"{path.name} : composant '{args.component}' absent "
                f"(candidats : {', '.join(comps) or 'aucun'})"
            )
        component = args.component
    elif len(comps) == 1:
        component = comps[0]
    elif comps:
        component = comps[0]
        print(f"[info] {path.name} : plusieurs composants {comps}, analyse de '{component}' "
              f"(voir --component)", file=sys.stderr)
    else:
        raise SystemExit(f"{path.name} : aucune colonne '<composant>.time' trouvée")

    frame_rate = guess_frame_rate(df)
    warn_decimal_loss(df, path)
    keep = keep_columns(df, args.keep)
    trial_rows, tap_rows = [], []

    for i, row in df.iterrows():
        taps = extract_taps(row, component, df.columns, button=args.button,
                            min_iti=args.min_iti)
        if not taps["times"]:
            continue
        meta = {
            "file": path.name,
            "source_row": int(i) + 2,  # +2 = ligne du tableur (en-tête inclus)
            "loop": taps["loop"],
            "component": component,
        }
        meta.update({c: row.get(c) for c in keep})
        metrics = trial_metrics(
            taps["times"], pause_factor=args.pause_factor,
            target_iti=args.target_iti, frame_rate=frame_rate,
        )
        metrics["n_short_merged"] = taps["n_short_merged"]
        metrics["sampling"] = taps["sampling"]
        trial_rows.append(meta | metrics)

        t = np.asarray(taps["times"], dtype=float)
        itis = np.r_[np.nan, np.diff(t)]
        median_iti = float(np.median(np.diff(t))) if len(t) > 1 else float("nan")
        for k, (time, iti) in enumerate(zip(t, itis)):
            tap_rows.append(meta | {
                "tap_index": k,
                "time_s": float(time),
                "iti_s": float(iti) if not math.isnan(iti) else None,
                "is_pause": bool(iti > args.pause_factor * median_iti) if iti == iti else False,
            })

    return pd.DataFrame(trial_rows), pd.DataFrame(tap_rows)


def condition_summary(trials: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    by = [c for c in by if c in trials.columns and trials[c].notna().any()]
    if not by:
        return pd.DataFrame()
    metrics = ["n_taps", "tap_rate_hz", "iti_mean", "iti_cv", "rmssd", "cv_rmssd",
               "clean_iti_cv", "clean_rmssd", "isochrony_sd_s", "n_pauses"]
    metrics = [m for m in metrics if m in trials.columns]
    out = trials.groupby(by, dropna=False)[metrics].agg(["mean", "std", "count"])
    out.columns = ["_".join(c) for c in out.columns]
    return out.reset_index()


# ------------------------------------------------------- étiquettes / export -


def add_labels(trials: pd.DataFrame, taps: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Ajoute `participant_id`, `trial_key` et `trial_label` aux deux tables.

    `trial_key` identifie un essai de façon unique (fichier + ligne source) et
    sert de clé de jointure entre la table par essai et la table par appui.
    """
    for frame in (trials, taps):
        if "participant" in frame.columns:
            pid = frame["participant"].astype("string")
            pid = pid.str.replace(r"\.0$", "", regex=True)
        else:
            pid = pd.Series(pd.NA, index=frame.index, dtype="string")
        stem = frame["file"].astype("string").str.replace(r"\.[^.]+$", "", regex=True)
        frame["participant_id"] = pid.fillna(stem)
        frame["trial_key"] = frame["file"].astype(str) + "#" + frame["source_row"].astype(str)

    trials = trials.sort_values(["participant_id", "file", "source_row"]).reset_index(drop=True)
    trials["trial_no"] = trials.groupby("participant_id").cumcount() + 1
    cond = trials["Condition"] if "Condition" in trials.columns else None
    trials["trial_label"] = [
        f"E{no:02d}" + (f" · {c}" if cond is not None and pd.notna(c) else "")
        for no, c in zip(trials["trial_no"], cond if cond is not None else trials["trial_no"])
    ]
    taps = taps.merge(trials[["trial_key", "trial_no", "trial_label"]], on="trial_key",
                      how="left")
    return trials, taps


def write_tables(trials: pd.DataFrame, taps: pd.DataFrame, summary: pd.DataFrame,
                 out_dir: Path) -> list[Path]:
    """Écrit les tables (CSV + classeur Excel) et renvoie les chemins écrits."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    trials.to_csv(out_dir / "trials.csv", index=False)
    taps.to_csv(out_dir / "taps_long.csv", index=False)
    written += [out_dir / "trials.csv", out_dir / "taps_long.csv"]
    if not summary.empty:
        summary.to_csv(out_dir / "summary.csv", index=False)
        written.append(out_dir / "summary.csv")
    try:
        with pd.ExcelWriter(out_dir / "tapping_metrics.xlsx") as xw:
            trials.to_excel(xw, sheet_name="trials", index=False)
            taps.to_excel(xw, sheet_name="taps", index=False)
            if not summary.empty:
                summary.to_excel(xw, sheet_name="summary", index=False)
        written.append(out_dir / "tapping_metrics.xlsx")
    except ModuleNotFoundError:
        print("[info] openpyxl absent : export .xlsx ignoré", file=sys.stderr)
    return written


# ---------------------------------------------------------------- main ------


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="+", type=Path, help="fichiers PsychoPy .xlsx / .csv")
    p.add_argument("--out", type=Path, default=Path("tapping_results"),
                   help="dossier de sortie (défaut : tapping_results/)")
    p.add_argument("--component", help="nom du composant souris (défaut : détecté)")
    p.add_argument("--button", choices=["left", "mid", "right", "any"], default="left",
                   help="bouton considéré comme un tap (défaut : left)")
    p.add_argument("--min-iti", type=float, default=0.05,
                   help="fusionne les appuis séparés de moins de X s (anti-rebond, défaut 0.05)")
    p.add_argument("--pause-factor", type=float, default=2.5,
                   help="un ITI > facteur × médiane de l'essai est une pause (défaut 2.5)")
    p.add_argument("--target-iti", type=float,
                   help="tempo consigne en s : ajoute les métriques de synchronisation")
    p.add_argument("--keep", nargs="*", default=[],
                   help="colonnes supplémentaires à reporter dans les sorties")
    p.add_argument("--by", nargs="*", default=["Condition", "Type"],
                   help="colonnes d'agrégation du résumé (défaut : Condition Type)")
    p.add_argument("--plots", action="store_true", help="génère les figures PNG")
    args = p.parse_args(argv)

    all_trials, all_taps = [], []
    for path in args.files:
        if not path.exists():
            raise SystemExit(f"fichier introuvable : {path}")
        trials, taps = analyse_file(path, args)
        if trials.empty:
            print(f"[info] {path.name} : aucun essai avec des taps", file=sys.stderr)
            continue
        all_trials.append(trials)
        all_taps.append(taps)

    if not all_trials:
        raise SystemExit("aucun tap trouvé dans les fichiers fournis")

    trials = pd.concat(all_trials, ignore_index=True)
    taps = pd.concat(all_taps, ignore_index=True)
    trials, taps = add_labels(trials, taps)
    summary = condition_summary(trials, args.by)
    write_tables(trials, taps, summary, args.out)

    if args.plots:
        import plots
        for path in plots.make_all(taps, trials, args.out, group_cols=args.by):
            print(f"figure : {path}")

    cols = ["participant_id", "trial_label", "n_taps", "tap_rate_hz", "iti_mean",
            "iti_cv", "clean_iti_cv", "rmssd", "n_pauses", "isochrony_sd_s"]
    cols = [c for c in cols if c in trials.columns]
    print(f"\n{len(trials)} essai(s), {len(taps)} tap(s) — sorties dans {args.out}/\n")
    print(trials[cols].to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
