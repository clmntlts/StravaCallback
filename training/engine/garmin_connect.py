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
    GARMIN_EMAIL        identifiant du compte Garmin Connect
    GARMIN_PASSWORD     mot de passe du compte
    GARMIN_TOKENSTORE   (option) dossier des jetons (défaut ~/.garminconnect) —
                        évite de se relogger (et de repasser la MFA) à chaque run
"""

from __future__ import annotations

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

# targetType : cible (allure = pace.zone, bornes en m/s ; sinon pas de cible)
_TARGET_PACE = {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone"}
_TARGET_NONE = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}


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
    else:
        node["targetType"] = _TARGET_NONE
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
    return bool(os.environ.get("GARMIN_EMAIL") and os.environ.get("GARMIN_PASSWORD"))


def login():
    """Ouvre une session Garmin Connect (réutilise les jetons si présents).

    Import paresseux de `garminconnect` : absente, on lève une RuntimeError
    explicite (le reste du moteur n'en dépend pas).
    """
    try:
        from garminconnect import Garmin  # dépendance externe optionnelle
    except ImportError as e:
        raise RuntimeError(
            "Lib 'garminconnect' absente. Installe-la : pip install garminconnect"
        ) from e

    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not (email and password):
        raise RuntimeError("GARMIN_EMAIL / GARMIN_PASSWORD manquants (variables d'env).")

    store = os.path.expanduser(os.environ.get("GARMIN_TOKENSTORE", "~/.garminconnect"))
    client = Garmin(email, password)
    try:
        client.login(store)          # réutilise les jetons stockés si valides
    except TypeError:
        client.login()               # anciennes versions sans tokenstore
    return client


def upload_workout(client, payload: Dict) -> str:
    """Crée la séance dans Garmin Connect ; renvoie son id."""
    resp = client.connectapi("/workout-service/workout", method="POST", json=payload)
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
    return client.connectapi(f"/workout-service/schedule/{workout_id}",
                             method="POST", json={"date": date_iso})


def push_and_schedule(payload: Dict, date_iso: str, client=None) -> Tuple[str, object]:
    """Upload + planification. Renvoie (workout_id, client) pour réutiliser la session."""
    client = client or login()
    wid = upload_workout(client, payload)
    schedule_workout(client, wid, date_iso)
    return wid, client
