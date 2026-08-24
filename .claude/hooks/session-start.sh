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
check "Strava (lecture activités)" STRAVA_CLIENT_ID STRAVA_CLIENT_SECRET STRAVA_REFRESH_TOKEN
check "Gmail (envoi email)"         GMAIL_ADDRESS GMAIL_APP_PASSWORD MAIL_TO
check "Garmin (push séances)"       GARMIN_CONSUMER_KEY GARMIN_CONSUMER_SECRET GARMIN_REFRESH_TOKEN

echo
echo "Pour agir :"
echo "  - Semaine (test hors-ligne) :"
echo "      python3 training/generate.py week --activities training/tests/fixtures/last_week_sample.json --today 2026-09-14"
echo "  - Envoi hebdo (données réelles) :"
echo "      python3 training/generate.py send --live --push-garmin"
echo "  - Obtenir un token Strava (une fois) :"
echo "      python3 training/generate.py strava-auth-url"
echo "  - Tests :"
echo "      (cd training && python3 -m unittest discover -s tests)"
echo "======================================================================"
exit 0
