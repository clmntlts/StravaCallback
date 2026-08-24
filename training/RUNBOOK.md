# Runbook — automatisation hebdomadaire (Claude = le moteur)

Chaque **dimanche ~18h (Europe/Paris)**, une Routine réveille une session Claude
fraîche qui exécute ce flux. Claude n'est pas un simple lanceur de script : il est
**le coach**. Le code garantit le déterministe (récup Strava, encodage FIT, envoi) ;
Claude apporte le **jugement** hebdomadaire dans les limites de la ligne de conduite
(`engine/program.py`) et des garde-fous (`engine/adapt.py`).

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
| `GARMIN_CONSUMER_KEY` | *(push Garmin)* client id de l'app Garmin (Developer Program) |
| `GARMIN_CONSUMER_SECRET` | *(push Garmin)* client secret |
| `GARMIN_REFRESH_TOKEN` | *(push Garmin)* token utilisateur (après consentement, voir ci-dessous) |
| `GARMIN_REDIRECT_URI` | *(auth Garmin)* URL de redirection déclarée sur l'app |
| `GARMIN_SCOPE` | *(option)* scopes OAuth demandés |

- Jeton Strava : créer une app sur https://www.strava.com/settings/api, puis
  utiliser les commandes intégrées (aucun service externe requis) :
  `python3 generate.py strava-auth-url` → autoriser → `strava-auth-exchange --code <CODE>`
  → stocker le `refresh_token` dans `STRAVA_REFRESH_TOKEN`.
- Mot de passe d'application Gmail : https://myaccount.google.com/apppasswords

Sans ces variables, `generate.py send --live` s'arrête avec un message explicite.
Pour tester hors-ligne : `python3 generate.py send --activities tests/fixtures/last_week_sample.json --today 2026-09-14 --dry-run`.

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

## Alternative connecteurs

Si les connecteurs **Strava** et **Gmail** sont activés pour les sessions de la
Routine, Claude peut lire Strava et envoyer l'email via ces connecteurs au runtime,
sans les variables d'environnement ci-dessus. Le chemin par variables d'env reste
le plus robuste pour l'exécution planifiée.
