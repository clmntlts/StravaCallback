"""Génération des rapports & du plan (markdown/JSON), et régénération du HTML."""

from __future__ import annotations

import json
import os
import re
from typing import List

from .adapt import AdaptResult
from .models import ROLE_DAY, ROLES, PlannedWeek, WeekSummary, ordered_roles
from . import program, workouts


def _ordered_roles(week: PlannedWeek):
    return ordered_roles(week.sessions)


# --------------------------------------------------------------------------- #
# Rapport hebdomadaire adaptatif
# --------------------------------------------------------------------------- #
def week_report_md(res: AdaptResult, last: WeekSummary, files: dict, analysis=None) -> str:
    w = res.week
    L = []
    L.append(f"# Semaine {w.index} — {w.phase}{' (décharge)' if w.deload else ''}\n")
    L.append(f"> {w.note}\n")
    L.append(f"**Lecture du coach.** {res.message}\n")

    if analysis is not None:
        L.append(f"\n## Debrief de la semaine passée\n")
        L.append(f"**{analysis.headline}**\n")
        if analysis.observations:
            L.append("\n_Constats :_")
            L.extend(f"- {o}" for o in analysis.observations)
        if getattr(analysis, "trends", None):
            L.append("\n_Tendances (4 sem.) :_")
            L.extend(f"- {t}" for t in analysis.trends)
        if analysis.recommendations:
            L.append("\n_À travailler :_")
            L.extend(f"- {r}" for r in analysis.recommendations)

    L.append("\n## Séances de la semaine\n")
    L.append("| Jour | Rôle | Séance | Durée | Fichier |")
    L.append("|---|---|---|---:|---|")
    for role in _ordered_roles(w):
        spec = w.sessions[role]
        mins = workouts.minutes(spec)
        L.append(f"| {ROLE_DAY[role]} | {role} | {workouts.label(spec)} | "
                 f"{mins/60:.1f} h | `{files.get(role,'')}` |")
    L.append(f"\n**Total semaine : {program.planned_hours(w):.1f} h**\n")

    tips = [(role, workouts.tip(w.sessions[role])) for role in _ordered_roles(w)]
    tips = [(r, t) for r, t in tips if t]
    if tips:
        L.append("\n## Consignes spécifiques\n")
        L.extend(f"- **{r}** — {t}" for r, t in tips)

    # Marge du plan à 4 jours : le cross-training (aérobie sans impact) est LE
    # multiplicateur de volume sûr. Rappelé en phase de construction (hors
    # décharge et hors affûtage, où l'on cherche la fraîcheur, pas le volume).
    if not w.deload and w.phase not in ("Affûtage",):
        L.append("\n## Marge des 4 jours : le cross-training\n")
        L.append("Sur 4 jours de course, ton volume plafonne — ta marge est là. "
                 "Ajoute **2-4 h/sem de vélo/elliptique** (aérobie, **sans impact**) "
                 "sur tes jours off : ça construit la caisse et **compte dans ta "
                 "charge de base** (pas de fausse régression du plan), sans le "
                 "risque blessure d'un 5ᵉ jour de course. Garde les jambes fraîches "
                 "pour le week-end longue/B2B, qui reste prioritaire.")

    if res.adjustments:
        L.append("\n## Ajustements appliqués\n")
        for a in res.adjustments:
            L.append(f"- **{a.role}** : {a.before} → {a.after} — _{a.reason}_")
    else:
        L.append("\n_Aucun ajustement : semaine appliquée telle que prévue._")

    L.append("\n## Semaine précédente (Strava)\n")
    if last.planned_time_s > 0 or last.n_runs > 0:
        L.append(f"- Sorties : **{last.n_runs}**")
        L.append(f"- Temps : **{last.actual_hours:.1f} h** / {last.planned_hours:.1f} h prévues "
                 f"({last.adherence:.0%})")
        L.append(f"- Distance : {last.total_dist_m/1000:.1f} km · D+ : {last.total_elev_m:.0f} m")
        L.append(f"- Plus longue sortie : {last.longest_run_s/60:.0f} min")
        if last.acwr is not None:
            L.append(f"- ACWR : {last.acwr:.2f}")
    else:
        L.append("_Pas de données de semaine précédente (début de programme)._")

    L.append("\n## Charger les séances sur la montre\n")
    L.append("⚠️ Les `.fit` de séance **ne s'importent pas** dans Garmin Connect "
             "(l'upload n'accepte que des *activités* terminées). Deux options :\n"
             "- **Copie USB** : brancher la montre, copier les `.fit` dans "
             "`GARMIN/NEWFILES` → ils apparaissent dans *Mes séances* "
             "(bibliothèque seulement, **pas** à une date).\n"
             "- **Planification à date fixe** (séance du jour) : "
             "`generate.py send --push-connect` (calendrier Garmin Connect) ou "
             "`--push-garmin` (Training API officielle).")
    return "\n".join(L) + "\n"


