"""LE moteur adaptatif.

Entrée  : la semaine PRÉVUE (program.py) + la synthèse du RÉALISÉ de la semaine
          précédente (strava.py).
Sortie  : la semaine AJUSTÉE + la liste des ajustements justifiés.

Règles (résumé) — voir README pour le détail :
  1. Une semaine de DÉCHARGE reste intouchable (c'est déjà de la récup).
  2. On mesure l'ADHÉRENCE = temps réalisé / temps prévu (semaine N-1) :
        < 0.60  → REPRISE   : on régresse (scale 0.75), long plafonné.
        < 0.85  → CONSOLIDE : on tempère  (scale 0.90), long plafonné.
        ≤ 1.15  → NOMINAL   : on suit le programme tel quel.
        > 1.15  → VIGILANCE  : pas de sur-dose ; on surveille l'ACWR.
  3. Garde-fou ACWR (charge aiguë/chronique) si dispo :
        > 1.5 → frein de sécurité (scale ≤ 0.8) + qualité rétrogradée en facile.
        > 1.3 → prudence (scale ≤ 0.9).
  4. La SORTIE LONGUE ne bondit jamais de +15 % au-delà de la plus longue
     réellement bouclée la semaine passée (anti-saut de charge).
  5. On ne change JAMAIS le type/rôle d'une séance (structure préservée) ;
     seule exception documentée : rétrograder une qualité en facile si fatigue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from .models import Adjustment, PlannedWeek, SessionSpec, WeekSummary
from . import workouts

# Bornes des bandes d'adhérence
BAND_REPRISE = 0.60
BAND_CONSOLIDE = 0.85
BAND_NOMINAL_HAUT = 1.15

# Plafond de progression de la sortie longue, PAR PHASE.
# Appliqué dans TOUTES les bandes hors décharge : anti-saut de charge inconditionnel,
# mais plus permissif dans les phases où l'on construit délibérément les grosses
# simulations (Spécifique/Pic) pour ne pas brider les répétitions générales.
LONG_GROWTH_DEFAULT = 1.20
LONG_GROWTH_BY_PHASE = {
    "Fondation": 1.20,
    "Force-endurance": 1.35,
    "Spécifique": 1.30,   # [E8] resserré (était 1.60, 3-6x la norme sûre sur la
    "Pic": 1.30,           # séance continue la plus traumatisante) ; le découplage
    "Affûtage": 1.20,      # backyard [E1] reste intact (template != "long" ici)
}

# Seuils ACWR (partagés avec le dashboard)
ACWR_BRAKE = 1.5
ACWR_CAUTION = 1.3
ACWR_LOW = 0.8


def long_growth(phase: str) -> float:
    return LONG_GROWTH_BY_PHASE.get(phase, LONG_GROWTH_DEFAULT)

# Planchers de bon sens
FLOOR_MIN = 20             # minutes minimum d'une séance en durée
FLOOR_LONG_MIN = 40
FLOOR_LOOPS = 3
FLOOR_HOURS = 1.0

# Quel paramètre chaque template met à l'échelle
_SCALE_PARAM = {
    "easy": "minutes", "recovery": "minutes", "strides": "minutes",
    "long": "minutes", "b2b": "minutes", "night": "minutes",
    "threshold": "reps", "hills": "reps", "cruise": "reps", "resist": "reps",
    "backyard": "loops", "runwalk": "hours",
}
_LONG_TEMPLATES = {"long", "runwalk", "backyard", "night"}


@dataclass
class AdaptResult:
    week: PlannedWeek
    adjustments: List[Adjustment]
    band: str
    scale: float
    acwr: Optional[float]
    message: str


# --------------------------------------------------------------------------- #
# Helpers d'échelle
# --------------------------------------------------------------------------- #
def _round5(x: float) -> int:
    return int(5 * round(x / 5))


def _round_half(x: float) -> float:
    return round(x * 2) / 2


def _scaled_spec(spec: SessionSpec, scale: float) -> SessionSpec:
    """Applique un facteur d'échelle au bon paramètre, avec arrondi & plancher."""
    kind = _SCALE_PARAM.get(spec.template)
    if kind is None or scale == 1.0:
        return spec.copy()
    is_long = spec.template in _LONG_TEMPLATES
    if kind == "minutes":
        m = _round5(spec.params["minutes"] * scale)
        m = max(FLOOR_LONG_MIN if is_long else FLOOR_MIN, m)
        return spec.copy(minutes=m)
    if kind == "reps":
        r = max(1, round(spec.params["reps"] * scale))
        return spec.copy(reps=r)
    if kind == "loops":
        n = max(FLOOR_LOOPS, round(spec.params["loops"] * scale))
        return spec.copy(loops=n)
    if kind == "hours":
        h = max(FLOOR_HOURS, _round_half(spec.params["hours"] * scale))
        return spec.copy(hours=h)
    return spec.copy()


