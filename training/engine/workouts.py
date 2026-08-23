"""Templates de séances PARAMÉTRABLES.

Chaque template sait :
  - construire un objet Workout encodable en .FIT  (build)
  - se décrire pour l'humain                        (label)
  - fournir un nom de fichier                        (slug)
  - estimer sa durée en minutes                      (minutes)  <- pour la charge

Le moteur adaptatif (adapt.py) fait varier les `params` (minutes, reps, loops…)
sans changer le `template` : la structure de la séance est préservée.
"""

from __future__ import annotations

import re
from typing import Callable, Dict

from .fit_encoder import (
    Duration,
    Intensity,
    Step,
    Target,
    Workout,
)
from .models import SessionSpec

# --------------------------------------------------------------------------- #
# Allures de référence (min/km). Éditables — recalibrées via Strava.
# --------------------------------------------------------------------------- #
PACES = {
    "recovery": "6:45",
    "easy": "6:15",
    "long": "6:40",
    "yard": "6:30",
    "steady": "5:35",
    "tempo": "5:00",
    "cruise": "4:55",
}


def _pace_seconds(pace: str) -> int:
    m, s = pace.split(":")
    return int(m) * 60 + int(s)


def _mm_s(pace_seconds: int) -> int:
    return round(1_000_000 / pace_seconds)


def speed_range(pace_key: str, slower: int = 20, faster: int = 20):
    base = _pace_seconds(PACES[pace_key])
    return _mm_s(base + slower), _mm_s(base - faster)


def MIN(m: float) -> int:
    return int(round(m * 60 * 1000))


def SEC(s: float) -> int:
    return int(round(s * 1000))


def KM(km: float) -> int:
    return int(round(km * 100000))


# --------------------------------------------------------------------------- #
# Constructeur de séance avec blocs de répétition
# --------------------------------------------------------------------------- #
class Builder:
    def __init__(self, name: str):
        self.w = Workout(name)

    def warmup(self, minutes):
        lo, hi = speed_range("easy", 40, 5)
        self.w.add(Step("Echauffement", Duration.TIME, MIN(minutes),
                        Target.SPEED, 0, lo, hi, Intensity.WARMUP))
        return self

    def cooldown(self, minutes):
        lo, hi = speed_range("recovery", 40, 5)
        self.w.add(Step("Retour au calme", Duration.TIME, MIN(minutes),
                        Target.SPEED, 0, lo, hi, Intensity.COOLDOWN))
        return self

    def run_time(self, minutes, pace, name, slower=20, faster=20,
                 intensity=Intensity.ACTIVE):
        lo, hi = speed_range(pace, slower, faster)
        self.w.add(Step(name, Duration.TIME, MIN(minutes),
                        Target.SPEED, 0, lo, hi, intensity))
        return self

    def run_dist(self, km, pace, name, slower=15, faster=15,
                 intensity=Intensity.ACTIVE):
        lo, hi = speed_range(pace, slower, faster)
        self.w.add(Step(name, Duration.DISTANCE, KM(km),
                        Target.SPEED, 0, lo, hi, intensity))
        return self

    def effort_time(self, seconds, name, intensity=Intensity.ACTIVE):
        self.w.add(Step(name, Duration.TIME, SEC(seconds),
                        Target.OPEN, 0, None, None, intensity))
        return self

    def easy_time(self, minutes, name, intensity=Intensity.ACTIVE):
        self.w.add(Step(name, Duration.TIME, MIN(minutes),
                        Target.OPEN, 0, None, None, intensity))
        return self

    def repeat(self, count, build_fn):
        start = len(self.w.steps)
        build_fn(self)
        self.w.add(Step("", Duration.REPEAT_UNTIL_STEPS_CMPLT, start,
                        Target.OPEN, int(count), None, None, Intensity.ACTIVE))
        return self

    def build(self):
        return self.w


