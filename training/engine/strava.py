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
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from . import clock, config
from .models import Activity, WeekSummary

STRAVA_API = "https://www.strava.com/api/v3"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"

# Types d'activités comptées comme "course à pied" (valeurs Strava sport_type)
RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}

# Cross-training aérobie (compte dans la BASE/charge, pondéré ; jamais dans le
# volume course prescrit). Vélo, rameur, ski de fond, elliptique, natation…
CROSS_TYPES = {
    "Ride", "GravelRide", "VirtualRide", "MountainBikeRide", "EBikeRide",
    "EMountainBikeRide", "Handcycle", "Velomobile",
    "Rowing", "VirtualRow", "Kayaking", "Canoeing", "Swim",
    "NordicSki", "BackcountrySki", "RollerSki", "Elliptical", "StairStepper",
}


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
    # Sans lire le corps, un refresh en échec ne rend qu'un « HTTP Error 400 »
    # inutile — or c'est le mode de panne n°1 du run hebdo (#20). On décode le
    # corps et on rend un 400 (refresh_token expiré/révoqué, cas dominant)
    # actionnable. NB : Strava utilise son propre schéma d'erreur, sans le
    # littéral `invalid_grant` — on se fie donc au code HTTP, pas au texte.
    try:
        data = _http(STRAVA_TOKEN_URL, data=body, method="POST")
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "replace").strip()
        except Exception:
            detail = ""
        if e.code == 400:
            raise RuntimeError(
                "Strava a rejeté le refresh du token (HTTP 400) — le "
                "refresh_token est probablement expiré ou révoqué. Régénère-le "
                "une fois : `python3 training/generate.py strava-auth-url` puis "
                "`strava-auth-exchange` (voir training/RUNBOOK.md). "
                f"Réponse Strava : {detail or '(vide)'}"
            ) from e
        raise RuntimeError(
            f"Échec du refresh du token Strava (HTTP {e.code}) : "
            f"{detail or e.reason}"
        ) from e
    if "access_token" not in data:
        raise RuntimeError(f"Réponse Strava inattendue au refresh du token : {data}")
    # NB : Strava peut renvoyer un nouveau refresh_token (data['refresh_token']).
    # Il n'est pas persisté ici (env var non réinscriptible) — voir RUNBOOK.
    return data["access_token"]


# --------------------------------------------------------------------------- #
# Autorisation initiale (obtenir un refresh_token, une seule fois)
# Remplace l'ancien callback OAuth : le projet est autonome.
# --------------------------------------------------------------------------- #
STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"


def authorize_url(client_id=None, redirect_uri=None, scope="activity:read_all") -> str:
    """URL de consentement Strava à ouvrir UNE fois dans un navigateur."""
    params = urllib.parse.urlencode({
        "client_id": client_id or os.environ.get("STRAVA_CLIENT_ID", ""),
        "response_type": "code",
        "redirect_uri": redirect_uri or os.environ.get("STRAVA_REDIRECT_URI", "http://localhost"),
        "approval_prompt": "force",
        "scope": scope,
    })
    return f"{STRAVA_AUTHORIZE_URL}?{params}"


def exchange_code(code: str, client_id=None, client_secret=None) -> dict:
    """Échange le code d'autorisation contre {access_token, refresh_token, ...}."""
    body = urllib.parse.urlencode({
        "client_id": client_id or os.environ.get("STRAVA_CLIENT_ID"),
        "client_secret": client_secret or os.environ.get("STRAVA_CLIENT_SECRET"),
        "code": code,
        "grant_type": "authorization_code",
    }).encode()
    return _http(STRAVA_TOKEN_URL, data=body, method="POST")


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


def _cross(acts: List[Activity]) -> List[Activity]:
    """Activités de cross-training aérobie (vélo, etc.) — hors course."""
    return [a for a in acts if a.sport in CROSS_TYPES]


def _hours(acts: List[Activity]) -> float:
    return sum(a.moving_time_s for a in acts) / 3600.0


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


def _earliest_aerobic_date(acts: List[Activity]) -> Optional[date]:
    """Première activité aérobie (course OU cross-training) : borne l'historique
    de charge chronique. Un long passé vélo compte donc comme de la base."""
    dates = []
    for a in _runs(acts) + _cross(acts):
        try:
            dates.append(datetime.strptime(a.date, "%Y-%m-%d").date())
        except ValueError:
            continue
    return min(dates) if dates else None


def summarize_week(week_acts: List[Activity], planned_time_s: int,
                   history_acts: Optional[List[Activity]] = None,
                   history_weeks: int = 3, data_available: bool = True,
                   cross_weight: Optional[float] = None) -> WeekSummary:
    """Synthèse de la semaine + charge aiguë/chronique (course ET aérobie totale).

    ACWR **non-couplé** : `history_acts` = les semaines PRÉCÉDANT la semaine
    évaluée (elle exclue), et le chronique est divisé par le nombre de semaines
    réellement couvertes (pas un 4.0 en dur). Chronique None si historique < seuil.

    Deux charges sont calculées en parallèle :
      - **course seule** (acute/chronic) : pilote le volume course prescrit ;
      - **aérobie totale** (aerobic_*) : course + cross-training pondéré
        (`cross_weight`), pour l'ACWR de fatigue et le garde-fou anti-régression.
    """
    weight = config.CROSS_TRAINING_WEIGHT if cross_weight is None else cross_weight
    runs = _runs(week_acts)
    total_time = sum(a.moving_time_s for a in runs)
    total_dist = sum(a.distance_m for a in runs)
    total_elev = sum(a.elevation_m for a in runs)
    longest = max((a.moving_time_s for a in runs), default=0)
    cross_time = sum(a.moving_time_s for a in _cross(week_acts))

    acute = total_time / 3600.0
    aerobic_acute = acute + weight * (cross_time / 3600.0)
    chronic = aerobic_chronic = None
    if history_acts and history_weeks >= ACWR_MIN_HISTORY_WEEKS:
        chronic = _hours(_runs(history_acts)) / history_weeks
        aerobic_chronic = (_hours(_runs(history_acts))
                           + weight * _hours(_cross(history_acts))) / history_weeks

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
        cross_time_s=cross_time,
        aerobic_acute_hours=aerobic_acute,
        aerobic_chronic_hours=aerobic_chronic,
    )


