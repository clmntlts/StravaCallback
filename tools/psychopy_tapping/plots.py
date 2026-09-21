"""Figures de l'analyse du tapping : par essai, par condition, par participant.

Toutes les figures suivent les mêmes règles : une mesure par panneau (jamais
deux axes y), marques fines, grille discrète, couleurs catégorielles fixes
(bleu = données, orange = moyenne / anomalie), identité jamais portée par la
seule couleur (les axes catégoriels et les étiquettes directes la portent).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

PALETTE = {
    "surface": "#fcfcfb",
    "ink": "#0b0b0b",
    "ink_soft": "#52514e",
    "grid": "#dcdcd8",
    "series": "#2a78d6",   # slot 1 — données
    "accent": "#eb6834",   # slot 2 — moyenne / pause
    "muted": "#b9b8b2",
}

MAX_RASTER_ROWS = 40      # essais par page de raster
MAX_ITI_PANELS = 24       # panneaux par page de petits multiples


# ----------------------------------------------------------------- outils ---


def _pyplot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "figure.facecolor": PALETTE["surface"], "axes.facecolor": PALETTE["surface"],
        "savefig.facecolor": PALETTE["surface"], "text.color": PALETTE["ink"],
        "axes.labelcolor": PALETTE["ink_soft"], "xtick.color": PALETTE["ink_soft"],
        "ytick.color": PALETTE["ink_soft"], "axes.edgecolor": PALETTE["grid"],
        "grid.color": PALETTE["grid"], "font.size": 9, "axes.titlesize": 10,
    })
    return plt


def _clean(ax, keep_left: bool = True, axis: str = "both") -> None:
    ax.grid(axis=axis, lw=0.6, alpha=0.7)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    if not keep_left:
        ax.spines["left"].set_visible(False)


def _save(fig, path: Path, written: list[Path]) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    _pyplot().close(fig)
    written.append(path)


def _pages(items, size: int):
    for start in range(0, len(items), size):
        yield start // size + 1, items[start:start + size]


def _slug(value) -> str:
    text = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(value))
    return text.strip("_") or "NA"


def _jitter(n: int, spread: float = 0.09, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).uniform(-spread, spread, n)


def _taps_of(taps: pd.DataFrame, trial_key: str) -> pd.DataFrame:
    return taps[taps["trial_key"] == trial_key]


def _cadence(trials: pd.DataFrame) -> pd.Series:
    """Cadence retenue pour les figures : hors pauses, sinon brute.

    Une pause de 3 s tire la cadence brute vers le bas sans rien dire du rythme
    tenu ; les deux versions restent disponibles dans `trials.csv`.
    """
    return trials["clean_tap_rate_hz"].fillna(trials["tap_rate_hz"])


# --------------------------------------------------------- par participant --


def raster_figures(taps, trials, out_dir: Path, pid: str, written: list[Path]) -> None:
    """Un trait par appui, un rang par essai ; pauses en orange."""
    plt = _pyplot()
    rows = list(trials.itertuples())
    multi = len(rows) > MAX_RASTER_ROWS
    for page, chunk in _pages(rows, MAX_RASTER_ROWS):
        fig, ax = plt.subplots(figsize=(10, 0.28 * len(chunk) + 1.8))
        for y, r in enumerate(chunk):
            sub = _taps_of(taps, r.trial_key)
            ax.vlines(sub["time_s"], y - 0.3, y + 0.3, color=PALETTE["series"], lw=1.4)
            for _, g in sub[sub["is_pause"]].iterrows():
                ax.hlines(y, g["time_s"] - g["iti_s"], g["time_s"],
                          color=PALETTE["accent"], lw=2.4, alpha=0.9)
        ax.set_yticks(range(len(chunk)), [r.trial_label for r in chunk])
        ax.set_ylim(-0.8, len(chunk) - 0.2)
        ax.invert_yaxis()
        ax.set_xlabel("temps depuis le début du tapping (s)")
        ax.set_title(f"Participant {pid} — appuis par essai"
                     f"{f' (page {page})' if multi else ''}\n"
                     "trait bleu : un appui ; segment orange : pause détectée",
                     loc="left")
        _clean(ax, keep_left=False, axis="x")
        suffix = f"_p{page}" if multi else ""
        _save(fig, out_dir / f"essais_{_slug(pid)}_raster{suffix}.png", written)


def iti_series_figures(taps, trials, out_dir: Path, pid: str, written: list[Path]) -> None:
    """Petits multiples : l'ITI au fil de l'essai, un panneau par essai."""
    plt = _pyplot()
    rows = list(trials.itertuples())
    multi = len(rows) > MAX_ITI_PANELS
    for page, chunk in _pages(rows, MAX_ITI_PANELS):
        ncol = min(4, len(chunk))
        nrow = math.ceil(len(chunk) / ncol)
        fig, axes = plt.subplots(nrow, ncol, figsize=(3.3 * ncol, 2.2 * nrow),
                                 squeeze=False)
        for ax, r in zip(axes.ravel(), chunk):
            sub = _taps_of(taps, r.trial_key).dropna(subset=["iti_s"])
            ax.plot(sub["tap_index"], sub["iti_s"] * 1000, color=PALETTE["series"],
                    lw=1.8, marker="o", ms=3.5)
            if not sub.empty:
                ax.axhline(sub["iti_s"].median() * 1000, color=PALETTE["ink_soft"],
                           lw=1, ls="--", alpha=0.6)
            cv = r.clean_iti_cv if not math.isnan(r.clean_iti_cv) else r.iti_cv
            hz = r.clean_tap_rate_hz if not math.isnan(r.clean_tap_rate_hz) else r.tap_rate_hz
            ax.set_title(f"{r.trial_label} — {hz:.2f} Hz · CV {cv:.2f}",
                         loc="left")
            ax.set_xlabel("n° d'appui")
            ax.set_ylabel("ITI (ms)")
            _clean(ax)
        for ax in axes.ravel()[len(chunk):]:
            ax.set_visible(False)
        fig.suptitle(f"Participant {pid} — intervalles entre appuis"
                     f"{f' (page {page})' if multi else ''}", x=0.01, ha="left")
        suffix = f"_p{page}" if multi else ""
        _save(fig, out_dir / f"essais_{_slug(pid)}_iti{suffix}.png", written)


def trial_summary_figure(trials, out_dir: Path, pid: str, written: list[Path]) -> None:
    """Cadence et irrégularité essai par essai, dans l'ordre de passation."""
    plt = _pyplot()
    n = len(trials)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 0.26 * n + 2.4), sharey=True)
    y = np.arange(n)
    rate = _cadence(trials).to_numpy()
    cv = trials["clean_iti_cv"].fillna(trials["iti_cv"]).to_numpy()

    for ax, values, color, label, title in (
        (ax1, rate, PALETTE["series"], "cadence hors pauses (Hz)", "Cadence"),
        (ax2, cv, PALETTE["accent"], "CV des ITI (hors pauses)", "Irrégularité"),
    ):
        ax.hlines(y, 0, values, color=PALETTE["grid"], lw=1.4)
        ax.plot(values, y, "o", color=color, ms=8)
        mean = np.nanmean(values)
        ax.axvline(mean, color=PALETTE["ink_soft"], lw=1, ls="--", alpha=0.7)
        ax.set_xlabel(label)
        ax.set_title(f"{title} — moyenne {mean:.2f}", loc="left")
        _clean(ax, keep_left=False, axis="x")

    ax1.set_yticks(y, trials["trial_label"])
    ax1.invert_yaxis()
    fig.suptitle(f"Participant {pid} — {n} essai(s)", x=0.01, ha="left")
    _save(fig, out_dir / f"essais_{_slug(pid)}_resume.png", written)


