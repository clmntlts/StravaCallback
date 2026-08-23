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
   jointes) :
   ```bash
   python3 generate.py send --live
   ```
5. **Confirmer** : l'email indique le destinataire et le nombre de pièces jointes.
   En cas d'échec (identifiants manquants, Strava indispo), le signaler clairement
   plutôt que d'échouer en silence.

> La semaine est déduite du calendrier (`PROGRAM_START` → semaine courante). Pour
> forcer une semaine : `python3 generate.py send --live 12`.

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

- Jeton Strava : créer une app sur https://www.strava.com/settings/api, autoriser
  le scope `activity:read`, échanger le code contre un `refresh_token`. (Le callback
  OAuth du repo, `api/sendCode.js`, sert déjà à récupérer le code.)
- Mot de passe d'application Gmail : https://myaccount.google.com/apppasswords

Sans ces variables, `generate.py send --live` s'arrête avec un message explicite.
Pour tester hors-ligne : `python3 generate.py send --activities tests/fixtures/last_week_sample.json --today 2026-09-14 --dry-run`.

## Alternative connecteurs

Si les connecteurs **Strava** et **Gmail** sont activés pour les sessions de la
Routine, Claude peut lire Strava et envoyer l'email via ces connecteurs au runtime,
sans les variables d'environnement ci-dessus. Le chemin par variables d'env reste
le plus robuste pour l'exécution planifiée.
