"""Source unique de la date « aujourd'hui » du moteur (#26).

Les activités Strava sont rangées par leur date **locale** (`start_date_local`,
cf. `strava._to_activity`), et l'automatisation (Routine hebdo, webapp) tourne
sur la machine de l'athlète — dont l'heure locale coïncide donc avec cette date
locale. Utiliser un « aujourd'hui » en UTC ailleurs (comme le faisaient les
défauts de `strava.py`) créait un décalage d'un jour aux frontières de semaine
(nuit du dimanche au lundi) : le plan pouvait pointer la semaine suivante alors
que les activités étaient encore rangées dans la semaine courante, ou l'inverse.

Toutes les fonctions à paramètre `today` doivent défaulter sur `clock.today()`,
jamais sur `date.today()` ni `datetime.now(timezone.utc).date()` en direct, pour
garder une référence unique et cohérente. `--today` (CLI) et le paramètre
`today=` restent prioritaires, pour la reproductibilité des tests et le rejeu
d'une date précise.

NB : les fenêtres de récupération Strava (`fetch_activities`, bornes `after`/
`before`) continuent d'utiliser `datetime.now(timezone.utc)` — ce sont des
instants aware pour l'API, pas la date calendaire « aujourd'hui ».
"""

from __future__ import annotations

from datetime import date


def today() -> date:
    """Date locale du jour — référence unique par défaut du moteur."""
    return date.today()
