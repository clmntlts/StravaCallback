"""Analyse "entraîneur" de la semaine écoulée.

Transforme les activités Strava de la semaine terminée en un debrief utile :
un verdict, des observations CHIFFRÉES, et 2-3 recommandations actionnables pour
la semaine à venir. Déterministe (heuristiques d'entraînement d'ultra), donc
toujours présent dans l'email ; le jugement humain peut l'enrichir au runtime.

Angles couverts :
  - volume réalisé vs prévu (régularité)
  - poids de la sortie longue dans le volume (spécifique endurance)
  - distribution d'intensité (endurance facile Z2 vs allure rapide)
  - dénivelé / spécificité côtes
  - espacement des sorties / récupération (enchaînements)
  - dynamique de charge (ACWR)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List

from .models import Activity, WeekSummary
from .workouts import PACES, _pace_seconds


@dataclass
class CoachAnalysis:
    headline: str
    observations: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


def _pace_str(sec_per_km: float) -> str:
    m, s = divmod(int(round(sec_per_km)), 60)
    return f"{m}:{s:02d}/km"


def _run_pace_s(a: Activity):
    if a.distance_m and a.distance_m > 0 and a.moving_time_s > 0:
        return a.moving_time_s / (a.distance_m / 1000.0)
    return None


def analyze(summary: WeekSummary, week_runs: List[Activity]) -> CoachAnalysis:
    obs: List[str] = []
    rec: List[str] = []

    if not week_runs:
        if not summary.data_available:
            return CoachAnalysis(
                "Pas de données Strava cette semaine.",
                ["Impossible d'analyser : aucune activité reçue."],
                ["Vérifie la synchro Strava pour un debrief la semaine prochaine."])
        return CoachAnalysis(
            "Semaine sans course enregistrée.",
            ["Aucune sortie détectée sur la semaine."],
            ["Si c'était du repos voulu, parfait. Sinon, vise 3-4 sorties la semaine prochaine."])

    total_s = summary.total_time_s
    total_km = summary.total_dist_m / 1000.0
    n = summary.n_runs
    longest_s = summary.longest_run_s
    long_share = (longest_s / total_s) if total_s else 0
    adh = summary.adherence

    # allures de référence
    easy_s = _pace_seconds(PACES["easy"])
    steady_s = _pace_seconds(PACES["steady"])

    # --- Volume / régularité --------------------------------------------- #
    if summary.planned_time_s > 0:
        obs.append(f"Volume : {summary.actual_hours:.1f} h sur {n} sorties "
                   f"({total_km:.0f} km), soit {adh:.0%} du prévu.")
    else:
        obs.append(f"Volume : {summary.actual_hours:.1f} h sur {n} sorties ({total_km:.0f} km).")
    if adh < 0.6:
        rec.append("Priorité régularité : reconstruis la fréquence avant le volume, "
                   "sans chercher à rattraper d'un coup.")
    elif adh > 1.2:
        rec.append("Tu as dépassé le prévu : soigne le sommeil et la récup, "
                   "ne surenchéris pas la semaine prochaine.")

    # --- Poids de la sortie longue --------------------------------------- #
    if longest_s > 0:
        obs.append(f"Sortie longue : {longest_s/60:.0f} min "
                   f"= {long_share:.0%} du volume de la semaine.")
        if long_share < 0.28 and n >= 2:
            rec.append("Ta sortie longue pèse trop peu : en prépa ultra elle doit "
                       "dominer la semaine (~30-40 %). Allonge-la progressivement.")
        elif long_share > 0.55:
            rec.append("Volume très concentré sur une seule sortie : étoffe le reste "
                       "de la semaine pour mieux encaisser.")

    # --- Distribution d'intensité (Z2 vs rapide) ------------------------- #
    paces = [(a, _run_pace_s(a)) for a in week_runs]
    with_pace = [(a, p) for a, p in paces if p]
    if with_pace:
        fast_km = sum(a.distance_m / 1000 for a, p in with_pace if p < steady_s)
        fast_share = fast_km / total_km if total_km else 0
        slow_km = sum(a.distance_m / 1000 for a, p in with_pace if p > easy_s + 25)
        if fast_share > 0.35:
            obs.append(f"Intensité : {fast_share:.0%} du kilométrage plus rapide "
                       f"que l'allure soutenue ({_pace_str(steady_s)}).")
            rec.append("Trop d'allure rapide : l'ultra se construit en endurance "
                       "facile (Z2). Ralentis la majorité de tes sorties.")
        elif fast_share < 0.08 and n >= 3:
            obs.append("Intensité : semaine quasi entièrement en endurance facile.")
        # cohérence de l'allure facile
        if slow_km > 0 and fast_share < 0.3:
            obs.append("Endurance bien tenue en aisance — c'est la bonne base.")

    # --- Dénivelé / spécificité côtes ------------------------------------ #
    elev = summary.total_elev_m
    dplus_per_km = elev / total_km if total_km else 0
    obs.append(f"Dénivelé : {elev:.0f} m D+ ({dplus_per_km:.0f} m/km).")
    if dplus_per_km < 10:
        rec.append("Peu de dénivelé : ajoute des côtes ou du D+ sur la longue — "
                   "la backyard use les quadriceps sur la durée.")

    # --- Espacement / récupération --------------------------------------- #
    days = sorted({a.date for a in week_runs})
    dts = [datetime.strptime(d, "%Y-%m-%d").date() for d in days if _isdate(d)]
    b2b = any((dts[i + 1] - dts[i]).days == 1 for i in range(len(dts) - 1)) if len(dts) > 1 else False
    if len(dts) >= 2:
        if b2b:
            obs.append("Enchaînement de sorties sur jours consécutifs — bon pour "
                       "l'habitude de courir sur jambes fatiguées (spécifique backyard).")
        else:
            obs.append("Sorties bien espacées sur la semaine.")

    # --- Dynamique de charge (ACWR) -------------------------------------- #
    if summary.acwr is not None:
        obs.append(f"Charge aiguë/chronique (ACWR) : {summary.acwr:.2f}.")
        if summary.acwr > 1.3:
            rec.append("Charge en hausse rapide (ACWR élevé) : semaine à venir plus "
                       "prudente pour éviter la blessure.")
        elif summary.acwr < 0.8:
            rec.append("Charge chroniquement basse : il y a de la marge pour "
                       "progresser en douceur.")

    if not rec:
        rec.append("Semaine solide — poursuis sur cette lancée, en gardant l'endurance facile.")

    return CoachAnalysis(_headline(adh, long_share, summary), obs, rec[:3])


def _headline(adh: float, long_share: float, summary: WeekSummary) -> str:
    if not summary.n_runs:
        return "Semaine sans course."
    if adh < 0.6:
        return "Semaine légère — on repart sur la régularité."
    if summary.acwr is not None and summary.acwr > 1.3:
        return "Bonne charge, mais attention à la fatigue qui monte."
    if long_share and long_share < 0.28:
        return "Bon volume — reste à muscler la sortie longue."
    if 0.85 <= adh <= 1.15:
        return "Semaine conforme et bien construite. On continue."
    return "Semaine au-dessus du prévu — pense récupération."


def _isdate(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False
