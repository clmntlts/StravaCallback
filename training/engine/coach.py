"""Analyse "entraîneur" de la semaine écoulée (+ tendances sur 4 semaines).

Transforme les activités Strava en un debrief utile : un verdict, des constats
CHIFFRÉS, des TENDANCES sur ~4 semaines, et 2-3 recommandations actionnables.
Déterministe (heuristiques d'entraînement d'ultra), donc toujours présent dans
l'email ; le jugement humain peut l'enrichir au runtime.

Angles :
  - volume vs prévu (régularité)          - régularité des allures faciles (CV)
  - poids de la sortie longue             - monotonie d'entraînement (Foster)
  - distribution d'intensité (Z2)         - efficacité aérobie (EF = allure/FC) + tendance
  - dénivelé / spécificité côtes          - tendances volume / longue / fréquence sur 4 sem.
  - espacement / enchaînements            - dynamique de charge (ACWR)
"""

from __future__ import annotations

import statistics as st
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Optional

from .models import Activity, WeekSummary
from .workouts import PACES, _pace_seconds


@dataclass
class CoachAnalysis:
    headline: str
    observations: List[str] = field(default_factory=list)
    trends: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _pace_str(sec_per_km: float) -> str:
    m, s = divmod(int(round(sec_per_km)), 60)
    return f"{m}:{s:02d}/km"


def _pace_s(a: Activity) -> Optional[float]:
    if a.distance_m and a.distance_m > 0 and a.moving_time_s > 0:
        return a.moving_time_s / (a.distance_m / 1000.0)
    return None


def _week_hours(runs: List[Activity]) -> float:
    return sum(a.moving_time_s for a in runs) / 3600.0


def _longest_min(runs: List[Activity]) -> float:
    return max((a.moving_time_s for a in runs), default=0) / 60.0


def _ef(a: Activity) -> Optional[float]:
    """Efficiency Factor : vitesse (m/min) par battement. Plus haut = plus efficace."""
    if a.avg_hr and a.avg_hr > 0 and a.distance_m > 0 and a.moving_time_s > 0:
        speed_m_per_min = a.distance_m / (a.moving_time_s / 60.0)
        return speed_m_per_min / a.avg_hr
    return None


def _week_ef(runs: List[Activity], steady_s: float) -> Optional[float]:
    """EF médian sur les sorties aérobies (allure plus lente que soutenue)."""
    efs = [_ef(a) for a in runs
           if (_pace_s(a) or 0) > steady_s and _ef(a) is not None]
    efs = [e for e in efs if e]
    return st.median(efs) if efs else None


def _monotony(runs: List[Activity], week_start: date) -> Optional[float]:
    """Monotonie de Foster = charge quotidienne moyenne / écart-type (7 jours)."""
    daily = [0.0] * 7
    for a in runs:
        try:
            d = datetime.strptime(a.date, "%Y-%m-%d").date()
        except ValueError:
            continue
        i = (d - week_start).days
        if 0 <= i < 7:
            daily[i] += a.moving_time_s / 60.0
    m = st.mean(daily)
    if m == 0:
        return None
    sd = st.pstdev(daily)
    return m / sd if sd > 0 else 3.0