def _slug(text: str) -> str:
    text = (text.replace("é", "e").replace("è", "e").replace("ê", "e")
                .replace("à", "a").replace("â", "a").replace("î", "i")
                .replace("ô", "o").replace("û", "u").replace("ç", "c"))
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return text


# --------------------------------------------------------------------------- #
# Définition d'un template : (build, label, minutes)
# --------------------------------------------------------------------------- #
class Template:
    def __init__(self, name: str,
                 build: Callable[[dict], Workout],
                 label: Callable[[dict], str],
                 minutes: Callable[[dict], float]):
        self.name = name
        self._build = build
        self._label = label
        self._minutes = minutes

    def build(self, params) -> Workout:
        return self._build(params)

    def label(self, params) -> str:
        return self._label(params)

    def minutes(self, params) -> float:
        return self._minutes(params)


# ---- Fabriques ------------------------------------------------------------- #
def _easy(p):
    m = p["minutes"]
    return (Builder(f"Facile {m:.0f}'")
            .run_time(m, "easy", "Endurance", 30, 15).build())


def _recovery(p):
    m = p["minutes"]
    return (Builder(f"Recup {m:.0f}'")
            .run_time(m, "recovery", "Tres facile", 45, 0).build())


def _strides(p):
    m = p["minutes"]
    reps = int(p.get("reps", 6))
    return (Builder(f"Facile {m:.0f}' + {reps} lignes droites")
            .run_time(m, "easy", "Endurance", 30, 15)
            .repeat(reps, lambda b: (
                b.effort_time(20, "Ligne droite vite"),
                b.easy_time(1, "Recup trot", Intensity.RECOVERY)))
            .run_time(5, "recovery", "Retour au calme", 40, 0, Intensity.COOLDOWN)
            .build())


def _long(p):
    m = p["minutes"]
    return (Builder(f"Sortie longue {_hm(m)}")
            .run_time(m, "long", "Effort ultra", 30, 20).build())


def _b2b(p):
    m = p["minutes"]
    return (Builder(f"B2B J2 - {_hm(m)}")
            .run_time(m, "long", "Jambes fatiguees - facile", 40, 15).build())


def _night(p):
    m = p["minutes"]
    return (Builder(f"Sortie nuit {_hm(m)} - frontale + ravito")
            .run_time(m, "long", "Nuit - facile", 40, 20).build())


def _threshold(p):
    reps = int(p["reps"])
    rep_min = p["rep_min"]
    rec = p.get("rec_min", 3)
    return (Builder(f"Seuil {reps}x{rep_min:.0f}'")
            .warmup(15)
            .repeat(reps, lambda b: (
                b.run_time(rep_min, "tempo", "Seuil", 8, 8),
                b.run_time(rec, "recovery", "Recup", 45, 0, Intensity.RECOVERY)))
            .cooldown(10).build())


def _cruise(p):
    reps = int(p["reps"])
    km = p.get("km", 1.0)
    return (Builder(f"Seuil {reps}x{km:g}km")
            .warmup(15)
            .repeat(reps, lambda b: (
                b.run_dist(km, "cruise", f"{km:g} km seuil", 8, 8),
                b.effort_time(90, "Trot recup", Intensity.RECOVERY)))
            .cooldown(10).build())


def _hills(p):
    reps = int(p["reps"])
    sec = p["sec"]
    rec = p.get("rec_sec", sec * 1.5)
    return (Builder(f"Cotes {reps}x{sec:.0f}\"")
            .warmup(15)
            .repeat(reps, lambda b: (
                b.effort_time(sec, "Cote - fort"),
                b.effort_time(rec, "Descente trot", Intensity.RECOVERY)))
            .cooldown(10).build())


def _resist(p):
    reps = int(p["reps"])
    block = p["block_min"]
    return (Builder(f"Resistance fatigue {reps}x{block:.0f}'")
            .warmup(15)
            .repeat(reps, lambda b: (
                b.run_time(block, "steady", "Soutenu", 12, 8),
                b.run_time(3, "easy", "Recup", 30, 0, Intensity.RECOVERY)))
            .cooldown(10).build())


