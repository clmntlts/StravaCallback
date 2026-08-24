"""Profil athlète = mémoire intersessions du moteur.

Charge `training/athlete.json` (committé dans le repo → lu par TOUTE session,
y compris la Routine hebdomadaire éphémère). Fournit les paramètres qui pilotent
le plan : objectif, date de course, jours/semaine, volume, allures.

Précédence : variables d'environnement > athlete.json > défauts.
Aucun import du moteur ici (uniquement des données) pour éviter les cycles.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Dict, Optional

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # training/
CONFIG_PATH = os.environ.get("ATHLETE_CONFIG", os.path.join(_HERE, "athlete.json"))

_DEFAULTS = {
    "objective": "18-24 yards",
    "race_date": None,
    "plan_start": None,
    "plan_weeks": None,
    "days_per_week": 4,
    "start_volume_h": None,
    "peak_volume_h": None,
    "paces": {},
}


def _load() -> Dict:
    data = dict(_DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        for k in _DEFAULTS:
            if k in raw and raw[k] is not None:
                data[k] = raw[k]
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    # overrides env
    for env_key, cfg_key in (("RACE_DATE", "race_date"),
                             ("PLAN_START", "plan_start"),
                             ("PLAN_WEEKS", "plan_weeks"),
                             ("DAYS_PER_WEEK", "days_per_week"),
                             ("START_VOLUME_H", "start_volume_h")):
        if os.environ.get(env_key):
            data[cfg_key] = os.environ[env_key]
    return data


def _parse_date(v) -> Optional[date]:
    if not v:
        return None
    try:
        return datetime.strptime(str(v), "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_float(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


_cfg = _load()

def _parse_int(v) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


OBJECTIVE: str = _cfg["objective"]
RACE_DATE: Optional[date] = _parse_date(_cfg["race_date"])
PLAN_START: Optional[date] = _parse_date(_cfg["plan_start"])
PLAN_WEEKS: Optional[int] = _parse_int(_cfg["plan_weeks"])
DAYS_PER_WEEK: int = int(_cfg["days_per_week"] or 4)
START_VOLUME_H: Optional[float] = _parse_float(_cfg["start_volume_h"])
PEAK_VOLUME_H: Optional[float] = _parse_float(_cfg["peak_volume_h"])
PACES: Dict[str, str] = dict(_cfg["paces"] or {})


def summary() -> Dict:
    return {
        "objective": OBJECTIVE,
        "race_date": RACE_DATE.isoformat() if RACE_DATE else None,
        "plan_start": PLAN_START.isoformat() if PLAN_START else None,
        "plan_weeks": PLAN_WEEKS,
        "days_per_week": DAYS_PER_WEEK,
        "start_volume_h": START_VOLUME_H,
        "peak_volume_h": PEAK_VOLUME_H,
        "paces_overridden": sorted(PACES.keys()),
        "config_path": CONFIG_PATH,
    }