# --------------------------------------------------------------------------- #
# Analyse
# --------------------------------------------------------------------------- #
def analyze(summary: WeekSummary, week_runs: List[Activity],
            history_runs: Optional[List[List[Activity]]] = None,
            week_start: Optional[date] = None) -> CoachAnalysis:
    obs: List[str] = []
    trends: List[str] = []
    rec: List[str] = []

    if not week_runs:
        if not summary.data_available:
            return CoachAnalysis(
                "Pas de données Strava cette semaine.",
                ["Impossible d'analyser : aucune activité reçue."],
                [], ["Vérifie la synchro Strava pour un debrief la semaine prochaine."])
        return CoachAnalysis(
            "Semaine sans course enregistrée.",
            ["Aucune sortie détectée sur la semaine."],
            [], ["Si c'était du repos voulu, parfait. Sinon vise 3-4 sorties la semaine prochaine."])

    total_s = summary.total_time_s
    total_km = summary.total_dist_m / 1000.0
    n = summary.n_runs
    longest_s = summary.longest_run_s
    long_share = (longest_s / total_s) if total_s else 0
    adh = summary.adherence
    easy_s = _pace_seconds(PACES["easy"])
    steady_s = _pace_seconds(PACES["steady"])

    # --- Volume / régularité --------------------------------------------- #
    if summary.planned_time_s > 0:
        obs.append(f"Volume : {summary.actual_hours:.1f} h sur {n} sorties "
                   f"({total_km:.0f} km), soit {adh:.0%} du prévu.")
    else:
        obs.append(f"Volume : {summary.actual_hours:.1f} h sur {n} sorties ({total_km:.0f} km).")

    # --- Poids de la sortie longue --------------------------------------- #
    if longest_s > 0:
        obs.append(f"Sortie longue : {longest_s/60:.0f} min = {long_share:.0%} du volume.")

    # --- Distribution d'intensité + régularité d'allure ------------------ #
    paces = [(a, _pace_s(a)) for a in week_runs]
    with_pace = [(a, p) for a, p in paces if p]
    fast_share = 0.0
    if with_pace:
        fast_km = sum(a.distance_m / 1000 for a, p in with_pace if p < steady_s)
        fast_share = fast_km / total_km if total_km else 0
        if fast_share > 0.35:
            obs.append(f"Intensité : {fast_share:.0%} du kilométrage plus rapide que "
                       f"l'allure soutenue ({_pace_str(steady_s)}).")
        elif fast_share < 0.08 and n >= 3:
            obs.append("Intensité : semaine quasi entièrement en endurance facile (bon).")
        # régularité des allures faciles
        easy_paces = [p for a, p in with_pace if p > steady_s]
        if len(easy_paces) >= 2:
            cv = st.pstdev(easy_paces) / st.mean(easy_paces)
            if cv > 0.07:
                obs.append(f"Allures faciles irrégulières (variation {cv:.0%}).")
                rec.append("Cale une allure d'endurance stable et confortable : "
                           "la régularité vaut mieux que l'à-coup.")
            else:
                obs.append(f"Allure d'endurance régulière (variation {cv:.0%}).")

    # --- Dénivelé -------------------------------------------------------- #
    elev = summary.total_elev_m
    dplus_per_km = elev / total_km if total_km else 0
    obs.append(f"Dénivelé : {elev:.0f} m D+ ({dplus_per_km:.0f} m/km).")

    # --- Espacement / monotonie ------------------------------------------ #
    dts = sorted({datetime.strptime(a.date, "%Y-%m-%d").date()
                  for a in week_runs if _isdate(a.date)})
    if len(dts) > 1:
        b2b = any((dts[i + 1] - dts[i]).days == 1 for i in range(len(dts) - 1))
        obs.append("Enchaînement sur jours consécutifs — bon pour courir sur jambes "
                   "fatiguées (spécifique backyard)." if b2b
                   else "Sorties bien espacées sur la semaine.")
    mono = _monotony(week_runs, week_start) if week_start else None
    if mono is not None and n >= 3:
        obs.append(f"Monotonie d'entraînement (Foster) : {mono:.1f}.")
        if mono > 2.0:
            rec.append("Monotonie élevée : varie durées et intensités d'un jour à "
                       "l'autre (alterne vrai stimulus et vraie récup).")

    # --- Efficacité aérobie (EF) ----------------------------------------- #
    ef_now = _week_ef(week_runs, steady_s)
    if ef_now is not None:
        obs.append(f"Efficacité aérobie (allure/FC) : {ef_now:.2f} "
                   f"(plus c'est haut, mieux c'est).")

    # --- ACWR ------------------------------------------------------------ #
    if summary.acwr is not None:
        obs.append(f"Charge aiguë/chronique (ACWR) : {summary.acwr:.2f}.")

    # --- TENDANCES sur ~4 semaines --------------------------------------- #
    hist = [w for w in (history_runs or []) if w]
    if len(hist) >= 2:
        hist_h = [_week_hours(w) for w in hist]
        trends.append(_trend_line("Volume hebdo", summary.actual_hours,
                                  st.mean(hist_h), "h"))
        hist_long = [_longest_min(w) for w in hist]
        trends.append(_trend_line("Sortie longue", longest_s / 60,
                                  st.mean(hist_long), "′"))
        hist_n = st.mean(len(w) for w in hist)
        trends.append(f"Fréquence : {n} sorties (moyenne récente {hist_n:.1f}).")
        hist_ef = [e for e in (_week_ef(w, steady_s) for w in hist) if e]
        if ef_now is not None and len(hist_ef) >= 1:
            base = st.mean(hist_ef)
            chg = (ef_now - base) / base if base else 0
            if chg > 0.03:
                trends.append(f"Efficacité aérobie en HAUSSE ({chg:+.0%}) : à FC égale, "
                              f"tu cours plus vite. La forme monte. 💪")
            elif chg < -0.03:
                trends.append(f"Efficacité aérobie en BAISSE ({chg:+.0%}) : fatigue, "
                              f"chaleur ou manque de fraîcheur possibles.")
                rec.append("EF en baisse : privilégie la récup et l'endurance facile "
                           "cette semaine plutôt que l'intensité.")
            else:
                trends.append(f"Efficacité aérobie stable ({chg:+.0%}).")

    # --- Recommandations transverses (priorité) -------------------------- #
    front: List[str] = []
    if summary.acwr is not None and summary.acwr > 1.3:
        front.append("Charge en hausse rapide (ACWR élevé) : semaine à venir plus "
                     "prudente pour éviter la blessure.")
    if fast_share > 0.35:
        front.append("Trop d'allure rapide : l'ultra se construit en endurance facile "
                     "(Z2). Ralentis la majorité de tes sorties.")
    if longest_s > 0 and long_share < 0.28 and n >= 2:
        front.append("Ta sortie longue pèse trop peu : en prépa ultra elle doit dominer "
                     "la semaine (~30-40 %). Allonge-la progressivement.")
    if dplus_per_km < 10 and total_km > 0:
        front.append("Peu de dénivelé : ajoute des côtes ou du D+ sur la longue — "
                     "la backyard use les quadriceps sur la durée.")
    if adh < 0.6:
        front.append("Priorité régularité : reconstruis la fréquence avant le volume.")
    elif adh > 1.2:
        front.append("Tu as dépassé le prévu : soigne sommeil et récup, ne surenchéris pas.")

    rec = (front + rec) or ["Semaine solide — poursuis, en gardant l'endurance facile."]

    return CoachAnalysis(_headline(adh, long_share, fast_share, summary),
                         obs, trends, _dedupe(rec)[:3])


# --------------------------------------------------------------------------- #
def _trend_line(label: str, now: float, base: float, unit: str) -> str:
    if base <= 0:
        return f"{label} : {now:.1f}{unit}."
    chg = (now - base) / base
    arrow = "↗︎ hausse" if chg > 0.08 else ("↘︎ baisse" if chg < -0.08 else "→ stable")
    return f"{label} : {now:.1f}{unit} ({arrow}, moy. récente {base:.1f}{unit})."


def _headline(adh, long_share, fast_share, summary: WeekSummary) -> str:
    if not summary.n_runs:
        return "Semaine sans course."
    if adh < 0.6:
        return "Semaine légère — on repart sur la régularité."
    if summary.acwr is not None and summary.acwr > 1.3:
        return "Bonne charge, mais attention à la fatigue qui monte."
    if fast_share > 0.35:
        return "Bon travail — mais tu cours globalement trop vite pour de l'ultra."
    if long_share and long_share < 0.28:
        return "Bon volume — reste à muscler la sortie longue."
    if 0.85 <= adh <= 1.15:
        return "Semaine conforme et bien construite. On continue."
    return "Semaine au-dessus du prévu — pense récupération."


def _dedupe(items: List[str]) -> List[str]:
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _isdate(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False