def _runwalk(p):
    hours = p["hours"]
    run_min = p.get("run_min", 25)
    walk_min = p.get("walk_min", 5)
    cycles = max(1, round(hours * 60 / (run_min + walk_min)))
    return (Builder(f"Marche-course {_hm(hours*60)}")
            .repeat(cycles, lambda b: (
                b.run_time(run_min, "long", "Course", 40, 20),
                b.easy_time(walk_min, "Marche + ravito", Intensity.REST)))
            .build())


def _backyard(p):
    loops = int(p["loops"])
    run_min = p.get("run_min", 50)
    rest_min = p.get("rest_min", 10)
    return (Builder(f"Simu Backyard {loops} boucles")
            .repeat(loops, lambda b: (
                b.run_time(run_min, "yard", "Boucle (~6.7km)", 45, 25),
                b.easy_time(rest_min, "Repos + ravito", Intensity.REST)))
            .build())


def _hm(minutes: float) -> str:
    m = int(round(minutes))
    h, mm = divmod(m, 60)
    if h and mm:
        return f"{h}h{mm:02d}"
    if h:
        return f"{h}h00"
    return f"{mm}'"


# ---- Registre + estimateurs de durée -------------------------------------- #
def _m_fixed(p):        # templates dont la durée = minutes
    return p["minutes"]


TEMPLATES: Dict[str, Template] = {
    "easy":      Template("easy", _easy, lambda p: f"Facile {p['minutes']:.0f}'", _m_fixed),
    "recovery":  Template("recovery", _recovery, lambda p: f"Récup {p['minutes']:.0f}'", _m_fixed),
    "strides":   Template("strides", _strides,
                          lambda p: f"Facile {p['minutes']:.0f}' + lignes droites",
                          lambda p: p["minutes"] + 13),
    "long":      Template("long", _long, lambda p: f"Longue {_hm(p['minutes'])}", _m_fixed),
    "b2b":       Template("b2b", _b2b, lambda p: f"B2B {_hm(p['minutes'])}", _m_fixed),
    "night":     Template("night", _night, lambda p: f"Nuit {_hm(p['minutes'])}", _m_fixed),
    "threshold": Template("threshold", _threshold,
                          lambda p: f"Seuil {int(p['reps'])}×{p['rep_min']:.0f}'",
                          lambda p: 25 + p["reps"] * (p["rep_min"] + p.get("rec_min", 3))),
    "cruise":    Template("cruise", _cruise,
                          lambda p: f"Seuil {int(p['reps'])}×{p.get('km',1):g} km",
                          lambda p: 25 + p["reps"] * (p.get("km", 1) * 5 + 1.5)),
    "hills":     Template("hills", _hills,
                          lambda p: f"Côtes {int(p['reps'])}×{p['sec']:.0f}\"",
                          lambda p: 25 + p["reps"] * (p["sec"] + p.get("rec_sec", p["sec"] * 1.5)) / 60),
    "resist":    Template("resist", _resist,
                          lambda p: f"Résistance {int(p['reps'])}×{p['block_min']:.0f}'",
                          lambda p: 25 + p["reps"] * (p["block_min"] + 3)),
    "runwalk":   Template("runwalk", _runwalk,
                          lambda p: f"Marche-course {_hm(p['hours']*60)}",
                          lambda p: p["hours"] * 60),
    "backyard":  Template("backyard", _backyard,
                          lambda p: f"Simu Backyard {int(p['loops'])} boucles",
                          lambda p: p["loops"] * (p.get("run_min", 50) + p.get("rest_min", 10))),
}


def build_workout(spec: SessionSpec) -> Workout:
    return TEMPLATES[spec.template].build(spec.params)


def label(spec: SessionSpec) -> str:
    return TEMPLATES[spec.template].label(spec.params)


def minutes(spec: SessionSpec) -> float:
    return TEMPLATES[spec.template].minutes(spec.params)


def slug(spec: SessionSpec) -> str:
    return _slug(label(spec))