def week_report_json(res: AdaptResult, last: WeekSummary, files: dict, analysis=None) -> dict:
    w = res.week
    data = {
        "week": w.index,
        "phase": w.phase,
        "deload": w.deload,
        "note": w.note,
        "band": res.band,
        "scale": res.scale,
        "acwr": res.acwr,
        "message": res.message,
        "total_hours": round(program.planned_hours(w), 2),
        "sessions": [
            {
                "role": role, "day": ROLE_DAY[role],
                "template": w.sessions[role].template,
                "params": w.sessions[role].params,
                "label": workouts.label(w.sessions[role]),
                "minutes": round(workouts.minutes(w.sessions[role]), 1),
                "tip": workouts.tip(w.sessions[role]),
                "file": files.get(role),
            }
            for role in _ordered_roles(w)
        ],
        "adjustments": [vars(a) for a in res.adjustments],
        "last_week": {
            "n_runs": last.n_runs,
            "actual_hours": round(last.actual_hours, 2),
            "planned_hours": round(last.planned_hours, 2),
            "adherence": round(last.adherence, 3),
            "distance_km": round(last.total_dist_m / 1000, 1),
            "elevation_m": round(last.total_elev_m, 0),
            "longest_run_min": round(last.longest_run_s / 60, 0),
            "acwr": last.acwr,
        },
    }
    if analysis is not None:
        data["analysis"] = {
            "headline": analysis.headline,
            "observations": analysis.observations,
            "trends": getattr(analysis, "trends", []),
            "recommendations": analysis.recommendations,
        }
    return data


# --------------------------------------------------------------------------- #
# Plan complet (markdown) depuis le programme
# --------------------------------------------------------------------------- #
def plan_md() -> str:
    from . import config
    L = [f"# Plan Backyard Ultra — {program.N_WEEKS} semaines\n"]
    L.append(f"Objectif : **{config.OBJECTIVE}** · {config.DAYS_PER_WEEK} jours/semaine · "
             "Mar. (qualité) · Jeu. (facile) · Sam. (longue) · Dim. (B2B).\n")
    L.append("> Programme macro (la « ligne de conduite »). Chaque semaine est "
             "ensuite **ajustée** au réalisé de la semaine précédente via "
             "`engine/adapt.py`.\n")
    cur = None
    for w in program.PROGRAM:
        if w.phase != cur:
            cur = w.phase
            L.append(f"\n## Phase — {w.phase}\n")
            L.append("| Sem. | Mardi | Jeudi | Samedi | Dimanche | Total |")
            L.append("|---:|---|---|---|---|---:|")
        cells = []
        for role in ROLES:
            spec = w.sessions.get(role)
            cells.append(workouts.label(spec) if spec else "Repos")
        tag = " 🟢" if w.deload else ""
        L.append(f"| {w.index}{tag} | {cells[0]} | {cells[1]} | {cells[2]} | "
                 f"{cells[3]} | {program.planned_hours(w):.1f} h |")
    L.append("\n🟢 = semaine de décharge.\n")
    return "\n".join(L) + "\n"


def plan_data_json() -> list:
    """Données pour l'artifact HTML (une entrée par semaine)."""
    rows = []
    for w in program.PROGRAM:
        s = [workouts.label(w.sessions[r]) if r in w.sessions else "Repos" for r in ROLES]
        rows.append({
            "wk": w.index, "phase": w.phase, "deload": w.deload,
            "note": w.note, "s": s, "h": round(program.planned_hours(w), 1),
        })
    return rows


_MONTHS_FR = ["", "janv.", "févr.", "mars", "avr.", "mai", "juin",
              "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def plan_meta_json() -> dict:
    """En-tête du plan piloté par le profil (objectif, jours, saison) — évite le
    texte codé en dur qui devient faux quand le profil change."""
    from . import config
    start, race = program.PROGRAM_START, program.race_date()
    return {
        "objective": config.OBJECTIVE,
        "days": config.DAYS_PER_WEEK,
        "weeks": program.N_WEEKS,
        "season": f"{_MONTHS_FR[start.month]} → {_MONTHS_FR[race.month]}",
        "onboarded": config.ONBOARDED,
    }


def update_plan_html(path: str) -> None:
    """Réinjecte les données du programme (`const DATA`) et l'en-tête piloté par
    le profil (`const META`) dans le HTML du plan."""
    with open(path, encoding="utf-8") as f:
        html = f.read()
    html = re.sub(r"const DATA = \[.*?\];",
                  "const DATA = " + json.dumps(plan_data_json(), ensure_ascii=False) + ";",
                  html, count=1, flags=re.S)
    html = re.sub(r"const META = \{.*?\};",
                  "const META = " + json.dumps(plan_meta_json(), ensure_ascii=False) + ";",
                  html, count=1, flags=re.S)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
