"""Client Garmin (API officielle, Developer Program — Training API).

Permet de CRÉER des workouts structurés et de les PLANIFIER à une date : ils se
synchronisent sur la montre via Garmin Connect. Pur stdlib (urllib).

Activation conditionnelle : `is_configured()` est vrai seulement si les
identifiants sont présents en variables d'environnement. Sinon, le pipeline
retombe proprement sur l'email + `.FIT`.

Variables d'environnement :
    GARMIN_CONSUMER_KEY       client id de l'app Garmin (Developer Program)
    GARMIN_CONSUMER_SECRET    client secret
    GARMIN_REFRESH_TOKEN      token de rafraîchissement utilisateur (après consentement)
    GARMIN_REDIRECT_URI       (auth) URL de redirection déclarée sur l'app
    GARMIN_SCOPE              (option) scopes OAuth demandés
    GARMIN_TOKEN_URL / GARMIN_AUTH_URL / GARMIN_TRAINING_API_BASE  (option) overrides

⚠️ RÉCONCILIATION : les URLs et le format des réponses ci-dessous suivent le
schéma public connu de Garmin. Confirme-les avec TA console développeur Garmin
(onglets OAuth2 + Training API) et surcharge au besoin via les variables d'env
`GARMIN_*_URL` / `GARMIN_TRAINING_API_BASE`. Le reste du code n'en dépend pas.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import urllib.parse
import urllib.request
from typing import Dict, Optional, Tuple

# --- Endpoints (surchargables par env) ------------------------------------- #
AUTH_URL = os.environ.get("GARMIN_AUTH_URL", "https://connect.garmin.com/oauth2Confirm")
TOKEN_URL = os.environ.get("GARMIN_TOKEN_URL",
                           "https://diauth.garmin.com/di-oauth2-service/oauth/token")
API_BASE = os.environ.get("GARMIN_TRAINING_API_BASE", "https://apis.garmin.com/training-api")
WORKOUT_PATH = "/workout"
SCHEDULE_PATH = "/schedule"
# --------------------------------------------------------------------------- #


def is_configured() -> bool:
    return all(os.environ.get(k) for k in
               ("GARMIN_CONSUMER_KEY", "GARMIN_CONSUMER_SECRET", "GARMIN_REFRESH_TOKEN"))


def _post_form(url: str, fields: Dict[str, str]) -> Dict:
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _post_json(url: str, payload: Dict, access_token: str) -> Dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {access_token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8")
        return json.loads(raw) if raw.strip() else {}


# --- OAuth2 ---------------------------------------------------------------- #
def get_access_token() -> str:
    """Échange le refresh token contre un access token."""
    if not is_configured():
        raise RuntimeError("Identifiants Garmin manquants (GARMIN_CONSUMER_KEY/"
                           "SECRET/REFRESH_TOKEN).")
    data = _post_form(TOKEN_URL, {
        "grant_type": "refresh_token",
        "client_id": os.environ["GARMIN_CONSUMER_KEY"],
        "client_secret": os.environ["GARMIN_CONSUMER_SECRET"],
        "refresh_token": os.environ["GARMIN_REFRESH_TOKEN"],
    })
    if "access_token" not in data:
        raise RuntimeError(f"Réponse token Garmin inattendue : {data}")
    return data["access_token"]


def make_pkce() -> Tuple[str, str]:
    """(code_verifier, code_challenge S256) pour le flux d'autorisation."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(code_challenge: str, state: str = "state") -> str:
    """URL de consentement à ouvrir UNE fois dans un navigateur."""
    params = {
        "response_type": "code",
        "client_id": os.environ.get("GARMIN_CONSUMER_KEY", ""),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "redirect_uri": os.environ.get("GARMIN_REDIRECT_URI", ""),
        "state": state,
    }
    scope = os.environ.get("GARMIN_SCOPE")
    if scope:
        params["scope"] = scope
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def exchange_code(code: str, code_verifier: str) -> Dict:
    """Échange le code d'autorisation contre {access_token, refresh_token, ...}."""
    return _post_form(TOKEN_URL, {
        "grant_type": "authorization_code",
        "client_id": os.environ.get("GARMIN_CONSUMER_KEY", ""),
        "client_secret": os.environ.get("GARMIN_CONSUMER_SECRET", ""),
        "code": code,
        "code_verifier": code_verifier,
        "redirect_uri": os.environ.get("GARMIN_REDIRECT_URI", ""),
    })


# --- Training API ---------------------------------------------------------- #
def create_workout(access_token: str, workout_json: Dict) -> str:
    resp = _post_json(API_BASE + WORKOUT_PATH, workout_json, access_token)
    wid = resp.get("workoutId") or resp.get("id") or resp.get("workoutKey")
    if wid is None:
        raise RuntimeError(f"Création workout : id introuvable dans la réponse {resp}")
    return str(wid)


def schedule_workout(access_token: str, workout_id: str, date_iso: str) -> Dict:
    """Planifie un workout à une date (YYYY-MM-DD)."""
    return _post_json(API_BASE + SCHEDULE_PATH,
                      {"workoutId": workout_id, "date": date_iso}, access_token)


def push_and_schedule(workout_json: Dict, date_iso: str,
                      access_token: Optional[str] = None) -> str:
    """Crée puis planifie un workout ; renvoie l'id créé."""
    token = access_token or get_access_token()
    wid = create_workout(token, workout_json)
    schedule_workout(token, wid, date_iso)
    return wid
