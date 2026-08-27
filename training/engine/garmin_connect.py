"""Client Garmin Connect **non-officiel** (via la lib `python-garminconnect`).

Pourquoi ce module : la copie d'un fichier `.FIT` sur la montre ne fait
apparaître la séance que dans la **bibliothèque** (« My Workouts ») — jamais
comme *séance du jour* à une date fixe. Pour qu'une séance soit **proposée
automatiquement le bon jour** sur la montre, il faut la **planifier dans le
calendrier Garmin Connect**. C'est exactement ce que fait ce module : il
**upload** la séance puis la **planifie** à une date ; Connect la synchronise
ensuite sur la montre.

Deux voies coexistent dans le projet pour pousser vers Garmin :
  - `engine/garmin.py`         → API **officielle** (Training API, Developer
                                 Program requis, OAuth2). Voie « propre » mais
                                 soumise à validation Garmin.
  - `engine/garmin_connect.py` → API **non-officielle** (ce fichier) : login
                                 compte Garmin, pas de validation. Fonctionne
                                 tout de suite, au prix d'une dépendance externe
                                 et d'une API rétro-ingénierée qui peut casser.

⚠️ DÉPENDANCE EXTERNE OPTIONNELLE : `pip install garminconnect`. Le reste du
moteur reste *stdlib-only* — l'import de la lib est **paresseux** (uniquement au
login), donc générer les `.FIT`, l'email et les tests ne l'exigent pas.

⚠️ API non-officielle : Garmin peut changer son service sans préavis. Si un
upload échoue, vérifier la version de `garminconnect` et les endpoints
`/workout-service/*`.

Variables d'environnement :
    GARMIN_EMAIL          identifiant du compte Garmin Connect
    GARMIN_PASSWORD       mot de passe du compte
    GARMIN_TOKENS_BASE64  (option, RECOMMANDÉ pour l'automatique cloud) jeton de
                          session encodé base64 (base64 du JSON de session
                          `garminconnect` : di_token / di_refresh_token) — évite
                          de se relogger à chaque run (Garmin limite les logins
                          répétés, voire bloque l'IP datacenter) et fonctionne
                          dans un environnement éphémère (pas de dossier persistant).
                          L'obtenir une fois : `generate.py garmin-connect-token`.
    GARMIN_TOKENSTORE     (option) dossier des jetons (défaut ~/.garminconnect),
                          utilisé en local/persistant si pas de jeton base64.
"""

from __future__ import annotations

import base64
import binascii
import os
from typing import Dict, List, Optional, Tuple

from .fit_encoder import Duration, Intensity, Target, Workout
from .models import SessionSpec
from . import workouts

# --------------------------------------------------------------------------- #
# Schéma workout Garmin Connect (service /workout-service).  Chaque « type »
# porte un id NUMÉRIQUE (fait autorité côté Garmin) + une clé lisible.
# --------------------------------------------------------------------------- #
_SPORT = {"sportTypeId": 1, "sportTypeKey": "running"}

# stepType : type de l'étape (échauffement, intervalle, récup, repos, retour…)
_STEP_TYPE = {
    Intensity.WARMUP:   {"stepTypeId": 1, "stepTypeKey": "warmup"},
    Intensity.COOLDOWN: {"stepTypeId": 2, "stepTypeKey": "cooldown"},
    Intensity.ACTIVE:   {"stepTypeId": 3, "stepTypeKey": "interval"},
    Intensity.RECOVERY: {"stepTypeId": 4, "stepTypeKey": "recovery"},
    Intensity.REST:     {"stepTypeId": 5, "stepTypeKey": "rest"},
}
_STEP_TYPE_REPEAT = {"stepTypeId": 6, "stepTypeKey": "repeat"}

# endCondition : ce qui termine l'étape (temps, distance, appui lap, itérations)
_END_TIME = {"conditionTypeId": 2, "conditionTypeKey": "time"}
_END_DISTANCE = {"conditionTypeId": 3, "conditionTypeKey": "distance"}
_END_LAP = {"conditionTypeId": 1, "conditionTypeKey": "lap.button"}
_END_ITERATIONS = {"conditionTypeId": 7, "conditionTypeKey": "iterations"}

# targetType : cible (allure = pace.zone, bornes en m/s ; FC = heart.rate.zone,
# bornes en bpm réels ; sinon pas de cible)
_TARGET_PACE = {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone"}
_TARGET_HR = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"}
_TARGET_NONE = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}

# Convention FIT (voir workouts.py) : une cible FC est stockée en bpm + 100.
_HR_OFFSET = 100