def _set_duration(spec: SessionSpec, target_min: float) -> SessionSpec:
    """Ramène la durée totale d'une séance ~à `target_min` (plafond)."""
    kind = _SCALE_PARAM.get(spec.template)
    if kind == "minutes":
        return spec.copy(minutes=max(FLOOR_LONG_MIN, _round5(target_min)))
    if kind == "loops":
        run = spec.params.get("run_min", 50) + spec.params.get("rest_min", 10)
        return spec.copy(loops=max(FLOOR_LOOPS, round(target_min / run)))
    if kind == "hours":
        return spec.copy(hours=max(FLOOR_HOURS, _round_half(target_min / 60)))
    return spec.copy()


# --------------------------------------------------------------------------- #
# Choix de la bande + facteur global
# --------------------------------------------------------------------------- #
def _band_and_scale(adherence: float) -> Tuple[str, float]:
    if adherence < BAND_REPRISE:
        # proportionnel à la profondeur du trou : 20 % réalisé → ×0.50, 55 % → ×0.75
        return "reprise", max(0.50, min(0.75, adherence + 0.20))
    if adherence < BAND_CONSOLIDE:
        return "consolide", 0.90
    if adherence <= BAND_NOMINAL_HAUT:
        return "nominal", 1.0
    # au-dessus du prévu : léger frein pour ne pas empiler la fatigue
    return "vigilance", 0.95


