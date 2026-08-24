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

# Types d'activités comptées comme "course à pied" (valeurs Strava sport_type)
RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}


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
    if "access_token" not in data:
        raise RuntimeError(f"Réponse Strava inattendue au refresh du token : {data}")
    # NB : Strava peut renvoyer un nouveau refresh_token (data['refresh_token']).
    # Il n'est pas persisté ici (env var non réinscriptible) — voir RUNBOOK.
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
                     per_page: int = 100, max_pages: int = 20) -> List[Activity]:
    """Liste les activités entre `after` et `before` (datetimes aware).

    Paginée : boucle jusqu'à une page vide (Strava renvoie 100 max/page).
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    out: List[Activity] = []
    for page in range(1, max_pages + 1):
        params = urllib.parse.urlencode({
            "after": int(after.timestamp()),
            "before": int(before.timestamp()),
            "per_page": per_page,
            "page": page,
        })
        raw = _http(f"{STRAVA_API}/athlete/activities?{params}", headers=headers)
        if not raw:
            break
        out.extend(_to_activity(a) for a in raw)
        if len(raw) < per_page:
            break
    return out


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


# Nombre de semaines d'historique requis pour un ACWR fiable
ACWR_MIN_HISTORY_WEEKS = 3


def _earliest_run_date(acts: List[Activity]) -> Optional[date]:
    dates = []
    for a in _runs(acts):
        try:
            dates.append(datetime.strptime(a.date, "%Y-%m-%d").date())
        except ValueError:
            continue
    return min(dates) if dates else None


def summarize_week(week_acts: List[Activity], planned_time_s: int,
                   history_acts: Optional[List[Activity]] = None,
                   history_weeks: int = 3, data_available: bool = True) -> WeekSummary:
    """Synthèse de la semaine + charge aiguë/chronique.

    ACWR **non-couplé** : `history_acts` = les semaines PRÉCÉDANT la semaine
    évaluée (elle exclue), et le chronique est divisé par le nombre de semaines
    réellement couvertes (pas un 4.0 en dur). Chronique None si historique < seuil.
    """
    runs = _runs(week_acts)
    total_time = sum(a.moving_time_s for a in runs)
    total_dist = sum(a.distance_m for a in runs)
    total_elev = sum(a.elevation_m for a in runs)
    longest = max((a.moving_time_s for a in runs), default=0)

    acute = total_time / 3600.0
    chronic = None
    if history_acts and history_weeks >= ACWR_MIN_HISTORY_WEEKS:
        hist_runs = _runs(history_acts)
        chronic = sum(a.moving_time_s for a in hist_runs) / 3600.0 / history_weeks

    return WeekSummary(
        n_runs=len(runs),
        total_time_s=total_time,
        total_dist_m=total_dist,
        total_elev_m=total_elev,
        longest_run_s=longest,
        planned_time_s=planned_time_s,
        acute_hours=acute,
        chronic_hours=chronic,
        data_available=data_available,
    )


def weekly_actual_hours(acts: List[Activity], start: date, n_weeks: int,
                        today: Optional[date] = None) -> List[Optional[float]]:
    """Heures de course réelles par semaine de programme (index 0 = semaine 1).

    None = semaine future (postérieure à aujourd'hui) → pas encore de données.
    """
    today = today or datetime.now(timezone.utc).date()
    buckets: List[Optional[float]] = [None] * n_weeks
    for i in range(n_weeks):
        wk_start = start + timedelta(days=7 * i)
        if wk_start <= today:
            buckets[i] = 0.0  # semaine échue ou en cours : 0 par défaut
    for a in _runs(acts):
        try:
            d = datetime.strptime(a.date, "%Y-%m-%d").date()
        except ValueError:
            continue
        idx = (d - start).days // 7
        if 0 <= idx < n_weeks and buckets[idx] is not None:
            buckets[idx] += a.moving_time_s / 3600.0
    return buckets


def completed_week_runs(acts: List[Activity], today: Optional[date] = None) -> List[Activity]:
    """Courses de la semaine qui vient de se terminer (relative au lundi à venir)."""
    today = today or datetime.now(timezone.utc).date()
    um = today + timedelta(days=(7 - today.weekday()) % 7)
    return _runs(in_range(acts, um - timedelta(days=7), um))


def completed_week_summary(acts: List[Activity], planned_time_s: int,
                           today: Optional[date] = None) -> WeekSummary:
    """Résumé de la semaine qui VIENT DE SE TERMINER, relative au lundi à venir.

    Exécuté un dimanche soir → la semaine évaluée est lun-dim se terminant ce
    dimanche (celle dont on va prescrire la suivante). Exécuté un lundi → la
    semaine précédente. Chronique = 3 semaines antérieures (ACWR non-couplé).
    """
    today = today or datetime.now(timezone.utc).date()
    um = today + timedelta(days=(7 - today.weekday()) % 7)  # lundi à venir
    completed_start = um - timedelta(days=7)                 # lundi de la sem. terminée
    week_acts = in_range(acts, completed_start, um)
    hist = in_range(acts, completed_start - timedelta(days=21), completed_start)

    earliest = _earliest_run_date(acts)
    history_weeks = 0
    if earliest is not None:
        history_weeks = max(0, min(3, (completed_start - earliest).days // 7))
    return summarize_week(week_acts, planned_time_s, history_acts=hist,
                          history_weeks=history_weeks)
