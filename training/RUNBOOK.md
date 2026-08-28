# Runbook — automatisation hebdomadaire

Deux façons d'exécuter le run hebdo, selon le besoin :

- **🖥️ Local (recommandé pour le pipeline complet, Garmin inclus)** — un simple
  `cron` sur **ta machine** (IP résidentielle) lance `run_weekly.sh`. C'est le
  seul chemin où la **planification Garmin Connect fonctionne de façon fiable** :
  depuis une IP datacenter (cloud), Garmin bloque le login (429/403) et le
  rafraîchissement des jetons échoue. Voir **« Exécution locale »** ci-dessous.
- **☁️ Routine cloud (Claude = le coach)** — chaque dimanche, une Routine réveille
  une session Claude fraîche qui exécute le flux et **apporte le jugement** de
  coach. Idéal pour l'email + les `.FIT`, mais **la planification Garmin n'y est
  pas fiable** (voir issue #14). Détaillé dans **« Flux de la Routine »**.

Dans les deux cas, le code garantit le déterministe (récup Strava, encodage FIT,
envoi) ; la ligne de conduite (`engine/program.py`) et les garde-fous
(`engine/adapt.py`) bornent l'adaptation.

## Exécution locale (recommandé) — cron sur ta machine

Sur une machine à toi, tout se simplifie : le dossier de jetons Garnin
`~/.garminconnect` **persiste** entre les runs, donc après **un** login tu n'y
touches plus (pas de `GARMIN_TOKENS_BASE64`, pas de MFA à répéter), et le refresh
des jetons (~1 an) fonctionne.

> ⚠️ **IP résidentielle requise** pour la partie Garmin. Un VPS cloud a une IP
> datacenter → il risque le même blocage Garmin qu'en Routine cloud. Préfère un
> Raspberry Pi / NAS / mini-PC allumé chez toi (ou ton laptop s'il est allumé à
> l'heure du cron).

**Mise en place (une fois) :**

```bash
# 1) dépendance Garmin (optionnelle : seulement pour --push-connect)
pip install "garminconnect>=0.3,<0.4"

# 2) secrets locaux (jamais committés : training/.env est gitignoré)
cp training/.env.example training/.env
$EDITOR training/.env                       # renseigne Strava / Gmail / Garmin

# 3) login Garmin Connect UNE fois (franchit la MFA, remplit ~/.garminconnect)
python3 training/generate.py garmin-connect-login

# 4) test à blanc (génère, n'envoie rien)
./training/run_weekly.sh --dry-run
```

**Cron hebdomadaire** (dimanche 19h, heure locale de la machine) :

```cron
0 19 * * 0  /chemin/vers/StravaCallback/training/run_weekly.sh >> /chemin/vers/StravaCallback/training/logs/cron.out 2>&1
```

`run_weekly.sh` charge `training/.env`, ajoute `--push-connect` automatiquement si
des identifiants Garmin sont présents, exécute `generate.py send --live`, et
journalise dans `training/logs/`. Les arguments passés au script sont transmis à
`send` (`./training/run_weekly.sh --dry-run`, `./training/run_weekly.sh 12`).

> **Deux variantes de routine locale :**
> - `training/run_weekly.sh` → **déterministe pur** (pas de Claude). L'engine
>   adapte via `adapt.py` et envoie. Simple, 100 % autonome.
> - `run_claude_weekly.sh` (racine) → **Claude comme coach** (ci-dessous). Garde
>   le jugement hebdo en plus du déterministe.

### Variante : Claude comme coach, en local (headless)

Pour **garder Claude dans la boucle** tout en profitant de l'IP résidentielle,
on planifie le **CLI Claude Code local** (et non la Routine cloud du produit, qui
tourne sur IP datacenter → Garmin bloqué). `run_claude_weekly.sh` lance Claude en
mode headless sur la commande `/weekly` : il génère, **juge** la proposition
(cohérence charge/fatigue, signaux particuliers), envoie l'email et planifie sur
Garmin, puis dépose d'éventuelles suites en issues `pending-dev`.

**Mise en place (une fois) :**

```bash
# Claude Code installé et authentifié sur la machine
claude login                                  # (ou export ANTHROPIC_API_KEY=…)
# secrets + login Garmin déjà faits (voir « Exécution locale » ci-dessus)
./run_claude_weekly.sh                         # test manuel du run headless
```

**Cron hebdomadaire :**

```cron
0 19 * * 0  /chemin/vers/StravaCallback/run_claude_weekly.sh >> /chemin/vers/StravaCallback/training/logs/claude-cron.out 2>&1
```

> ⚠️ Le wrapper lance Claude avec `--dangerously-skip-permissions` (aucun prompt
> en run non-surveillé) : à n'utiliser que sur **ta** machine de confiance.
> Posture plus stricte via une allowlist : `export CLAUDE_PERM='--allowedTools Bash Read Edit'`
> avant l'appel. Vérifie les drapeaux disponibles avec `claude --help`.

> `run_claude_weekly.sh` (bash) est pour **macOS/Linux**. Sous **Windows**, utilise
> `run_claude_weekly.ps1` (PowerShell) + le Planificateur de tâches — voir ci-dessous.

### Windows 11 — Planificateur de tâches (rattrapage au réveil)

Sous Windows, le wrapper est **`run_claude_weekly.ps1`** (racine) et le minuteur est
le **Planificateur de tâches**. L'option clé **« Exécuter dès que possible après
un démarrage planifié manqué »** (`StartWhenAvailable`) donne exactement le
rattrapage voulu : si le PC était éteint/en veille à l'heure fixe, la tâche part
**au prochain allumage**. Le wrapper contient en plus une **garde « une fois par
semaine »** (fichier `training/logs/.last-week-run`) : même si le PC se réveille
plusieurs fois, le run n'a lieu qu'une fois par semaine ISO.

**Mise en place (une fois) :**

```powershell
# 1) Claude Code installé + authentifié, secrets + login Garmin faits
claude login
Copy-Item training\.env.example training\.env      # puis renseigne-le
python training\generate.py garmin-connect-login    # login Garmin (MFA), tokenstore persistant

# 2) test manuel du run headless
.\run_claude_weekly.ps1 -Force

# 3) enregistrer la tâche planifiée (dimanche 19h, rattrapage au réveil)
$root   = "C:\chemin\vers\StravaCallback"           # adapte le chemin
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
            -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$root\run_claude_weekly.ps1`""
$trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 7pm
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'StravaBackyard-Weekly' -Action $action `
            -Trigger $trigger -Settings $settings `
            -Description 'Run hebdo coach Backyard Ultra (Claude local)'
```

- `-StartWhenAvailable` → rattrape un créneau manqué (PC éteint) au prochain
  démarrage. `-WakeToRun` → réveille depuis la **veille** (pas depuis l'arrêt
  complet) pour tenir l'heure fixe quand c'est possible.
- La tâche s'exécute sous **ton compte** ; coche « Exécuter même si l'utilisateur
  n'est pas connecté » dans les propriétés de la tâche si tu veux qu'elle tourne
  sans session ouverte (elle demandera ton mot de passe Windows).
- Logs dans `training\logs\claude-weekly-*.log`. Relancer à la main :
  `.\run_claude_weekly.ps1 -Force`.

**Onboarding** (personnaliser `training/athlete.json`, la mémoire durable) : c'est
un **one-shot**, indépendant de la routine. Fais-le une fois en interactif — ouvre
une session Claude Code locale (elle te posera les questions via le hook de
démarrage) ou lance directement :

```bash
python3 training/generate.py onboard --objective "18-24 yards" --race-date 2027-04-24 \
  --days 4 --start-volume <H> --longest-run <MIN> --cross-weight 0.5 \
  --ref-distance 10k --ref-time 44:00
git add training/athlete.json && git commit -m "Onboarding athlète"
```

`athlete.json` est versionné : une fois rempli, **tous** les runs (locaux comme
interactifs) le relisent depuis le repo. La routine hebdo, elle, ne refait jamais
l'onboarding.

## Flux de la Routine

1. **Se placer dans le repo** et récupérer la dernière version :
   ```bash
   cd training && git pull --ff-only || true
   ```
2. **Générer la recommandation de la semaine (sans envoyer)** — récupère Strava en
   direct, agrège la semaine passée, calcule la semaine ajustée, écrit les `.fit`,
   le `rapport.md/json` et le `dashboard.html` :
   ```bash
   python3 generate.py send --live --dry-run
   ```
3. **Jugement de coach.** Lire `workouts/semaine_NN/rapport.json` + les données
   Strava. Vérifier que la proposition tient debout :
   - cohérence charge / fatigue (ACWR, adhérence, plus longue sortie) ;
   - signaux particuliers (semaine ratée pour blessure, gros pic imprévu, etc.).
   Si un ajustement de bon sens s'impose **au-delà des règles**, l'appliquer (ex.
   régénérer avec un `--week` différent, ou ajuster puis re-générer). Sinon, la
   proposition déterministe fait foi. Ne jamais sortir de la structure macro.
4. **Envoyer** l'email (dashboard en corps + `.fit` et `dashboard.html` en pièces
   jointes) et **planifier sur Garmin si configuré** :
   ```bash
   python3 generate.py send --live --push-garmin
   ```
   `--push-garmin` crée + planifie chaque séance au bon jour sur Garmin Connect
   **si** les identifiants Garmin sont définis ; sinon il est ignoré proprement
   (l'email/`.FIT` reste le mode de livraison).
5. **Confirmer** : l'email indique le destinataire et le nombre de pièces jointes.
   En cas d'échec (identifiants manquants, Strava indispo), le signaler clairement
   plutôt que d'échouer en silence.

> **Timing dimanche→lundi.** La semaine prescrite est celle qui **commence le
> lundi à venir** (`target_week_index`), et le réalisé évalué est la semaine
> lun-dim **qui vient de se terminer**. Un run le dimanche soir cible donc bien
> la semaine suivante (pas celle qui s'achève). Pour forcer une semaine :
> `python3 generate.py send --live 12`.
>
> **Rotation du refresh token Strava.** Strava peut renvoyer un nouveau
> `refresh_token` au refresh ; il n'est pas persisté (variable d'env non
> réinscriptible). Aujourd'hui Strava le laisse généralement stable ; si un run
> échoue soudainement à l'auth, régénère `STRAVA_REFRESH_TOKEN`.

## Prérequis (variables d'environnement de l'environnement d'exécution)

| Variable | Rôle |
|---|---|
| `STRAVA_CLIENT_ID` | App Strava |
| `STRAVA_CLIENT_SECRET` | App Strava |
| `STRAVA_REFRESH_TOKEN` | Jeton de rafraîchissement (accès en lecture activités) |
| `GMAIL_ADDRESS` | Adresse Gmail d'envoi |
| `GMAIL_APP_PASSWORD` | Mot de passe d'application Google (2FA requise) |
| `MAIL_TO` | Destinataire (défaut : `GMAIL_ADDRESS`) |
| `PROGRAM_START` | *(optionnel)* Lundi de la semaine 1 (`YYYY-MM-DD`) pour aligner le calendrier |
| `CROSS_TRAINING_WEIGHT` | *(optionnel)* Poids du cross-training (vélo…) dans la charge aérobie, défaut 0.5 |
| `GARMIN_CONSUMER_KEY` | *(push Garmin)* client id de l'app Garmin (Developer Program) |
| `GARMIN_CONSUMER_SECRET` | *(push Garmin)* client secret |
| `GARMIN_REFRESH_TOKEN` | *(push Garmin)* token utilisateur (après consentement, voir ci-dessous) |
| `GARMIN_REDIRECT_URI` | *(auth Garmin)* URL de redirection déclarée sur l'app |
| `GARMIN_SCOPE` | *(option)* scopes OAuth demandés |
| `GARMIN_EMAIL` | *(push Connect non-officiel)* identifiant du compte Garmin Connect |
| `GARMIN_PASSWORD` | *(push Connect non-officiel)* mot de passe du compte |
| `GARMIN_TOKENS_BASE64` | *(cloud éphémère uniquement)* jeton de session base64 (via `garmin-connect-token`). **Inutile en local** (le tokenstore persiste). Peu fiable en cloud : le refresh du jeton échoue derrière le proxy — voir issue #14. |
| `GARMIN_TOKENSTORE` | *(option)* dossier des jetons Connect (défaut `~/.garminconnect`) |

- Jeton Strava : créer une app sur https://www.strava.com/settings/api, puis
  utiliser les commandes intégrées (aucun service externe requis) :
  `python3 generate.py strava-auth-url` → autoriser → `strava-auth-exchange --code <CODE>`
  → stocker le `refresh_token` dans `STRAVA_REFRESH_TOKEN`.
- Mot de passe d'application Gmail : https://myaccount.google.com/apppasswords

Sans ces variables, `generate.py send --live` s'arrête avec un message explicite.
Pour tester hors-ligne : `python3 generate.py send --activities tests/fixtures/last_week_sample.json --today 2026-09-14 --dry-run`.

## Interface web locale (optionnelle)

Dashboard interactif dans le navigateur, en plus (pas à la place) de l'email
hebdo et de la CLI : vue du plan complet, vue semaine avec KPIs/ajustements,
téléchargement `.fit` par séance en un clic, push Garmin. **Local uniquement**
(`127.0.0.1`) — jamais hébergée publiquement, entre autres pour rester sur IP
résidentielle côté Garmin (cf. push Garmin Connect ci-dessous, et issue #14).

```bash
pip install -r training/requirements-web.txt   # Flask, seule dépendance
python3 training/generate.py serve             # http://127.0.0.1:5000
# ou : python3 training/generate.py serve --port 5050
```

N'a aucun effet sur la Routine hebdo (cron/Tâche planifiée) : deux surfaces
indépendantes sur le même moteur.

### Chat (onglet « Coach »)

Pas de clé API Anthropic séparée, pas de facturation à part : le backend
shelle out vers la CLI `claude` **déjà installée en local et authentifiée**
(mêmes conditions que la Routine hebdo, qui invoque `claude -p "/weekly"`) —
`claude login` une fois suffit, aucune variable d'environnement à ajouter.

- **Questions sur le plan** (mode par défaut une fois le profil configuré) :
  pur Q&A en lecture seule sur la semaine/le plan/le profil courants — aucun
  outil (Bash/Edit/…) n'est donné à l'agent pour ce mode.
- **Configuration du profil** (mode par défaut tant que `athlete.json` n'est
  pas encore personnalisé, ou accessible via le bouton « Configurer mon
  profil ») : reprend les questions de l'onboarding interactif
  (objectif, date de course, jours/semaine, volume, allures…) directement
  dans le chat. Une fois les réponses réunies, l'agent écrit le profil
  lui-même via `python3 training/generate.py onboard …` — même frontière de
  confiance que la Routine hebdo (`--dangerously-skip-permissions`), mais
  restreinte au seul outil Bash (aucun autre), et le prompt système le borne
  explicitement à cette unique commande. Le dashboard recharge
  automatiquement le plan dès que `athlete.json` a été réécrit.

## Push Garmin (API officielle, Training API)

Livraison directe sur la montre (calendrier Garmin Connect) au lieu de l'import
manuel des `.FIT`. Optionnel et **conditionnel** : actif seulement si les
`GARMIN_*` sont définis.

Autorisation utilisateur (une fois) :
```bash
# 1) génère l'URL de consentement + le code_verifier (requiert GARMIN_CONSUMER_KEY, GARMIN_REDIRECT_URI)
python3 generate.py garmin-auth-url
# 2) ouvre l'URL, autorise, récupère le ?code=… du redirect, puis :
python3 generate.py garmin-auth-exchange --code <CODE> --verifier <VERIFIER>
# 3) stocke le refresh_token renvoyé dans GARMIN_REFRESH_TOKEN
```
Ensuite, `--push-garmin` planifie automatiquement les 4 séances de la semaine
(mardi qualité, jeudi facile, samedi longue, dimanche B2B).

> ⚠️ Les URLs OAuth/Training API et le schéma JSON des workouts sont centralisés
> dans `engine/garmin.py` et `engine/garmin_workout.py` avec des repères
> « RÉCONCILIATION » : vérifie-les avec ta console développeur Garmin et
> surcharge via les `GARMIN_*_URL` si besoin. Le push réel n'a pas pu être testé
> sans ton compte ; le traducteur JSON, lui, est couvert par les tests.

## Push Garmin Connect (voie non-officielle, `--push-connect`)

Alternative qui **fonctionne sans validation Garmin** : elle upload la séance
**et la planifie au calendrier** Garmin Connect (donc *séance du jour* à date
fixe sur la montre). Pourquoi cette voie existe : **copier un `.FIT` sur la
montre ne fait qu'ajouter la séance à la bibliothèque, jamais à une date** — seul
le calendrier Connect donne le rappel automatique du bon jour.

Contrepartie : **dépendance externe** (`pip install garminconnect`) et **API
rétro-ingénierée** susceptible de casser si Garmin change son service. Le reste
du moteur reste *stdlib-only* (import paresseux de la lib, uniquement au login).

```bash
pip install garminconnect
export GARMIN_EMAIL=…  GARMIN_PASSWORD=…
python3 generate.py garmin-connect-login          # login + stockage des jetons, une fois
python3 generate.py send --live --push-connect    # upload + planification des 4 séances
```

### Full-auto (Routine cloud, sans machine ni MFA) : jeton en variable

> ⚠️ **Peu fiable en cloud.** Le rafraîchissement du jeton passe par un transport
> (`curl_cffi`) coupé par le proxy sortant : un jeton frais tient le temps d'un
> run, mais un jeton âgé (cas d'une Routine hebdo) déclenche un refresh qui
> échoue. Pour une planification Garmin fiable, préfère l'**exécution locale**
> ci-dessus. Détails et suivi : issue #14.

L'environnement cloud est **éphémère** : le dossier de jetons (`~/.garminconnect`)
est effacé entre les runs. Pour que la Routine se connecte **sans re-login**
(et sans MFA interactive), on stocke le **jeton de session en base64** dans une
variable d'environnement :

```bash
# 1) une fois (ici ou en local), récupère le jeton :
python3 generate.py garmin-connect-token          # imprime le base64
# 2) colle-le dans l'environnement cloud :  GARMIN_TOKENS_BASE64=<le base64>
# 3) la Routine peut désormais planifier toute seule (plus besoin d'e-mail/mdp) :
python3 generate.py send --live --push-connect
```

`login()` essaie d'abord `GARMIN_TOKENS_BASE64` (repli sur e-mail+mot de passe).
Le jeton est un **secret** (accès au compte) : ne le committe pas ; régénère-le
avec `garmin-connect-token` si Garmin invalide la session.

> ⚠️ Le schéma JSON du service `/workout-service` est dans
> `engine/garmin_connect.py`. Le traducteur est couvert par les tests ; l'upload
> réel demande ton compte Garmin.

## Alternative connecteurs

Si les connecteurs **Strava** et **Gmail** sont activés pour les sessions de la
Routine, Claude peut lire Strava et envoyer l'email via ces connecteurs au runtime,
sans les variables d'environnement ci-dessus. Le chemin par variables d'env reste
le plus robuste pour l'exécution planifiée.
