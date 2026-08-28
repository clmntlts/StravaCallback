"""Traducteur : Workout (modèle interne, style FIT) → JSON workout Garmin.

La Training API de Garmin attend un workout structuré en JSON, avec les blocs de
répétition **imbriqués** (`WorkoutRepeatStep` contenant des sous-étapes), alors
que notre modèle interne (`fit_encoder`) est **à plat** avec un marqueur de
répétition placé après ses enfants. Ce module reconstruit l'imbrication.

⚠️ RÉCONCILIATION : les noms d'enums et d'unités ci-dessous suivent le schéma
documenté de la Training API Garmin. Si ta doc développeur diffère (ex. `PACE`
au lieu de `SPEED`, ou vitesse en m/s vs allure en s/km), ajuste UNIQUEMENT les
constantes de cette section — le reste du code n'en dépend pas.
"""

from __future__ import annotations

from typing import Dict, List

from .fit_encoder import Duration, Intensity, Target, Workout
from .models import SessionSpec
from . import workouts

# --- Constantes à réconcilier avec la doc Training API --------------------- #
SPORT_RUNNING = "RUNNING"
REPEAT_TYPE = "REPEAT_UNTIL_STEPS_CMPLT"

DURATION_TIME = "TIME"          # valeur en SECONDES
DURATION_DISTANCE = "DISTANCE"  # valeur en MÈTRES
DURATION_OPEN = "OPEN"

TARGET_SPEED = "SPEED"          # bornes en m/s
TARGET_HEART_RATE = "HEART_RATE"  # bornes en bpm réels
TARGET_OPEN = "OPEN"

# Convention FIT (voir workouts.py) : une cible FC est stockée en bpm + 100.
_HR_OFFSET = 100

INTENSITY = {
    Intensity.ACTIVE: "ACTIVE",
    Intensity.REST: "REST",
    Intensity.WARMUP: "WARMUP",
    Intensity.COOLDOWN: "COOLDOWN",
    Intensity.RECOVERY: "RECOVERY",
}
# --------------------------------------------------------------------------- #


def _leaf(step) -> Dict:
    node: Dict = {"type": "WorkoutStep",
                  "intensity": INTENSITY.get(step.intensity, "ACTIVE")}
    if step.name:
        node["description"] = step.name

    if step.duration_type == Duration.TIME:
        node["durationType"] = DURATION_TIME
        node["durationValue"] = round(step.duration_value / 1000)      # ms -> s
    elif step.duration_type == Duration.DISTANCE:
        node["durationType"] = DURATION_DISTANCE
        node["durationValue"] = round(step.duration_value / 100)       # cm -> m
    else:
        node["durationType"] = DURATION_OPEN

    if (step.target_type == Target.SPEED
            and step.custom_low is not None and step.custom_high is not None):
        node["targetType"] = TARGET_SPEED
        node["targetValueLow"] = round(step.custom_low / 1000, 3)      # mm/s -> m/s
        node["targetValueHigh"] = round(step.custom_high / 1000, 3)
    elif (step.target_type == Target.HEART_RATE
            and step.custom_low is not None and step.custom_high is not None):
        node["targetType"] = TARGET_HEART_RATE
        node["targetValueLow"] = step.custom_low - _HR_OFFSET    # bpm+100 -> bpm réel
        node["targetValueHigh"] = step.custom_high - _HR_OFFSET
    elif step.target_type == Target.OPEN:
        node["targetType"] = TARGET_OPEN
    else:
        raise ValueError(
            f"Target Training API non géré : {step.target_type!r} (step={step.name!r})")
    return node


def _nest(wkt: Workout) -> List[Dict]:
    """Reconstruit l'imbrication des répétitions depuis la liste à plat."""
    built = []  # (src_index, node)
    for idx, s in enumerate(wkt.steps):
        if s.duration_type == Duration.REPEAT_UNTIL_STEPS_CMPLT:
            loop, count = s.duration_value, int(s.target_value)
            children = [n for (si, n) in built if si >= loop]
            built = [(si, n) for (si, n) in built if si < loop]
            built.append((loop, {
                "type": "WorkoutRepeatStep",
                "repeatType": REPEAT_TYPE,
                "repeatValue": count,
                "steps": children,
            }))
        else:
            built.append((idx, _leaf(s)))
    return [n for (_, n) in built]


def _number(nodes: List[Dict], start: int = 1) -> int:
    """Attribue stepOrder/stepId en profondeur (Garmin veut un ordre unique)."""
    order = start
    for node in nodes:
        node["stepOrder"] = order
        node["stepId"] = order
        order += 1
        if node.get("type") == "WorkoutRepeatStep":
            order = _number(node["steps"], order)
    return order


def translate_workout(wkt: Workout, minutes: float) -> Dict:
    steps = _nest(wkt)
    _number(steps)
    return {
        "workoutName": wkt.name,
        "sport": SPORT_RUNNING,
        "estimatedDurationInSecs": int(round(minutes * 60)),
        "steps": steps,
    }


def session_to_garmin(spec: SessionSpec) -> Dict:
    return translate_workout(workouts.build_workout(spec), workouts.minutes(spec))
