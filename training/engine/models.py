"""Types de données du moteur d'entraînement adaptatif."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional

# Les quatre "rôles" hebdomadaires (la structure ne change jamais).
# Un rôle est rattaché à un jour par défaut mais reste déplaçable.
ROLES = ["quality", "easy", "long", "b2b"]
ROLE_DAY = {"quality": "Mardi", "easy": "Jeudi", "long": "Samedi", "b2b": "Dimanche"}
ROLE_LABEL = {
    "quality": "Qualité",
    "easy": "Facile",
    "long": "Sortie longue",
    "b2b": "Back-to-back",
}


@dataclass
class SessionSpec:
    """Une séance = un template paramétrable (durée/reps/intensité).

    Le `template` désigne une fabrique dans workouts.TEMPLATES ; `params` porte
    les paramètres que le moteur adaptatif fait varier (ex. minutes, reps).
    """
    template: str
    params: Dict[str, float] = field(default_factory=dict)

    def copy(self, **param_overrides) -> "SessionSpec":
        new = dict(self.params)
        new.update(param_overrides)
        return SessionSpec(self.template, new)


@dataclass
class PlannedWeek:
    """Une semaine du programme : intention par rôle + méta."""
    index: int
    phase: str
    deload: bool
    note: str
    sessions: Dict[str, SessionSpec]  # role -> SessionSpec

    def copy(self) -> "PlannedWeek":
        return replace(
            self,
            sessions={r: s.copy() for r, s in self.sessions.items()},
        )


@dataclass
class Activity:
    """Une activité Strava normalisée (course uniquement pour nous)."""
    date: str            # ISO "YYYY-MM-DD"
    moving_time_s: int
    distance_m: float
    elevation_m: float = 0.0
    sport: str = "Run"
    avg_hr: Optional[float] = None
    name: str = ""

    @property
    def hours(self) -> float:
        return self.moving_time_s / 3600.0


@dataclass
class WeekSummary:
    """Synthèse d'une semaine réalisée, comparée au prévu."""
    n_runs: int
    total_time_s: int
    total_dist_m: float
    total_elev_m: float
    longest_run_s: int
    planned_time_s: int
    acute_hours: Optional[float] = None    # charge 7 j
    chronic_hours: Optional[float] = None  # charge moyenne hebdo sur 28 j

    @property
    def actual_hours(self) -> float:
        return self.total_time_s / 3600.0

    @property
    def planned_hours(self) -> float:
        return self.planned_time_s / 3600.0

    @property
    def adherence(self) -> float:
        """Ratio réalisé/prévu (en temps). 1.0 = pile la charge prévue."""
        if self.planned_time_s <= 0:
            return 1.0
        return self.total_time_s / self.planned_time_s

    @property
    def acwr(self) -> Optional[float]:
        """Acute:Chronic Workload Ratio. Zone sûre ~0.8-1.3."""
        if not self.chronic_hours or self.chronic_hours <= 0:
            return None
        acute = self.acute_hours if self.acute_hours is not None else self.actual_hours
        return acute / self.chronic_hours


@dataclass
class Adjustment:
    """Trace d'un ajustement appliqué par le moteur (pour le rapport)."""
    role: str
    before: str
    after: str
    reason: str
