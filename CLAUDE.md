# StravaCallback — guide projet (Claude)

Callback OAuth Strava (Vercel + Botpress) **et** moteur d'entraînement adaptatif
backyard ultra sous `training/` (voir `training/README.md` et `training/RUNBOOK.md`).

## 📌 Suivi des développements en cours → GitHub Issues (obligatoire)

**Tout développement en cours, différé, ou identifié comme "à faire plus tard"
doit être listé comme une issue GitHub** dans `clmntlts/stravacallback`, avec le
label `pending-dev` (+ un label de catégorie : `training`, `code`, `infra`,
`research`).

Règles :
- Avant de **terminer une tâche** qui fait émerger des suites (TODO, point de
  revue non traité, amélioration repérée), les **déposer en issues** — ne jamais
  laisser du "pending" uniquement dans le chat ou dans le code.
- **Dédoublonner** : lister les issues ouvertes `pending-dev` avant d'en créer
  (mettre à jour l'existante plutôt que recréer).
- **Fermer** l'issue quand le développement est livré (référencer le commit/PR).
- Outil : la commande **`/backlog`** (voir `.claude/commands/backlog.md`)
  synchronise les développements en cours avec les issues via le serveur MCP
  GitHub. Les hooks bash n'ont pas accès à `gh`/l'API GitHub ici : ce suivi
  passe par Claude (MCP `mcp__github__*`), pas par un hook automatique.

## Développement `training/`

- Tests : `cd training && python3 -m unittest discover -s tests`
- Sans dépendances externes (stdlib) ; `fitdecode` seulement pour valider les FIT.
- Ne pas éditer les `.fit` à la main : régénérer via `python3 training/generate.py library`.
- Source unique de la structure : `training/engine/program.py`.
- **Paramètres & mémoire intersessions** : `training/athlete.json` (objectif, date de
  course, jours/sem, volume, allures) est lu par toute session, y compris la Routine
  hebdo. C'est LA mémoire durable du moteur — versionnée dans le repo. Voir
  `python3 training/generate.py config`.