# ------------------------------------------------- par condition / groupe ---


def _group_panels(trials, group_col: str, title: str, path: Path,
                  written: list[Path], connect: str | None = None) -> None:
    """Deux panneaux (cadence, irrégularité) par niveau d'une colonne.

    Chaque essai est un point ; la moyenne du niveau est marquée en orange.
    Si `connect` est fourni (p. ex. `participant_id`), les moyennes de chaque
    sujet sont reliées en gris pour montrer l'effet intra-sujet.
    """
    plt = _pyplot()
    levels = [lv for lv in trials[group_col].dropna().unique()]
    levels.sort(key=str)
    if not levels:
        return
    pos = {lv: i for i, lv in enumerate(levels)}
    cv_all = trials["clean_iti_cv"].fillna(trials["iti_cv"])

    fig, axes = plt.subplots(1, 2, figsize=(4.6 + 0.9 * len(levels), 4.4))
    linked = bool(connect) and trials[connect].nunique(dropna=True) > 1
    for ax, values, label, panel_title in (
        (axes[0], _cadence(trials), "cadence hors pauses (Hz)", "Cadence"),
        (axes[1], cv_all, "CV des ITI (hors pauses)", "Irrégularité"),
    ):
        frame = pd.DataFrame({"g": trials[group_col], "v": values,
                              "c": trials[connect] if connect else None})
        frame = frame.dropna(subset=["g", "v"])

        if linked:
            for _, sub in frame.groupby("c", dropna=True):
                means = sub.groupby("g")["v"].mean().reindex(levels).dropna()
                if len(means) > 1:
                    ax.plot([pos[g] for g in means.index], means.to_numpy(),
                            color=PALETTE["muted"], lw=1.2, zorder=1)

        x = np.array([pos[g] for g in frame["g"]], dtype=float)
        ax.plot(x + _jitter(len(x)), frame["v"], "o", color=PALETTE["series"],
                ms=7, alpha=0.75, zorder=2)

        stats = frame.groupby("g")["v"].agg(["mean", "std", "count"]).reindex(levels)
        ax.errorbar([pos[g] for g in levels], stats["mean"], yerr=stats["std"],
                    fmt="D", ms=9, color=PALETTE["accent"], ecolor=PALETTE["accent"],
                    elinewidth=1.6, capsize=4, zorder=3)
        for lv in levels:
            m = stats.loc[lv, "mean"]
            if pd.notna(m):
                ax.annotate(f"{m:.2f}", (pos[lv], m), textcoords="offset points",
                            xytext=(11, 4), color=PALETTE["ink"], fontsize=9)

        ax.set_xticks(range(len(levels)),
                      [f"{lv}\nn={int(stats.loc[lv, 'count'] or 0)}" for lv in levels])
        ax.set_xlim(-0.6, len(levels) - 0.4)
        ax.set_ylabel(label)
        ax.set_title(panel_title, loc="left")
        _clean(ax, axis="y")

    fig.suptitle(f"{title}\npoint bleu : un essai · losange orange : moyenne ± SD"
                 + (" · ligne grise : un participant" if linked else ""),
                 x=0.01, ha="left")
    _save(fig, path, written)