def weekly_actual_hours(acts: List[Activity], start: date, n_weeks: int,
                        today: Optional[date] = None) -> List[Optional[float]]:
    """Heures de course réelles par semaine de programme (index 0 = semaine 1).

    None = semaine future (postérieure à aujourd'hui) → pas encore de données.
    """
    today = today or clock.today()
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
    today = today or clock.today()
    um = today + timedelta(days=(7 - today.weekday()) % 7)
    return _runs(in_range(acts, um - timedelta(days=7), um))


def recent_completed_weeks(acts: List[Activity], today: Optional[date] = None,
                           n: int = 4) -> List[List[Activity]]:
    """Courses des `n` dernières semaines terminées ; index 0 = la plus récente."""
    today = today or clock.today()
    um = today + timedelta(days=(7 - today.weekday()) % 7)
    out = []
    for k in range(n):
        end = um - timedelta(days=7 * k)
        out.append(_runs(in_range(acts, end - timedelta(days=7), end)))
    return out


def history_json(activities: List[Activity], start: date, end: date) -> dict:
    """Agrège l'historique Strava (course + cross-training, tous types) sur
    [start, end) pour l'onglet Historique du dashboard web : calendrier
    quotidien (heatmap), volume/dénivelé/FC hebdomadaires. `start` doit être
    un lundi pour que la grille hebdo s'aligne proprement (comme le
    calendrier de contributions GitHub)."""
    acts = in_range(activities, start, end)

    by_day: dict = {}
    for a in acts:
        b = by_day.setdefault(a.date, {"hours": 0.0, "km": 0.0})
        b["hours"] += a.moving_time_s / 3600.0
        b["km"] += a.distance_m / 1000.0

    daily = []
    d = start
    while d < end:
        v = by_day.get(d.isoformat(), {"hours": 0.0, "km": 0.0})
        daily.append({"date": d.isoformat(), "hours": round(v["hours"], 2),
                      "km": round(v["km"], 1)})
        d += timedelta(days=1)

    n_weeks = -(-(end - start).days // 7)  # division entière arrondie au sup.
    weekly = []
    cumulative_elev = 0.0
    for i in range(n_weeks):
        wk_start = start + timedelta(days=7 * i)
        wk_end = min(wk_start + timedelta(days=7), end)
        wk_acts = in_range(acts, wk_start, wk_end)
        hours = sum(a.moving_time_s for a in wk_acts) / 3600.0
        km = sum(a.distance_m for a in wk_acts) / 1000.0
        elev = sum(a.elevation_m for a in wk_acts)
        cumulative_elev += elev
        hr_vals = [a.avg_hr for a in wk_acts if a.avg_hr]
        weekly.append({
            "week_start": wk_start.isoformat(),
            "hours": round(hours, 2),
            "km": round(km, 1),
            "elevation_m": round(elev, 0),
            "elevation_cumulative_m": round(cumulative_elev, 0),
            "avg_hr": round(sum(hr_vals) / len(hr_vals), 1) if hr_vals else None,
            "activities": len(wk_acts),
        })

    totals = {
        "hours": round(sum(a.moving_time_s for a in acts) / 3600.0, 1),
        "km": round(sum(a.distance_m for a in acts) / 1000.0, 1),
        "elevation_m": round(cumulative_elev, 0),
        "activities": len(acts),
    }
    return {"start": start.isoformat(), "end": end.isoformat(),
            "daily": daily, "weekly": weekly, "totals": totals}


def completed_week_summary(acts: List[Activity], planned_time_s: int,
                           today: Optional[date] = None) -> WeekSummary:
    """Résumé de la semaine qui VIENT DE SE TERMINER, relative au lundi à venir.

    Exécuté un dimanche soir → la semaine évaluée est lun-dim se terminant ce
    dimanche (celle dont on va prescrire la suivante). Exécuté un lundi → la
    semaine précédente. Chronique = 3 semaines antérieures (ACWR non-couplé).
    """
    today = today or clock.today()
    um = today + timedelta(days=(7 - today.weekday()) % 7)  # lundi à venir
    completed_start = um - timedelta(days=7)                 # lundi de la sem. terminée
    week_acts = in_range(acts, completed_start, um)
    hist = in_range(acts, completed_start - timedelta(days=21), completed_start)

    earliest = _earliest_aerobic_date(acts)
    history_weeks = 0
    if earliest is not None:
        history_weeks = max(0, min(3, (completed_start - earliest).days // 7))
    return summarize_week(week_acts, planned_time_s, history_acts=hist,
                          history_weeks=history_weeks)