# --------------------------------------------------------------------------- #
# Traducteur Workout (modèle interne, à plat) → JSON Garmin Connect (imbriqué)
# --------------------------------------------------------------------------- #
def _leaf(step) -> Dict:
    node: Dict = {
        "type": "ExecutableStepDTO",
        "stepType": _STEP_TYPE.get(step.intensity, _STEP_TYPE[Intensity.ACTIVE]),
    }
    if step.name:
        node["description"] = step.name

    if step.duration_type == Duration.TIME:
        node["endCondition"] = _END_TIME
        node["endConditionValue"] = round(step.duration_value / 1000, 1)   # ms -> s
    elif step.duration_type == Duration.DISTANCE:
        node["endCondition"] = _END_DISTANCE
        node["endConditionValue"] = round(step.duration_value / 100, 1)    # cm -> m
    else:
        node["endCondition"] = _END_LAP

    if (step.target_type == Target.SPEED
            and step.custom_low is not None and step.custom_high is not None):
        node["targetType"] = _TARGET_PACE
        # bornes en m/s ; low = plus lent (vitesse faible), high = plus rapide.
        node["targetValueOne"] = round(step.custom_low / 1000, 3)          # mm/s -> m/s
        node["targetValueTwo"] = round(step.custom_high / 1000, 3)
    elif (step.target_type == Target.HEART_RATE
            and step.custom_low is not None and step.custom_high is not None):
        node["targetType"] = _TARGET_HR
        node["targetValueOne"] = step.custom_low - _HR_OFFSET    # bpm+100 -> bpm réel
        node["targetValueTwo"] = step.custom_high - _HR_OFFSET
    elif step.target_type == Target.OPEN:
        node["targetType"] = _TARGET_NONE
    else:
        raise ValueError(
            f"Target Garmin Connect non géré : {step.target_type!r} (step={step.name!r})")
    return node


def _group(count: int, children: List[Dict]) -> Dict:
    return {
        "type": "RepeatGroupDTO",
        "stepType": _STEP_TYPE_REPEAT,
        "numberOfIterations": count,
        "smartRepeat": False,
        "endCondition": _END_ITERATIONS,
        "endConditionValue": float(count),
        "workoutSteps": children,
    }


def _nest(wkt: Workout) -> List[Dict]:
    """Reconstruit l'imbrication des répétitions depuis la liste à plat.

    Dans notre modèle interne, un marqueur REPEAT est placé APRÈS ses enfants ;
    `duration_value` pointe l'index de début de boucle, `target_value` = nb de
    répétitions.
    """
    built: List[Tuple[int, Dict]] = []
    for idx, s in enumerate(wkt.steps):
        if s.duration_type == Duration.REPEAT_UNTIL_STEPS_CMPLT:
            loop, count = s.duration_value, int(s.target_value)
            children = [n for (si, n) in built if si >= loop]
            built = [(si, n) for (si, n) in built if si < loop]
            built.append((loop, _group(count, children)))
        else:
            built.append((idx, _leaf(s)))
    return [n for (_, n) in built]


def _number(nodes: List[Dict], start: int = 1) -> int:
    """Attribue un `stepOrder` unique en profondeur (exigé par Garmin)."""
    order = start
    for node in nodes:
        node["stepOrder"] = order
        order += 1
        if node.get("type") == "RepeatGroupDTO":
            order = _number(node["workoutSteps"], order)
    return order


def session_to_connect(spec: SessionSpec) -> Dict:
    """SessionSpec → payload JSON du service /workout-service de Garmin Connect."""
    wkt = workouts.build_workout(spec)
    steps = _nest(wkt)
    _number(steps)
    return {
        "sportType": _SPORT,
        "workoutName": wkt.name,
        "estimatedDurationInSecs": int(round(workouts.minutes(spec) * 60)),
        "workoutSegments": [{
            "segmentOrder": 1,
            "sportType": _SPORT,
            "workoutSteps": steps,
        }],
    }


# --------------------------------------------------------------------------- #
# Accès réseau (lib externe, import paresseux)
# --------------------------------------------------------------------------- #
def is_configured() -> bool:
    """Vrai si de quoi ouvrir une session : jeton base64 OU e-mail+mot de passe."""
    return bool(os.environ.get("GARMIN_TOKENS_BASE64")
                or (os.environ.get("GARMIN_EMAIL") and os.environ.get("GARMIN_PASSWORD")))


def _import_garmin():
    try:
        from garminconnect import Garmin  # dépendance externe optionnelle
    except ImportError as e:
        raise RuntimeError(
            "Lib 'garminconnect' absente. Installe-la : pip install garminconnect"
        ) from e
    return Garmin


