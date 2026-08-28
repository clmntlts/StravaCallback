"""Push + planification Garmin d'une semaine — partagé entre la CLI
(`generate.py`) et l'interface web (`webapp/server.py`).

Extrait de `generate.py::_push_garmin`/`_push_garmin_connect` (mêmes deux
voies, même sélection par `is_configured()`) pour ne plus dupliquer la boucle
rôle/date entre la CLI et la route web `POST /api/week/<idx>/push-garmin`.

Ne fait AUCUN print : retourne un résultat structuré, jamais d'exception —
c'est à l'appelant (CLI ou route web) de décider comment l'afficher.
"""

from __future__ import annotations

from datetime import timedelta

from . import garmin, garmin_connect, garmin_workout, program, workouts
from .models import ordered_roles

# Décalage (jours) du rôle par rapport au lundi de la semaine (week_start).
ROLE_OFFSET = {"quality": 1, "easy": 3, "long": 5, "b2b": 6}  # Mar/Jeu/Sam/Dim


def _session_dates(res, idx):
    for role in ordered_roles(res.week.sessions):
        spec = res.week.sessions[role]
        d = (program.week_start(idx) + timedelta(days=ROLE_OFFSET[role])).isoformat()
        yield role, spec, d


def _push_training_api(res, idx: int) -> dict:
    if not garmin.is_configured():
        return {"via": "training-api", "configured": False, "ok": False,
                "detail": None, "results": []}
    try:
        token = garmin.get_access_token()
    except Exception as e:
        return {"via": "training-api", "configured": True, "ok": False,
                "detail": str(e), "results": []}
    results = []
    for role, spec, d in _session_dates(res, idx):
        try:
            wid = garmin.push_and_schedule(garmin_workout.session_to_garmin(spec), d,
                                           access_token=token)
            results.append({"role": role, "date": d, "label": workouts.label(spec),
                            "ok": True, "detail": f"id {wid}"})
        except Exception as e:
            results.append({"role": role, "date": d, "label": workouts.label(spec),
                            "ok": False, "detail": str(e)})
    return {"via": "training-api", "configured": True,
            "ok": all(r["ok"] for r in results), "detail": None, "results": results}


def _push_connect(res, idx: int) -> dict:
    if not garmin_connect.is_configured():
        return {"via": "connect", "configured": False, "ok": False,
                "detail": None, "results": []}
    try:
        client = garmin_connect.login()
    except Exception as e:
        return {"via": "connect", "configured": True, "ok": False,
                "detail": str(e), "results": []}
    results = []
    for role, spec, d in _session_dates(res, idx):
        try:
            wid, client = garmin_connect.push_and_schedule(
                garmin_connect.session_to_connect(spec), d, client=client)
            results.append({"role": role, "date": d, "label": workouts.label(spec),
                            "ok": True, "detail": f"id {wid}"})
        except Exception as e:
            results.append({"role": role, "date": d, "label": workouts.label(spec),
                            "ok": False, "detail": str(e)})
    return {"via": "connect", "configured": True,
            "ok": all(r["ok"] for r in results), "detail": None, "results": results}


def push_week(res, idx: int, via: str = "auto") -> dict:
    """Planifie chaque séance de la semaine `idx` sur Garmin.

    `via` : "training-api" (Training API officielle), "connect" (Garmin
    Connect, voie non-officielle), ou "auto" (préfère la Training API si
    configurée, sinon Connect — un seul bouton côté web, l'utilisateur n'a
    normalement qu'une voie configurée). La CLI appelle explicitement
    "training-api"/"connect" pour préserver exactement le comportement de
    `--push-garmin`/`--push-connect` (indépendants l'un de l'autre).

    Retourne `{via, configured, ok, detail, results}` :
    - `configured=False` : voie non configurée, push ignoré (`detail=None`).
    - `detail` non-nul avec `results=[]` : échec d'auth/connexion.
    - sinon `results` : une entrée par séance `{role, date, label, ok, detail}`
      (`detail` = "id <workout_id>" si `ok`, message d'erreur sinon).
    """
    if via == "auto":
        via = "training-api" if garmin.is_configured() else "connect"
    if via == "training-api":
        return _push_training_api(res, idx)
    if via == "connect":
        return _push_connect(res, idx)
    raise ValueError(f"via inconnu : {via!r} (attendu training-api/connect/auto)")
