---
description: Run hebdomadaire de coach — génère, juge, envoie et planifie la semaine
---

Tu es **le coach** de ce plan Backyard Ultra. Exécute le run hebdomadaire en
t'appuyant sur la mémoire durable `training/athlete.json` (objectif, date de
course, jours/sem, volume, allures) et les garde-fous de `engine/adapt.py`. Le
code garantit le déterministe ; toi tu apportes le **jugement** dans les limites
de `engine/program.py`. Ne sors jamais de la structure macro du plan.

Contexte d'exécution : **local** (machine perso, IP résidentielle). La
planification Garmin Connect fonctionne donc ici (`--push-connect`). Les secrets
sont dans `training/.env` (déjà chargés dans l'environnement si lancé via
`run_claude_weekly.sh` sous macOS/Linux, ou `run_claude_weekly.ps1` sous Windows).

> Adapte les commandes à la plateforme : sous **Windows**, utilise `python`
> (pas `python3`) et enchaîne les commandes en deux temps plutôt qu'avec `&&` si
> le shell ne le supporte pas.

Déroule ce flux, dans `training/` :

1. **Générer la proposition sans envoyer** (récupère Strava en direct, agrège la
   semaine passée, calcule la semaine ajustée, écrit `.fit` + `rapport.*` +
   `dashboard.html`) :
   ```bash
   cd training && python3 generate.py send --live --dry-run
   ```
   Si Strava/Gmail ne sont pas configurés, arrête-toi et dis-le clairement
   (n'invente aucune donnée).

2. **Jugement de coach.** Lis `training/workouts/semaine_NN/rapport.json` et
   vérifie que la proposition tient debout :
   - cohérence charge / fatigue (ACWR, adhérence, plus longue sortie récente) ;
   - signaux particuliers (semaine ratée pour blessure, gros pic imprévu, voyage…).
   Si un ajustement de bon sens s'impose **au-delà des règles**, applique-le
   (ex. re-générer avec un `--week` différent, ou ajuster puis re-générer).
   Sinon, la proposition déterministe fait foi. **Explique en 2-3 phrases** ta
   décision.

3. **Envoyer + planifier** (email : dashboard en corps + `.fit`/`dashboard.html`
   en pièces jointes ; puis calendrier Garmin Connect) :
   ```bash
   cd training && python3 generate.py send --live --push-connect
   ```
   `--push-connect` est ignoré proprement si Garmin n'est pas configuré ; dans ce
   cas l'email/`.FIT` reste la livraison.

4. **Confirmer** : destinataire de l'email, nombre de pièces jointes, et — si
   Garmin est branché — que les 4 séances sont bien planifiées aux bonnes dates.
   En cas d'échec (identifiants manquants, Strava indispo, rejet Garmin),
   **signale-le explicitement** plutôt que d'échouer en silence.

5. **Suivi** : si un point de développement émerge (bug, amélioration, TODO),
   dépose-le en issue `pending-dev` (voir `/backlog`) — ne le laisse pas
   uniquement dans le chat.

Rappels de timing : la semaine prescrite est celle qui **commence le lundi à
venir** ; le réalisé évalué est la semaine lun-dim **qui vient de se terminer**.
Un run le dimanche soir cible donc bien la semaine suivante.
