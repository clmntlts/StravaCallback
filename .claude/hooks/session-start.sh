#!/bin/bash
# Hook SessionStart : prépare l'environnement et "démarre" le projet à l'ouverture
# d'une session Claude sur ce dépôt. Idempotent, non-interactif, sans dépendance
# réseau obligatoire. Sa sortie sert de briefing (à l'utilisateur et à l'agent).
set -uo pipefail

DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
GEN="$DIR/training/generate.py"

# Parseur FIT pour la suite de tests (best-effort : les tests le skippent sinon).
python3 -c "import fitdecode" >/dev/null 2>&1 || pip install -q fitdecode >/dev/null 2>&1 || true

echo "======================================================================"
echo " Backyard Ultra — moteur d'entraînement adaptatif (prêt)"
echo "======================================================================"
python3 "$GEN" config 2>/dev/null || echo "(profil indisponible — vérifier training/athlete.json)"

echo
echo "Accès configurés (variables d'environnement) :"
check() {
  local name="$1"; shift; local ok=1 v val
  for v in "$@"; do val="${!v:-}"; [ -n "$val" ] || ok=0; done
  [ "$ok" -eq 1 ] && echo "  [x] $name" || echo "  [ ] $name (non configuré)"
}
check "Strava (lecture activités)"        STRAVA_CLIENT_ID STRAVA_CLIENT_SECRET STRAVA_REFRESH_TOKEN
check "Gmail (envoi email)"               GMAIL_ADDRESS GMAIL_APP_PASSWORD MAIL_TO
check "Garmin Training API (officielle)"  GARMIN_CONSUMER_KEY GARMIN_CONSUMER_SECRET GARMIN_REFRESH_TOKEN
check "Garmin Connect (non-officiel)"     GARMIN_EMAIL GARMIN_PASSWORD

echo
echo "Pour agir :"
echo "  - Semaine (test hors-ligne) :"
echo "      python3 training/generate.py week --activities training/tests/fixtures/last_week_sample.json --today 2026-09-14"
echo "  - Envoi hebdo (données réelles) :"
echo "      python3 training/generate.py send --live"
echo "  - Planifier au calendrier Garmin (séance du jour à date fixe) :"
echo "      pip install garminconnect ; python3 training/generate.py garmin-connect-login"
echo "      python3 training/generate.py send --live --push-connect"
echo "  - Obtenir un token Strava (une fois) :"
echo "      python3 training/generate.py strava-auth-url"
echo "  - Tests :"
echo "      (cd training && python3 -m unittest discover -s tests)"
echo "======================================================================"

# Onboarding au premier démarrage : si le profil n'est pas encore personnalisé,
# demander à l'agent de poser les questions et d'écrire athlete.json lui-même.
ONB="$( (cd "$DIR/training" && python3 -c "from engine import config; print(1 if config.ONBOARDED else 0)") 2>/dev/null || echo 1)"
if [ "${ONB:-1}" = "0" ]; then
  cat <<'ONBOARD'

>>> ONBOARDING REQUIS — profil athlète non personnalisé (athlete.json) <<<
Instruction pour Claude : si cette session est INTERACTIVE (un humain peut
répondre) ET qu'aucune tâche précise n'est déjà demandée dans ce tour, lance
l'onboarding AVANT toute autre action :
  1. Pose les questions à l'utilisateur (question à choix) : objectif (ex.
     12 / 18 / 24 yards ou "dernier debout"), date de course, jours/semaine
     (3 ou 4), et volume de course hebdo actuel (en heures).
  2. Écris ses réponses (ne lui demande pas d'éditer un fichier) :
       python3 training/generate.py onboard --objective "<obj>" --race-date <YYYY-MM-DD> --days <N> --start-volume <H>
     (options possibles : --plan-start, --plan-weeks, --peak-volume)
  3. Confirme le plan dérivé : python3 training/generate.py config
NE PAS lancer l'onboarding dans un run automatique/planifié (aucun humain) :
dans ce cas, exécute la tâche demandée et ignore ce bloc.
ONBOARD
fi
exit 0