def _token_json_from_env(raw: str) -> str:
    """Normalise la valeur de `GARMIN_TOKENS_BASE64` en JSON de session.

    Format attendu : base64 du JSON produit par `dump_token_base64`. On tolère
    aussi un JSON collé tel quel (au cas où la variable aurait été renseignée
    sans l'encodage).
    """
    s = raw.strip()
    if s.startswith("{"):
        return s
    try:
        return base64.b64decode(s).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return s


def login():
    """Ouvre une session Garmin Connect.

    Ordre de préférence (du plus robuste au plus interactif) :
      1. `GARMIN_TOKENS_BASE64` : restaure une session déjà authentifiée SANS
         mot de passe ni MFA — idéal pour l'automatique en environnement éphémère
         (et pour contourner le blocage/rate-limit des IP datacenter au login).
      2. e-mail + mot de passe (+ dossier de jetons persistant si dispo) : login
         complet ; nécessite de franchir la MFA au 1er login si elle est active.

    API `garminconnect` 0.3.x : la sérialisation de session est portée par le
    client interne (`client.client.dumps/loads`) ; la restauration passe par
    `Garmin.login(tokenstore=<jeton>)`, qui charge le jeton, rafraîchit le
    di_token si besoin et valide la session (récupère le profil). Import
    paresseux de `garminconnect` (le reste du moteur n'en dépend pas).
    """
    Garmin = _import_garmin()

    # 1) Jeton de session en variable d'environnement (sans mot de passe).
    token_env = os.environ.get("GARMIN_TOKENS_BASE64")
    if token_env:
        client = Garmin()
        try:
            # >512 chars => garminconnect traite la chaîne comme un jeton inline
            # (et non comme un chemin) : loads() + refresh + validation profil.
            client.login(tokenstore=_token_json_from_env(token_env))
            return client
        except Exception as e:
            if not (os.environ.get("GARMIN_EMAIL") and os.environ.get("GARMIN_PASSWORD")):
                raise RuntimeError(
                    "GARMIN_TOKENS_BASE64 invalide/expiré et pas d'identifiants de "
                    "repli. Régénère-le : generate.py garmin-connect-token") from e
            # sinon on retombe sur le login complet ci-dessous

    # 2) Login e-mail + mot de passe (dossier de jetons persistant si présent).
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not (email and password):
        raise RuntimeError("GARMIN_EMAIL / GARMIN_PASSWORD manquants (variables d'env).")
    store = os.path.expanduser(os.environ.get("GARMIN_TOKENSTORE", "~/.garminconnect"))
    client = Garmin(email, password)
    try:
        client.login(store)          # réutilise/écrit les jetons du dossier si possible
    except TypeError:
        client.login()               # anciennes versions sans tokenstore
    return client


def dump_token_base64(client) -> str:
    """Sérialise la session courante en base64 (à stocker dans GARMIN_TOKENS_BASE64).

    `garminconnect` 0.3.x sérialise en JSON via le client interne
    (`client.client.dumps()`) ; on l'encode en base64 pour en faire un jeton
    d'une seule ligne, sûr à poser en variable d'environnement.
    """
    raw_json = client.client.dumps()        # JSON : di_token / di_refresh_token / di_client_id
    return base64.b64encode(raw_json.encode("utf-8")).decode("ascii")


def upload_workout(client, payload: Dict) -> str:
    """Crée la séance dans Garmin Connect ; renvoie son id.

    `garminconnect` 0.3.x a figé `Garmin.connectapi()`/`client.connectapi()` sur
    GET (passer `method="POST"` en kwarg lève désormais "got multiple values
    for argument 'method'") : le POST passe par le client interne `client.client`.
    """
    resp = client.client.post("connectapi", "/workout-service/workout",
                              json=payload, api=True)
    wid = (resp or {}).get("workoutId") or (resp or {}).get("workoutKey") \
        or (resp or {}).get("id")
    if wid is None:
        raise RuntimeError(f"Upload workout : id introuvable dans la réponse {resp}")
    return str(wid)


def schedule_workout(client, workout_id: str, date_iso: str) -> Dict:
    """Planifie la séance au CALENDRIER à la date donnée (YYYY-MM-DD).

    C'est cette planification qui la fait apparaître comme *séance du jour* sur
    la montre après synchronisation.
    """
    return client.client.post("connectapi", f"/workout-service/schedule/{workout_id}",
                              json={"date": date_iso}, api=True)


def push_and_schedule(payload: Dict, date_iso: str, client=None) -> Tuple[str, object]:
    """Upload + planification. Renvoie (workout_id, client) pour réutiliser la session."""
    client = client or login()
    wid = upload_workout(client, payload)
    schedule_workout(client, wid, date_iso)
    return wid, client
