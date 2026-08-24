"""LA ligne de conduite : le programme macro sur 34 semaines.

C'est la structure FIXE que le moteur adaptatif respecte. Chaque semaine
définit une INTENTION par rôle (quality / easy / long / b2b) sous forme de
SessionSpec paramétrable. Le moteur module les paramètres selon le réalisé,
mais ne change ni les rôles ni les types de séance.

Objectif : backyard ultra, 18-24 yards, 4 jours/semaine.
Phases : Fondation → Force-endurance → Spécifique → Pic → Affûtage.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from .models import ROLES, PlannedWeek, SessionSpec
from . import adapt, config, workouts


def S(template: str, **params) -> SessionSpec:
    return SessionSpec(template, params)


# Raccourcis de séances récurrentes
def easy(m):       return S("easy", minutes=m)
def rec(m):        return S("recovery", minutes=m)
def strides(m=35): return S("strides", minutes=m, reps=6)
def long(m):       return S("long", minutes=m)
def b2b(m):        return S("b2b", minutes=m)
def night(m):      return S("night", minutes=m)
def thr(reps, rm, rec_min=3):  return S("threshold", reps=reps, rep_min=rm, rec_min=rec_min)
def hills(reps, sec):          return S("hills", reps=reps, sec=sec)
def resist(reps=4, block=20):  return S("resist", reps=reps, block_min=block)
def runwalk(h):    return S("runwalk", hours=h)
def backyard(n):   return S("backyard", loops=n)


# (index, phase, deload, note, quality, easy, long, b2b)
# long/b2b == None  ->  repos (semaine de course)
_ROWS = [
    # ---- Fondation ----
    (1,  "Fondation", False, "On installe la régularité, allure basse",  easy(60),      strides(),  long(90),  b2b(60)),
    (2,  "Fondation", False, "Le volume monte doucement",                easy(60),      strides(),  long(120), b2b(60)),
    (3,  "Fondation", False, "Intro force en côtes",                      hills(8, 60),  easy(60),   long(120), b2b(90)),
    (4,  "Fondation", True,  "Décharge — on assimile",                    easy(45),      rec(40),    long(90),  b2b(60)),
    (5,  "Fondation", False, "Intro seuil",                              thr(2, 15),    easy(60),   long(150), b2b(90)),
    (6,  "Fondation", False, "Force + endurance",                        hills(10, 90), easy(75),   long(150), b2b(90)),
    (7,  "Fondation", False, "Premier gros week-end",                    thr(3, 10, 2.5), easy(60), long(180), b2b(120)),
    (8,  "Fondation", True,  "Décharge",                                 strides(),     rec(40),    long(120), b2b(60)),

    # ---- Force-endurance ----
    (9,  "Force-endurance", False, "Résistance à la fatigue",            resist(),      easy(60),   long(180), b2b(120)),
    (10, "Force-endurance", False, "Marche-course : gestion ravito",     hills(10, 90), easy(75),   runwalk(3), b2b(90)),
    (11, "Force-endurance", False, "Charge soutenue",                    thr(3, 10, 2.5), easy(75), long(180), b2b(120)),
    (12, "Force-endurance", True,  "Décharge",                           strides(),     rec(40),    long(120), b2b(60)),
    (13, "Force-endurance", False, "Premier 4h en temps de pied",        resist(),      easy(60),   runwalk(4), b2b(120)),
    (14, "Force-endurance", False, "Volume soutenu",                     hills(10, 90), easy(75),   long(180), b2b(120)),
    (15, "Force-endurance", False, "Deuxième 4h",                        thr(3, 10, 2.5), easy(75), runwalk(4), b2b(120)),
    (16, "Force-endurance", True,  "Décharge",                           easy(60),      rec(40),    long(150), b2b(60)),

    # ---- Spécifique ----
    (17, "Spécifique", False, "1re simu backyard (6 boucles)",           resist(),      easy(60),   backyard(6),  b2b(90)),
    (18, "Spécifique", False, "Plus longue sortie continue : 4h",        hills(10, 90), easy(75),   long(240), b2b(120)),
    (19, "Spécifique", False, "Temps de pied + ravito",                  thr(3, 10, 2.5), easy(75), runwalk(4), b2b(120)),
    (20, "Spécifique", True,  "Décharge",                                strides(),     rec(40),    long(150), b2b(60)),
    (21, "Spécifique", False, "2e simu backyard",                        resist(),      easy(60),   backyard(6),  b2b(120)),
    (22, "Spécifique", False, "Le gros morceau : 5h",                    hills(10, 90), easy(75),   long(300), b2b(120)),
    (23, "Spécifique", False, "Course de nuit (jeu.) + long",           thr(3, 10, 2.5), night(120), runwalk(4), b2b(120)),
    (24, "Spécifique", True,  "Décharge",                                easy(60),      rec(40),    long(150), b2b(60)),
    (25, "Spécifique", False, "Répétition majeure : 10 boucles / nuit",  resist(),      easy(60),   backyard(10), b2b(60)),
    (26, "Spécifique", False, "Consolidation",                           hills(10, 90), easy(75),   long(240), b2b(120)),

    # ---- Pic ----
    (27, "Pic", False, "Gros volume",                                    resist(),      easy(75),   long(240), b2b(120)),
    (28, "Pic", True,  "Mini-décharge avant le pic",                     thr(2, 15),    easy(60),   long(180), b2b(90)),
    (29, "Pic", False, "Spécifique boucles",                             hills(10, 90), easy(75),   backyard(6),  b2b(120)),
    (30, "Pic", False, "Plus gros continu : 5h",                         resist(),      easy(75),   long(300), b2b(120)),
    (31, "Pic", False, "RÉPÉTITION GÉNÉRALE (10 boucles, nuit)",         strides(),     easy(45),   backyard(10), b2b(60)),

    # ---- Affûtage ----
    (32, "Affûtage", False, "On réduit le volume, on garde la fraîcheur", thr(2, 15),   easy(45),   long(150), b2b(60)),
    (33, "Affûtage", False, "Affûtage",                                  strides(),     rec(40),    long(90),  b2b(60)),
    (34, "Affûtage", False, "SEMAINE DE COURSE",                         rec(35),       strides(20), None,     None),
]


TEMPLATE_WEEKS = len(_ROWS)
MIN_WEEKS = 4


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


# --------------------------------------------------------------------------- #
# Durée de plan variable : compresse le template de 34 semaines pour tenir dans
# le temps réellement disponible (plan_start→race_date, ou plan_weeks). On garde
# la forme : affûtage intact, chaque phase représentée (min. renforcé pour
# Spécifique/Pic), sélection régulière à l'intérieur de chaque phase.
# --------------------------------------------------------------------------- #
def _allocate(budget, sizes, mins):
    alloc = [min(m, s) for m, s in zip(mins, sizes)]
    total = sum(sizes) or 1
    quotas = [budget * s / total for s in sizes]
    for i in range(len(sizes)):
        alloc[i] = min(sizes[i], max(alloc[i], int(quotas[i])))
    order = sorted(range(len(sizes)), key=lambda i: quotas[i] - int(quotas[i]), reverse=True)
    j = 0
    while sum(alloc) < budget and any(alloc[i] < sizes[i] for i in range(len(sizes))):
        i = order[j % len(order)]
        if alloc[i] < sizes[i]:
            alloc[i] += 1
        j += 1
    while sum(alloc) > budget:  # sécurité : ne dépasse pas le budget
        for i in order[::-1]:
            if alloc[i] > mins[i] and sum(alloc) > budget:
                alloc[i] -= 1
    return alloc


def _even(rows, k):
    n = len(rows)
    if k <= 0:
        return []
    if k >= n:
        return list(rows)
    if k == 1:
        return [rows[-1]]  # garde la semaine "pic" de la phase
    idxs = sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})
    i = 0
    while len(idxs) < k and i < n:
        if i not in idxs:
            idxs.append(i)
        i += 1
    return [rows[i] for i in sorted(idxs)[:k]]


def _select(rows, N):
    if N >= len(rows):
        return list(rows)
    groups = []
    for r in rows:
        if not groups or groups[-1][0] != r[1]:
            groups.append((r[1], [r]))
        else:
            groups[-1][1].append(r)
    *others, taper = groups
    taper_rows = taper[1]
    budget = N - len(taper_rows)
    if budget < len(others):            # trop court : garder les N dernières semaines
        kept = list(rows)[-N:]
    else:
        sizes = [len(g[1]) for g in others]
        mins = [2 if g[0] in ("Spécifique", "Pic") else 1 for g in others]
        alloc = _allocate(budget, sizes, mins)
        kept = []
        for (ph, rws), k in zip(others, alloc):
            kept += _even(rws, k)
        kept += taper_rows
    return [(i,) + tuple(r[1:]) for i, r in enumerate(kept, start=1)]  # ré-indexe 1..N


def _target_weeks() -> int:
    if config.PLAN_WEEKS:
        return max(MIN_WEEKS, min(TEMPLATE_WEEKS, config.PLAN_WEEKS))
    if config.PLAN_START and config.RACE_DATE:
        w = (_monday(config.RACE_DATE) - _monday(config.PLAN_START)).days // 7 + 1
        return max(MIN_WEEKS, min(TEMPLATE_WEEKS, w))
    return TEMPLATE_WEEKS


_ACTIVE_ROWS = _select(_ROWS, _target_weeks())
N_WEEKS = len(_ACTIVE_ROWS)


# --------------------------------------------------------------------------- #
# Paramétrage par le profil athlète (config) → mémoire intersessions
# --------------------------------------------------------------------------- #
# Jours/semaine : à 3 jours on retire le "facile" du jeudi (on garde qualité +
# week-end longue/back-to-back, le plus spécifique). 4+ : les 4 rôles.
def _roles_for_days(days: int) -> List[str]:
    if days <= 3:
        return [r for r in ROLES if r != "easy"]
    return list(ROLES)


DAYS_PER_WEEK = config.DAYS_PER_WEEK
_ACTIVE_ROLES = _roles_for_days(DAYS_PER_WEEK)


def _base_row_sessions(row):
    idx, phase, deload, note, q, e, lg, bb = row
    s: Dict[str, SessionSpec] = {"quality": q, "easy": e}
    if lg is not None:
        s["long"] = lg
    if bb is not None:
        s["b2b"] = bb
    return {r: spec for r, spec in s.items() if r in _ACTIVE_ROLES}


def _base_week1_hours() -> float:
    s = _base_row_sessions(_ACTIVE_ROWS[0])
    return sum(workouts.minutes(spec) for spec in s.values()) / 60.0


# Échelle de volume : cale la charge de la semaine 1 sur le volume de départ réel
# de l'athlète (start_volume_h). Le reste du plan monte proportionnellement.
VOLUME_SCALE = 1.0
if config.START_VOLUME_H:
    base = _base_week1_hours()
    if base > 0:
        VOLUME_SCALE = round(config.START_VOLUME_H / base, 3)


def _build_week(row, scale: float = None, days: int = None) -> PlannedWeek:
    idx, phase, deload, note = row[0], row[1], row[2], row[3]
    roles = _roles_for_days(days) if days is not None else _ACTIVE_ROLES
    sc = VOLUME_SCALE if scale is None else scale
    sessions = {r: spec for r, spec in _base_row_sessions(row).items() if r in roles}
    if sc != 1.0:
        sessions = {r: adapt._scaled_spec(spec, sc) for r, spec in sessions.items()}
    return PlannedWeek(idx, phase, deload, note, sessions)


PROGRAM: List[PlannedWeek] = [_build_week(r) for r in _ACTIVE_ROWS]


# Lundi de la SEMAINE 1 : plan_start explicite, sinon calé pour finir à la course,
# sinon env/défaut.
def _compute_start() -> date:
    if config.PLAN_START:
        return _monday(config.PLAN_START)
    if config.RACE_DATE:
        return _monday(config.RACE_DATE) - timedelta(days=7 * (N_WEEKS - 1))
    d = date(2026, 8, 31)
    env = os.environ.get("PROGRAM_START")
    if env:
        try:
            d = datetime.strptime(env, "%Y-%m-%d").date()
        except ValueError:
            pass
    return _monday(d)


PROGRAM_START = _compute_start()


def week(index: int) -> PlannedWeek:
    """Renvoie la semaine `index` (1-based). Lève IndexError hors bornes."""
    if not (1 <= index <= N_WEEKS):
        raise IndexError(f"Semaine {index} hors programme (1..{N_WEEKS})")
    return PROGRAM[index - 1].copy()


def build_week_scaled(index: int, scale: float, days: int = None) -> PlannedWeek:
    """Semaine reconstruite avec une échelle de volume explicite (tests/simulation)."""
    return _build_week(_ACTIVE_ROWS[index - 1], scale=scale, days=days)


def planned_minutes(w: PlannedWeek) -> float:
    return sum(workouts.minutes(s) for s in w.sessions.values())


def planned_hours(w: PlannedWeek) -> float:
    return planned_minutes(w) / 60.0


# --------------------------------------------------------------------------- #
# Ancrage calendaire
# --------------------------------------------------------------------------- #
def week_start(index: int) -> date:
    """Lundi de la semaine `index` (1-based)."""
    return PROGRAM_START + timedelta(days=7 * (index - 1))


def week_end(index: int) -> date:
    """Dimanche de la semaine `index`."""
    return week_start(index) + timedelta(days=6)


def current_week_index(today: Optional[date] = None) -> int:
    """Numéro de semaine de programme correspondant à `today` (borné 1..N)."""
    today = today or date.today()
    delta = (today - PROGRAM_START).days
    if delta < 0:
        return 1
    return min(N_WEEKS, delta // 7 + 1)


def upcoming_monday(today: Optional[date] = None) -> date:
    """Lundi de la semaine d'entraînement à VENIR (aujourd'hui si déjà lundi).

    Permet une exécution dimanche soir : on cible la semaine qui commence demain,
    et on évalue le réalisé sur la semaine qui vient de se terminer.
    """
    today = today or date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7)


def target_week_index(today: Optional[date] = None) -> int:
    """Semaine de programme à PRESCRIRE lors d'un run (lun. ou dim. soir)."""
    return current_week_index(upcoming_monday(today))


def race_date() -> date:
    """Jour de course = fin de la semaine 34 (samedi = start + 5 j)."""
    return week_start(N_WEEKS) + timedelta(days=5)


def days_to_race(today: Optional[date] = None) -> int:
    today = today or date.today()
    return (race_date() - today).days
