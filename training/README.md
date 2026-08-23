# Entraînement Backyard Ultra — moteur adaptatif 🏃‍♂️🌲

Un moteur qui **génère chaque semaine** tes séances au format **`.FIT` Garmin**,
en s'**adaptant à ce que tu as réellement fait la semaine précédente** (Strava),
tout en **respectant la structure macro** d'un programme périodisé de 34 semaines
(objectif backyard ultra, **18-24 yards**, 4 jours/semaine).

## Idée directrice

- `engine/program.py` = **la ligne de conduite** : 34 semaines, chacune décrit
  une *intention* par rôle (`quality` / `easy` / `long` / `b2b`) sous forme de
  séances **paramétrables** (durée, reps, boucles…). C'est la structure fixe.
- `engine/adapt.py` = **le moteur adaptatif** : il prend la semaine prévue + le
  réalisé Strava de la semaine passée, et **module les paramètres** — sans jamais
  changer le *type* ni le *rôle* d'une séance. La structure tient, la charge s'ajuste.

## Utilisation

```bash
cd training

# Semaine adaptée à partir d'un export d'activités (JSON, fixture ou export perso)
python3 generate.py week 9 --activities tests/fixtures/last_week_sample.json --today 2026-09-14

# Semaine adaptée en direct depuis Strava (voir variables d'env plus bas)
python3 generate.py week 9 --live

# Bibliothèque complète des séances "nominales" (import une fois dans Garmin)
python3 generate.py library

# Régénérer le plan (plan.md + plan.html) depuis le programme
python3 generate.py plan

# Pipeline hebdo complet + envoi email (dashboard + .fit en pièces jointes)
python3 generate.py send --live               # semaine courante (calendrier)
python3 generate.py send --live 12            # forcer une semaine
python3 generate.py send --activities tests/fixtures/last_week_sample.json \
        --today 2026-09-14 --dry-run          # test hors-ligne, sans envoyer

# + planifier directement sur Garmin (si GARMIN_* définis, sinon ignoré)
python3 generate.py send --live --push-garmin
```

## Automatisation hebdomadaire (Claude = le moteur)

Chaque **dimanche ~18h (Europe/Paris)**, une Routine Claude planifiée réveille une
session qui agrège la semaine Strava écoulée, décide la semaine à venir (jugement
de coach dans les limites de `program.py`/`adapt.py`), génère les `.FIT` + un
**dashboard visuel de progression**, et les **envoie par email** (Gmail).

Le déroulé exact et les variables d'environnement requises (`STRAVA_*`, `GMAIL_*`)
sont dans **[`RUNBOOK.md`](RUNBOOK.md)**.

- `engine/dashboard.py` — dashboard HTML autonome (courbe prévu vs réalisé,
  adhérence, position dans le plan, séances de la semaine, bilan N-1).
- `engine/deliver.py` — envoi SMTP Gmail (stdlib) avec pièces jointes.

`generate.py week N` écrit dans `workouts/semaine_NN/` :
- un `.fit` par séance (à importer dans Garmin Connect),
- `rapport.md` : lecture du coach + ajustements justifiés + bilan Strava,
- `rapport.json` : les mêmes données, exploitables par un bot / une automatisation.

## Règles d'adaptation

Mesure de référence : **adhérence** = temps réalisé / temps prévu (semaine N-1).

| Situation | Bande | Effet |
|---|---|---|
| Décharge programmée | `deload` | **Intouchable** (c'est déjà de la récup). |
| Adhérence < 60 % | `reprise` | Régression (× 0,75) + sortie longue plafonnée. |
| 60-85 % | `consolide` | On tempère (× 0,90) + sortie longue plafonnée. |
| 85-115 % | `nominal` | On suit le programme tel quel. |
| > 115 % | `vigilance` | Pas de sur-dose ; surveillance ACWR. |

Garde-fous supplémentaires :
- **Sortie longue** : jamais plus de **+15 %** au-delà de la plus longue sortie
  réellement bouclée la semaine passée (anti-saut de charge / anti-blessure).
- **ACWR** (charge aiguë 7 j / chronique 28 j) : > 1,5 → frein de sécurité
  (× 0,8) **et** qualité rétrogradée en facile ; > 1,3 → prudence (× 0,9).
- **Structure préservée** : les 4 rôles et les types de séance ne changent pas
  (seule exception documentée : le downgrade qualité→facile si fatigue élevée).

## Connexion Strava

Auth par variables d'environnement (jamais commitées) :

```bash
export STRAVA_CLIENT_ID=...
export STRAVA_CLIENT_SECRET=...
export STRAVA_REFRESH_TOKEN=...
```

Le client (`engine/strava.py`, stdlib pure) rafraîchit le token, liste les
activités des ~5 dernières semaines, isole la semaine calendaire précédente
et calcule volume / D+ / plus longue sortie / ACWR.

## Personnaliser les allures

`engine/workouts.py` → dictionnaire `PACES` (min/km). Les cibles d'allure des
`.FIT` en découlent. Recalibrable avec tes vraies données Strava.

## Structure

```
training/
  generate.py         # CLI (week / library / plan)
  engine/
    models.py         # types (SessionSpec, PlannedWeek, WeekSummary, Adjustment)
    program.py        # programme 34 semaines + ancrage calendaire (source unique)
    workouts.py       # templates de séances paramétrables + allures
    adapt.py          # moteur adaptatif (garde-fous)
    strava.py         # client Strava + synthèse hebdo + agrégation par semaine
    dashboard.py      # dashboard hebdo visuel (HTML autonome)
    deliver.py        # envoi email Gmail (SMTP, pièces jointes)
    garmin.py         # client Garmin (OAuth + Training API : create/schedule)
    garmin_workout.py # traducteur SessionSpec -> JSON workout Garmin
    report.py         # rapports md/json + (re)génération du plan
    fit_encoder.py    # encodeur FIT sans dépendance
  tests/              # tests unitaires (python3 -m unittest discover -s tests)
  workouts/           # séances .fit générées
  plan.md / plan.html # plan macro (vue d'ensemble)
  RUNBOOK.md          # procédure d'automatisation hebdomadaire
```

## Tests

```bash
cd training && python3 -m unittest discover -s tests -v
```

Les tests couvrent : bandes d'adaptation, garde-fous (décharge, ACWR, plafond
long), préservation de la structure, et validité des `.FIT` (parsés par la lib
de référence `fitdecode` si installée, sinon le test se skippe).

## Import Garmin

Garmin Connect (web) → Entraînement → Entraînements → **Importer** les `.fit`,
puis planifie-les sur les bons jours (ou envoie-les vers la montre).

---
*Plan indicatif, pas un avis médical. Adapte selon fatigue et blessures.*
