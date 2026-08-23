"""LA ligne de conduite : le programme macro sur 34 semaines.

C'est la structure FIXE que le moteur adaptatif respecte. Chaque semaine
définit une INTENTION par rôle (quality / easy / long / b2b) sous forme de
SessionSpec paramétrable. Le moteur module les paramètres selon le réalisé,
mais ne change ni les rôles ni les types de séance.

Objectif : backyard ultra, 18-24 yards, 4 jours/semaine.
Phases : Fondation → Force-endurance → Spécifique → Pic → Affûtage.
"""

from __future__ import annotations

from typing import Dict, List

from .models import PlannedWeek, SessionSpec
from . import workouts


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


def _week(row) -> PlannedWeek:
    idx, phase, deload, note, q, e, lg, bb = row
    sessions: Dict[str, SessionSpec] = {"quality": q, "easy": e}
    if lg is not None:
        sessions["long"] = lg
    if bb is not None:
        sessions["b2b"] = bb
    return PlannedWeek(idx, phase, deload, note, sessions)


PROGRAM: List[PlannedWeek] = [_week(r) for r in _ROWS]
N_WEEKS = len(PROGRAM)


def week(index: int) -> PlannedWeek:
    """Renvoie la semaine `index` (1-based). Lève IndexError hors bornes."""
    if not (1 <= index <= N_WEEKS):
        raise IndexError(f"Semaine {index} hors programme (1..{N_WEEKS})")
    return PROGRAM[index - 1].copy()


def planned_minutes(w: PlannedWeek) -> float:
    return sum(workouts.minutes(s) for s in w.sessions.values())


def planned_hours(w: PlannedWeek) -> float:
    return planned_minutes(w) / 60.0