# --------------------------------------------------------------------------- #
# Cœur
# --------------------------------------------------------------------------- #
def adapt_week(planned: PlannedWeek, last: WeekSummary) -> AdaptResult:
    adjustments: List[Adjustment] = []
    out = planned.copy()

    # 1) Décharge : intouchable
    if planned.deload:
        return AdaptResult(
            week=out, adjustments=[], band="deload", scale=1.0,
            acwr=last.acwr,
            message="Semaine de décharge : conservée telle quelle (récupération programmée).",
        )

    # 1bis) Aucune donnée Strava fournie → on ne fabrique rien : nominal, non adapté.
    if not last.data_available:
        return AdaptResult(
            week=out, adjustments=[], band="nominal", scale=1.0, acwr=None,
            message="Aucune donnée Strava fournie : semaine prescrite au nominal "
                    "(non adaptée). Fournir l'activité pour l'adaptation.",
        )

    # Base aérobie entretenue par le cross-training (vélo, etc.) ? Si la charge
    # aérobie TOTALE réalisée atteint ~le volume course prévu, l'athlète n'est pas
    # déconditionné : on ne régresse pas le plan course sur la seule pénurie de
    # course. La sécurité SPÉCIFIQUE course (plafond de la sortie longue) reste,
    # elle, pilotée par la course seule plus bas.
    base_maintained = last.cross_hours > 0 and last.aerobic_adherence >= BAND_CONSOLIDE

    # 1ter) Semaine terminée SANS aucune sortie alors qu'il y avait du prévu :
    # probable trou de synchro plutôt qu'un vrai zéro → on ne régresse pas en
    # silence, on tient le nominal et on signale pour vérification humaine.
    # Exception : si du cross-training a maintenu la base, on tient le nominal
    # sereinement (pas d'alerte "synchro manquée").
    if last.planned_time_s > 0 and last.n_runs == 0 and not base_maintained:
        return AdaptResult(
            week=out, adjustments=[], band="verifier", scale=1.0, acwr=last.aerobic_acwr,
            message="0 sortie détectée la semaine passée (repos réel ou synchro "
                    "manquée ?). Semaine tenue au nominal — à vérifier.",
        )

    adherence = last.adherence
    band, scale = _band_and_scale(adherence)
    # Garde-fou anti-régression : la base est là (cross-training) → pas de recul.
    if base_maintained and band in ("reprise", "consolide"):
        band, scale = "nominal", 1.0
    acwr = last.aerobic_acwr  # ACWR sur la charge aérobie totale (fatigue réelle)

    # 2) Garde-fou ACWR : peut durcir le frein
    brake_quality = False
    if acwr is not None:
        if acwr > ACWR_BRAKE:
            scale = min(scale, 0.8)
            brake_quality = True
        elif acwr > ACWR_CAUTION:
            scale = min(scale, 0.9)

    # 3) Application du facteur global à chaque séance (structure préservée)
    if scale != 1.0:
        for role, spec in list(out.sessions.items()):
            new = _scaled_spec(spec, scale)
            if workouts.label(new) != workouts.label(spec):
                adjustments.append(Adjustment(
                    role=role, before=workouts.label(spec), after=workouts.label(new),
                    reason=f"volume × {scale:.2f} (adhérence {adherence:.0%})",
                ))
            out.sessions[role] = new

    # 4) Plafond de la sortie longue (anti-saut) — INCONDITIONNEL hors décharge,
    #    avec un facteur dépendant de la phase (généreux en Spécifique/Pic).
    #    [E1] Ne s'applique qu'aux séances CONTINUES (template "long") : une simu
    #    backyard/night/runwalk assignée au rôle "long" compte le REPOS dans ses
    #    minutes (12 boucles = 720' dont ~600' de repos), incomparable au temps
    #    de MOUVEMENT réel `ref_long_s` — le cap étranglait systématiquement les
    #    sims (le dashboard promettait 12/14 boucles, le .fit en encodait bien
    #    moins). La progression backyard reste pilotée par le nombre de boucles
    #    du plan (déjà en paliers) et par le facteur d'adhérence (étape 3).
    growth = long_growth(planned.phase)
    # rolling max des ~3 dernières semaines : une longue sautée isolée ne sur-restreint pas
    ref_long_s = max(last.longest_run_s, last.rolling_longest_s)
    long_spec = out.sessions.get("long")
    if long_spec is not None and long_spec.template == "long" and ref_long_s > 0:
        cap_min = (ref_long_s / 60.0) * growth
        if workouts.minutes(long_spec) > cap_min:
            capped = _set_duration(long_spec, cap_min)
            adjustments.append(Adjustment(
                role="long", before=workouts.label(long_spec), after=workouts.label(capped),
                reason=(f"plafonnée : +{(growth-1)*100:.0f} % max vs plus longue récente "
                        f"({ref_long_s/60:.0f}' → cap {cap_min:.0f}')"),
            ))
            out.sessions["long"] = capped

    # 3bis) Rétrograder la qualité en facile si fatigue marquée (ACWR élevé)
    if brake_quality and "quality" in out.sessions:
        q = out.sessions["quality"]
        if q.template not in ("easy", "recovery", "strides"):
            easy_spec = SessionSpec("easy", {"minutes": 50})
            adjustments.append(Adjustment(
                role="quality", before=workouts.label(q), after=workouts.label(easy_spec),
                reason=f"fatigue élevée (ACWR {acwr:.2f}) : qualité rétrogradée en facile",
            ))
            out.sessions["quality"] = easy_spec

    message = _message(band, adherence, acwr, last, adjustments, base_maintained)
    return AdaptResult(out, adjustments, band, scale, acwr, message)


def _message(band, adherence, acwr, last: WeekSummary, adjustments,
             base_maintained: bool = False) -> str:
    head = {
        "reprise": "REPRISE — semaine passée bien en deçà du prévu, on régresse pour repartir sainement.",
        "consolide": "CONSOLIDATION — semaine passée partiellement réalisée, on tempère.",
        "nominal": "NOMINAL — semaine passée conforme, on suit le programme.",
        "vigilance": "VIGILANCE — semaine passée au-dessus du prévu, pas de sur-dose.",
    }[band]
    bits = [head]
    if last.planned_time_s > 0:
        bits.append(f"Réalisé {last.actual_hours:.1f} h / {last.planned_hours:.1f} h prévues "
                    f"({adherence:.0%}), {last.n_runs} sorties.")
    if base_maintained and last.cross_hours > 0:
        bits.append(f"Base aérobie tenue par le cross-training "
                    f"({last.cross_hours:.1f} h vélo/autre) : pas de régression.")
    if acwr is not None:
        bits.append(f"ACWR {acwr:.2f}.")
    if not adjustments:
        bits.append("Aucun ajustement : la semaine est appliquée telle quelle.")
    else:
        bits.append(f"{len(adjustments)} ajustement(s).")
    return " ".join(bits)
