# Backyard Ultra — moteur d'entraînement adaptatif 🏃‍♂️🌲

Un moteur qui **génère chaque semaine des séances de course structurées**,
**adaptées à l'activité Strava réelle** de la semaine précédente, tout en
respectant une **structure de programme périodisée**. Il produit des fichiers
**`.FIT` importables sur Garmin**, un **dashboard visuel envoyé par email**
avec un **debrief de coach**, et peut **planifier les séances directement dans
Garmin Connect** via l'API officielle.

Tout est **paramétrable** (objectif, date de course, durée, volume, jours par
semaine, allures) par un simple fichier de profil, et le tout peut tourner en
**automatique une fois par semaine**.

Le projet est **autonome** : aucun service externe requis. L'autorisation Strava
et Garmin se fait par des commandes intégrées, et **ouvrir le dépôt dans une
session Claude « démarre » le projet automatiquement** (voir plus bas).

---

## Sommaire

- [Aperçu](#aperçu)
- [Démarrage rapide](#démarrage-rapide)
- [Le profil athlète (configuration + mémoire)](#le-profil-athlète-configuration--mémoire)
- [Commandes](#commandes)
- [Comment fonctionne l'adaptation](#comment-fonctionne-ladaptation)
- [Le dashboard & le debrief de coach](#le-dashboard--le-debrief-de-coach)
- [Livraison : email et/ou Garmin](#livraison--email-etou-garmin)
- [Automatisation hebdomadaire](#automatisation-hebdomadaire)
- [Structure du dépôt](#structure-du-dépôt)
- [Tests](#tests)
- [Variables d'environnement](#variables-denvironnement)
- [Avertissement](#avertissement)

---

## Aperçu

À chaque semaine, le moteur :

1. **Lit l'activité Strava** de la semaine qui vient de se terminer.
2. **Choisit la semaine à venir** dans le programme périodisé (la « ligne de
   conduite ») et **module** ses paramètres selon ce qui a réellement été fait —
   sans jamais changer le *type* ni le *rôle* d'une séance.
3. **Génère les séances `.FIT`** structurées (échauffement, intervalles,
   répétitions, cibles d'allure, retour au calme).
4. **Construit un dashboard visuel** (progression prévu vs réalisé, adhérence,
   tendances) avec un **debrief d'entraîneur** exploitable.
5. **Livre** : email (dashboard + `.FIT` en pièces jointes) et/ou planification
   directe dans Garmin Connect.

Le programme couvre une préparation type de **34 semaines** (Fondation →
Force-endurance → Spécifique → Pic → Affûtage), automatiquement **compressée**
si le temps disponible est plus court.

**Sans dépendances externes** : Python standard uniquement (la bibliothèque
`fitdecode` sert seulement à *vérifier* les `.FIT` dans les tests).

---

## Démarrage rapide

```bash
cd training

# 1) Générer la semaine courante à partir d'un export d'activités (hors-ligne)
python3 generate.py week --activities tests/fixtures/last_week_sample.json --today 2026-09-14

# 2) Regarder le résultat
#    -> workouts/semaine_XX/ : les .FIT + rapport.md + rapport.json + dashboard.html

# 3) Générer toute la bibliothèque de séances "nominales" (import Garmin manuel)
python3 generate.py library

# 4) Voir le profil effectif (objectif, date, durée, volume, allures)
python3 generate.py config
```

Pour un usage réel, on remplace `--activities <fichier>` par `--live` (lecture
Strava en direct) une fois les accès configurés (voir plus bas).

### Ouverture dans une session Claude (auto-lancement)

Un **hook `SessionStart`** ([`.claude/hooks/session-start.sh`](.claude/hooks/session-start.sh))
fait que **le projet démarre tout seul** à l'ouverture du dépôt dans une session
Claude : il prépare l'environnement (parseur `.FIT` pour les tests) et affiche un
**briefing** — profil effectif, durée du plan, état des accès (Strava/Gmail/Garmin)
et les prochaines actions. Aucune configuration n'est nécessaire ; le hook
s'exécute automatiquement.

**Onboarding au premier démarrage** : tant que le profil n'a pas été personnalisé
(`"onboarded": false`), le hook demande à l'assistant de **poser quelques questions**
(objectif, date de course, jours par semaine, volume hebdo actuel) puis d'écrire
lui-même `athlete.json` via `generate.py onboard` — **aucun fichier à éditer à la
main**. L'onboarding ne se déclenche qu'en session interactive, jamais dans un run
automatique planifié.

### Obtenir un token Strava (une fois, sans service externe)

```bash
python3 generate.py strava-auth-url                  # ouvre l'URL, autorise
python3 generate.py strava-auth-exchange --code <CODE>
# -> stocker le refresh_token renvoyé dans STRAVA_REFRESH_TOKEN
```

---

## Le profil athlète (configuration + mémoire)

Tout le plan est piloté par **un seul fichier** : [`training/athlete.json`](training/athlete.json).
Parce qu'il est versionné dans le dépôt, **toute exécution le lit** — y compris
les exécutions automatiques planifiées. C'est la **mémoire durable** du moteur.

```jsonc
{
  "objective": "18-24 yards",   // objectif visé (informe le pic)
  "race_date": "2027-04-24",    // jour de course → cale la fin du plan
  "plan_start": null,           // date de début → durée = début → course
  "plan_weeks": null,           // ou fixer directement le nombre de semaines
  "days_per_week": 4,           // 3 → retire le jour "facile" ; 4 → 4 rôles
  "start_volume_h": null,       // volume hebdo de départ (h) → échelle le plan
  "peak_volume_h": null,        // (réservé)
  "paces": {                    // allures cibles des séances (min/km)
    "easy": "6:15", "long": "6:40", "steady": "5:35",
    "tempo": "5:00", "cruise": "4:55", "yard": "6:30", "recovery": "6:45"
  }
}
```

Ce que chaque paramètre pilote :

| Paramètre | Effet |
|---|---|
| `race_date` | La dernière semaine du plan tombe la semaine de course. |
| `plan_start` / `plan_weeks` | **Durée du plan variable** : la périodisation est **compressée** pour tenir dans le temps disponible (phases préservées, affûtage intact). |
| `days_per_week` | 3 jours → qualité + sortie longue + back-to-back ; 4 → + un jour facile. |
| `start_volume_h` | **Échelle de volume** : la semaine 1 colle au volume réel de départ, le reste monte proportionnellement. |
| `cross_training_weight` | Poids d'une heure de vélo/cross-training dans la **charge aérobie** (défaut 0,5). Compte pour l'ACWR et l'anti-régression, jamais dans le volume course prescrit. |
| `paces` | Cibles d'allure encodées dans les `.FIT`. |

Précédence : **variables d'environnement** > `athlete.json` > valeurs par défaut.
On édite le fichier, on l'inspecte avec `python3 generate.py config`, et la
prochaine génération en tient compte.

Rôles hebdomadaires (structure fixe) : **Mardi** qualité · **Jeudi** facile ·
**Samedi** sortie longue · **Dimanche** back-to-back (sur jambes fatiguées).

---

## Commandes

Toutes les commandes se lancent depuis `training/` : `python3 generate.py <cmd>`.

| Commande | Rôle |
|---|---|
| `week [N]` | Génère une semaine adaptée (`.FIT` + `rapport.md/json` + `dashboard.html`). Sans `N`, la semaine courante est déduite du calendrier. |
| `send [N]` | Pipeline complet **+ envoi email**. Requiert une source (`--live`, `--activities`, ou `--dry-run`). |
| `library` | Génère toute la bibliothèque de séances nominales dans `workouts/`. |
| `plan` | Régénère la vue d'ensemble du plan (`plan.md` + `plan.html`). |
| `config` | Affiche le profil effectif et les valeurs dérivées (durée, semaine 1, échelle…). |
| `strava-auth-url` / `strava-auth-exchange` | Autorisation Strava en deux étapes → `refresh_token` (une seule fois). |
| `garmin-auth-url` / `garmin-auth-exchange` | Autorisation Garmin **Training API** (officielle) en deux étapes (une seule fois). |
| `garmin-connect-login` | Login Garmin **Connect** (voie non-officielle) : stocke les jetons (MFA incluse) pour les runs suivants. |

Options communes à `week`/`send` :

- `--live` — lit Strava en direct (variables d'environnement requises).
- `--activities <fichier.json>` — lit un export/fixture d'activités (hors-ligne).
- `--today YYYY-MM-DD` — date de référence (tests/simulation).
- `--push-garmin` — planifie via la **Training API officielle** **si configurée** (sinon ignoré).
- `--push-connect` — planifie au **calendrier Garmin Connect** (voie non-officielle) **si configuré** (sinon ignoré).
- `--dry-run` (sur `send`) — génère tout **sans** envoyer l'email.

Exemples :

```bash
python3 generate.py send --live                 # semaine courante, envoi email
python3 generate.py send --live --push-garmin   # + planification Garmin
python3 generate.py send --live 12              # forcer la semaine 12
python3 generate.py week 22 --activities tests/fixtures/last_week_sample.json --today 2026-11-01
```

---

## Comment fonctionne l'adaptation

Le moteur mesure l'**adhérence** = temps réalisé / temps prescrit de la semaine
précédente, puis choisit une **bande** :

| Situation | Bande | Effet |
|---|---|---|
| Semaine de décharge programmée | `deload` | **Intouchable** (récupération). |
| Adhérence < 60 % | `reprise` | Régression (× 0,75). |
| 60 – 85 % | `consolide` | On tempère (× 0,90). |
| 85 – 115 % | `nominal` | On suit le programme. |
| > 115 % | `vigilance` | Léger frein (× 0,95), pas de sur-dose. |
| 0 sortie alors qu'il y avait du prévu | `verifier` | On tient le nominal + on **signale** (probable trou de synchro, pas une vraie régression). |
| Aucune donnée fournie | `nominal` | Plan **non adapté**, signalé comme tel. |

### Charge multi-sport (course **et** vélo/cross-training)

Le moteur raisonne sur **deux charges en parallèle** :

- **Volume course** (spécifique) → pilote les séances prescrites et le **plafond
  de la sortie longue**. Reste **course seule** : une grosse caisse vélo n'autorise
  pas un saut de volume *course* (l'impact au sol est spécifique et se construit
  en courant).
- **Charge aérobie totale** = course + cross-training pondéré (vélo, rameur, ski…
  au poids `cross_training_weight`, défaut **0,5**). Elle nourrit l'**ACWR de
  fatigue** et un **garde-fou anti-régression** : si tu as entretenu la base à
  vélo, le plan **ne te fait pas régresser** sous prétexte d'une semaine à faible
  kilométrage course — mais un gros bloc vélo fait bien **monter l'ACWR** (et donc
  déclencher le frein de fatigue si besoin).

Garde-fous, toujours actifs (hors décharge) :

- **Plafond de la sortie longue** : elle ne bondit jamais au-delà d'un facteur
  dépendant de la phase (plus permissif en Spécifique/Pic pour les grosses
  simulations) par rapport à la plus longue sortie réellement bouclée.
- **ACWR** (charge aiguë 7 j / chronique 3 sem., non-couplé) : au-delà de 1,5,
  frein de sécurité + qualité rétrogradée en facile ; au-delà de 1,3, prudence.
- **Structure préservée** : les rôles et types de séance ne changent pas (seule
  exception documentée : le passage qualité → facile en cas de fatigue marquée).

L'adhérence est comparée à la **prescription réellement adaptée** de la semaine
précédente (recalculée sans état), ce qui évite un tempérage perpétuel après une
seule semaine en creux.

---

## Le dashboard & le debrief de coach

Chaque génération produit un `dashboard.html` **autonome** (thème clair, lisible
en email) : position dans le plan, compte à rebours, tuiles d'indicateurs
(volume, adhérence, ACWR), courbe **prévu vs réalisé** avec bandes de phase, et
un **debrief d'entraîneur** :

- **Verdict** de la semaine en une phrase.
- **Constats chiffrés** : volume vs prévu, poids de la sortie longue,
  distribution d'intensité (part courue plus vite que l'allure soutenue),
  régularité des allures faciles, dénivelé, **monotonie d'entraînement** (indice
  de Foster), **efficacité aérobie** (allure/FC).
- **Tendances sur ~4 semaines** : volume, sortie longue, fréquence, et
  **efficacité aérobie** avec sa tendance (« à FC égale, plus vite » = forme qui
  monte) lorsque la fréquence cardiaque est disponible.
- **Recommandations** priorisées et concrètes pour la semaine suivante.

Le même contenu est disponible en `rapport.md` (lisible) et `rapport.json`
(exploitable par un programme).

---

## Livraison : email et/ou Garmin

**Email (Gmail, SMTP)** — le mode par défaut, universel :
le dashboard est le corps du message, les `.FIT` et le dashboard sont en pièces
jointes.

> ⚠️ **Important — les `.FIT` de séance ne s'importent PAS dans Garmin Connect.**
> Connect (web et app) n'accepte l'upload de fichiers que pour des *activités
> terminées*, pas pour des *séances planifiées*. Pour charger un `.FIT` de
> séance, il faut **brancher la montre en USB et copier le fichier dans le
> dossier `GARMIN/NEWFILES`** : la séance apparaît alors dans **Entraînement ▸
> Mes séances** — dans la **bibliothèque uniquement**. Elle n'est **pas planifiée
> à une date** et ne s'affiche donc pas comme *séance du jour* ; il faut la
> sélectionner à la main. Pour une planification à date fixe, utiliser une des
> deux voies API ci-dessous.

**Garmin Connect (voie non-officielle)** — optionnel, `--push-connect` :
la séance est **uploadée puis planifiée au calendrier** Garmin Connect ; elle se
synchronise sur la montre et **apparaît comme séance du jour à la bonne date**.
C'est la voie qui marche *tout de suite* (login compte Garmin, pas de validation
Garmin), au prix d'une **dépendance externe** (`pip install garminconnect`) et
d'une API rétro-ingénierée qui peut casser si Garmin change son service.

```bash
pip install garminconnect                    # dépendance optionnelle
export GARMIN_EMAIL=…  GARMIN_PASSWORD=…      # compte Garmin Connect
python3 generate.py garmin-connect-login      # login une fois (stocke les jetons)
python3 generate.py send --live --push-connect
```

Pour l'**automatique en cloud** (session éphémère, sans re-login ni MFA), récupère
le jeton de session et stocke-le en variable d'environnement :

```bash
python3 generate.py garmin-connect-token      # imprime le jeton base64
# -> colle-le dans GARMIN_TOKENS_BASE64 (secret) ; la Routine se connecte seule
```

**Garmin (API officielle Training API)** — optionnel, `--push-garmin` :
même résultat (création + planification), par la voie *propre*. Nécessite un
compte **Garmin Developer Program** (validation manuelle par Garmin) et une
autorisation OAuth unique :

```bash
python3 generate.py garmin-auth-url         # ouvre l'URL, autorise
python3 generate.py garmin-auth-exchange --code <CODE> --verifier <VERIFIER>
# -> stocker le refresh_token renvoyé dans GARMIN_REFRESH_TOKEN
```

> Les URLs OAuth/Training API et le schéma JSON des workouts sont centralisés,
> avec des repères « RÉCONCILIATION », dans `engine/garmin.py`,
> `engine/garmin_workout.py` (Training API) et `engine/garmin_connect.py`
> (Connect non-officiel) — surchargeables sans modifier le reste du code.

Si les identifiants ne sont pas définis (ou la lib absente), `--push-garmin` /
`--push-connect` sont **ignorés proprement** et la livraison email/`.FIT` reste
en place. Les deux drapeaux sont cumulables et indépendants.

---

## Automatisation hebdomadaire

Le pipeline est conçu pour tourner **une fois par semaine** de façon autonome :
récupérer Strava, adapter, générer, débriefer, envoyer (et planifier sur Garmin
si configuré). La procédure détaillée, les prérequis et le déroulé exact sont
dans **[`training/RUNBOOK.md`](training/RUNBOOK.md)**.

En pratique, un seul appel suffit :

```bash
python3 generate.py send --live --push-garmin
```

La semaine cible est déduite du calendrier : une exécution le dimanche soir
prescrit la **semaine à venir** et évalue la **semaine qui vient de se terminer**.

---

## Structure du dépôt

```
training/
  generate.py         # CLI (week / send / library / plan / config / garmin-auth)
  athlete.json        # profil athlète = mémoire (objectif, date, durée, volume, allures)
  engine/
    config.py         # chargement du profil (+ overrides env)
    program.py        # programme périodisé + durée variable (source unique de structure)
    workouts.py       # templates de séances paramétrables + allures
    adapt.py          # moteur adaptatif (bandes + garde-fous)
    coach.py          # debrief d'entraîneur (constats, tendances, recommandations)
    strava.py         # client Strava (refresh token, activités, synthèses)
    dashboard.py      # dashboard hebdo (HTML autonome)
    deliver.py        # envoi email Gmail (SMTP, pièces jointes)
    garmin.py         # client Garmin Training API officielle (OAuth : create/schedule)
    garmin_workout.py # traducteur séance -> JSON Training API
    garmin_connect.py # client Garmin Connect non-officiel (upload + planif calendrier)
    report.py         # rapports md/json + génération de la vue plan
    fit_encoder.py    # encodeur FIT sans dépendance
    models.py         # types de données
  tests/              # tests unitaires
  workouts/           # séances .FIT générées
  plan.md / plan.html # vue d'ensemble du programme
  README.md           # détails moteur
  RUNBOOK.md          # procédure d'automatisation hebdomadaire

.claude/
  settings.json       # enregistre le hook SessionStart
  hooks/session-start.sh  # briefing + préparation à l'ouverture d'une session
  commands/backlog.md # commande /backlog (suivi des issues)
CLAUDE.md             # guide projet + politique de suivi
README.md             # ce guide
```

Le suivi des développements en cours se fait en **issues GitHub** (label
`pending-dev`) — voir [`CLAUDE.md`](CLAUDE.md).

---

## Tests

```bash
cd training && python3 -m unittest discover -s tests
```

Les tests couvrent l'encodage `.FIT` (parsé par `fitdecode` si installé), la
logique d'adaptation et ses garde-fous, l'ancrage calendaire, la compression de
plan, le debrief de coach (tendances/efficacité), la traduction Garmin, et la
génération du dashboard.

---

## Variables d'environnement

Configuration du plan (surchargent `athlete.json`) :
`RACE_DATE`, `PLAN_START`, `PLAN_WEEKS`, `DAYS_PER_WEEK`, `START_VOLUME_H`,
`CROSS_TRAINING_WEIGHT` (poids du cross-training dans la charge aérobie, défaut 0,5),
`PROGRAM_START`, `ATHLETE_CONFIG` (chemin d'un autre profil).

Accès Strava (lecture des activités) :
`STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, `STRAVA_REFRESH_TOKEN`.

Envoi email (Gmail) :
`GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `MAIL_TO`.

Push Garmin — Training API officielle (optionnel) :
`GARMIN_CONSUMER_KEY`, `GARMIN_CONSUMER_SECRET`, `GARMIN_REFRESH_TOKEN`,
`GARMIN_REDIRECT_URI`, `GARMIN_SCOPE`.

Push Garmin — Connect non-officiel (optionnel, `--push-connect`, requiert
`pip install garminconnect`) :
`GARMIN_EMAIL`, `GARMIN_PASSWORD`, `GARMIN_TOKENS_BASE64` *(recommandé pour l'auto
cloud : jeton de session, évite le re-login)*, `GARMIN_TOKENSTORE` *(option, défaut `~/.garminconnect`)*.

Les secrets ne sont **jamais** committés : ils vivent dans l'environnement
d'exécution.

---

## Avertissement

Ce projet fournit un **plan d'entraînement indicatif**, ce n'est pas un avis
médical. Adaptez-le à votre forme, à votre fatigue et à d'éventuelles blessures,
et faites valider votre préparation par un professionnel de santé si nécessaire.
