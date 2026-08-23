"""Client Strava minimal (stdlib uniquement) + synthèse hebdomadaire.

Deux sources d'activités possibles :
  1. l'API Strava en direct (rafraîchit le token puis liste les activités),
  2. un fichier JSON de fixture (dév/tests, et quand l'API n'est pas branchée).

Auth par variables d'environnement (jamais en dur dans le repo) :
    STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, STRAVA_REFRESH_TOKEN
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from .models import Activity, WeekSummary

STRAVA_API = "https://www.strava.com/api/v3"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"

# Types d'activités comptées comme "course à pied"
RUN_TYPES = {"Run", "TrailRun", "VirtualRun", "Treadmill"}


# --------------------------------------------------------------------------- #
# HTTP (stdlib) — respecte HTTPS_PROXY si présent
# --------------------------------------------------------------------------- #
def _http(url: str, data: Optional[bytes] = None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# --------------------------------------------------------------------------- #
# OAuth
# --------------------------------------------------------------------------- #
def refresh_access_token(client_id=None, client_secret=None, refresh_token=None) -> str:
    client_id = client_id or os.environ.get("STRAVA_CLIENT_ID")
    client_secret = client_secret or os.environ.get("STRAVA_CLIENT_SECRET")
    refresh_token = refresh_token or os.environ.get("STRAVA_REFRESH_TOKEN")
    if not (client_id and client_secret and refresh_token):
        raise RuntimeError(
            "Identifiants Strava manquants : définis STRAVA_CLIENT_ID, "
            "STRAVA_CLIENT_SECRET, STRAVA_REFRESH_TOKEN."
        )
    body = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }).encode()
    data = _http(STRAVA_TOKEN_URL, data=body, method="POST")
    return data["access_token"]


# --------------------------------------------------------------------------- #
# Récupération d'activités
# --------------------------------------------------------------------------- #
def _to_activity(a: dict) -> Activity:
    start = a.get("start_date_local") or a.get("start_date") or ""
    return Activity(
        date=start[:10],
        moving_time_s=int(a.get("moving_time", 0)),
        distance_m=float(a.get("distance", 0.0)),
        elevation_m=float(a.get("total_elevation_gain", 0.0)),
        sport=a.get("sport_type") or a.get("type", "Run"),
        avg_hr=a.get("average_heartrate"),
        name=a.get("name", ""),
    )


def fetch_activities(access_token: str, after: datetime, before: datetime,
                     per_page: int = 100) -> List[Activity]:
    """Liste les activités entre `after` et `before` (datetimes aware)."""
    params = urllib.parse.urlencode({
        "after": int(after.timestamp()),
        "before": int(before.timestamp()),
        "per_page": per_page,
    })
    url = f"{STRAVA_API}/athlete/activities?{params}"
    raw = _http(url, headers={"Authorization": f"Bearer {access_token}"})
    return [_to_activity(a) for a in raw]


def load_activities_file(path: str) -> List[Activity]:
    """Charge des activités depuis un JSON (liste d'objets Strava bruts)."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return [_to_activity(a) for a in raw]


# --------------------------------------------------------------------------- #
# Filtres & synthèse
# --------------------------------------------------------------------------- #
def _runs(acts: List[Activity]) -> List[Activity]:
    return [a for a in acts if a.sport in RUN_TYPES]


def in_range(acts: List[Activity], start: date, end: date) -> List[Activity]:
    """Activités dont la date ∈ [start, end)."""
    out = []
    for a in acts:
        try:
            d = datetime.strptime(a.date, "%Y-%m-%d").date()
        except ValueError:
            continue
        if start <= d < end:
            out.append(a)
    return out


def summarize_week(week_acts: List[Activity], planned_time_s: int,
                   history_acts: Optional[List[Activity]] = None) -> WeekSummary:
    """Synthèse de la semaine + charge aiguë/chronique si historique fourni.

    `history_acts` = activités des ~28 derniers jours (pour l'ACWR).
    """
    runs = _runs(week_acts)
    total_time = sum(a.moving_time_s for a in runs)
    total_dist = sum(a.distance_m for a in runs)
    total_elev = sum(a.elevation_m for a in runs)
    longest = max((a.moving_time_s for a in runs), default=0)

    acute = total_time / 3600.0
    chronic = None
    if history_acts:
        hist_runs = _runs(history_acts)
        chronic = sum(a.moving_time_s for a in hist_runs) / 3600.0 / 4.0  # moyenne hebdo sur 4 sem.

    return WeekSummary(
        n_runs=len(runs),
        total_time_s=total_time,
        total_dist_m=total_dist,
        total_elev_m=total_elev,
        longest_run_s=longest,
        planned_time_s=planned_time_s,
        acute_hours=acute,
        chronic_hours=chronic,
    )


def last_week_summary(acts: List[Activity], planned_time_s: int,
                      today: Optional[date] = None) -> WeekSummary:
    """Résumé de la semaine calendaire précédente (lun-dim) + ACWR sur 28 j."""
    today = today or datetime.now(timezone.utc).date()
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(days=7)
    week_acts = in_range(acts, last_monday, this_monday)
    hist = in_range(acts, this_monday - timedelta(days=28), this_monday)
    return summarize_week(week_acts, planned_time_s, history_acts=hist)