def condition_figures(taps, trials, out_dir: Path, group_col: str,
                      written: list[Path]) -> None:
    """Comparaison entre conditions + distribution des ITI par condition."""
    _group_panels(trials, group_col, f"Cadence et régularité par « {group_col} »",
                  out_dir / f"conditions_{_slug(group_col)}.png", written,
                  connect="participant_id")

    plt = _pyplot()
    merged = taps if group_col in taps.columns else taps.merge(
        trials[["trial_key", group_col]], on="trial_key", how="left")
    merged = merged.dropna(subset=["iti_s", group_col])
    merged = merged[~merged["is_pause"]]
    levels = sorted(merged[group_col].unique(), key=str)
    if not levels:
        return
    ncol = min(3, len(levels))
    nrow = math.ceil(len(levels) / ncol)
    lo, hi = merged["iti_s"].quantile([0.01, 0.99]) * 1000
    bins = np.linspace(max(0, lo * 0.9), hi * 1.1, 30)
    fig, axes = plt.subplots(nrow, ncol, figsize=(3.6 * ncol, 2.6 * nrow),
                             squeeze=False, sharex=True)
    for ax, lv in zip(axes.ravel(), levels):
        vals = merged.loc[merged[group_col] == lv, "iti_s"] * 1000
        ax.hist(vals, bins=bins, color=PALETTE["series"], alpha=0.85)
        ax.axvline(vals.median(), color=PALETTE["accent"], lw=2)
        ax.set_title(f"{lv} — médiane {vals.median():.0f} ms · n={len(vals)}", loc="left")
        ax.set_xlabel("ITI (ms)")
        ax.set_ylabel("appuis")
        _clean(ax)
    for ax in axes.ravel()[len(levels):]:
        ax.set_visible(False)
    fig.suptitle(f"Distribution des ITI par « {group_col} » (pauses exclues)"
                 "\ntrait orange : médiane", x=0.01, ha="left")
    _save(fig, out_dir / f"conditions_{_slug(group_col)}_distribution_iti.png", written)


def participant_figures(trials, out_dir: Path, written: list[Path]) -> None:
    """Vue inter-sujets : un point par essai, une colonne par participant."""
    _group_panels(trials, "participant_id", "Cadence et régularité par participant",
                  out_dir / "participants_resume.png", written)


# ------------------------------------------------------------------ entrée --


def make_all(taps: pd.DataFrame, trials: pd.DataFrame, out_dir: Path,
             group_cols: list[str] | None = None,
             per_trial: bool = True) -> list[Path]:
    """Génère toutes les figures et renvoie les chemins écrits."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if per_trial:
        for pid, sub in trials.groupby("participant_id", dropna=False, sort=True):
            sub = sub.sort_values("source_row").reset_index(drop=True)
            raster_figures(taps, sub, out_dir, str(pid), written)
            iti_series_figures(taps, sub, out_dir, str(pid), written)
            trial_summary_figure(sub, out_dir, str(pid), written)

    for col in group_cols or []:
        if col in trials.columns and trials[col].notna().any() \
                and trials[col].nunique(dropna=True) > 1:
            condition_figures(taps, trials, out_dir, col, written)

    if trials["participant_id"].nunique(dropna=True) > 1:
        participant_figures(trials, out_dir, written)

    return written
