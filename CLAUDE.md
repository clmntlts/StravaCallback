# StravaCallback — guide projet (Claude)

Moteur d'entraînement adaptatif backyard ultra sous `training/` (voir
`training/README.md` et `training/RUNBOOK.md`) : plan macro, adaptation
hebdomadaire au réalisé Strava, génération de `.fit`, envoi email et
planification Garmin. Automatisation locale (cron/Tâche planifiée) via la
Routine hebdo (`/weekly`). Interface web locale optionnelle : `training/webapp/`
(`python3 training/generate.py serve`) — dashboard interactif, téléchargement
`.fit`, push Garmin ; reste local uniquement, jamais hébergée (voir
`training/RUNBOOK.md`).

L'ancien callback OAuth Strava (Vercel + Botpress) a été retiré (commit
`8249e3c`, 2026-08-24) : l'auth Strava est désormais CLI-only
(`generate.py strava-auth-url` / `strava-auth-exchange`).

## 📌 Suivi des développements en cours → GitHub Issues (obligatoire)

**Tout développement en cours, différé, ou identifié comme "à faire plus tard"
doit être listé comme une issue GitHub** dans `clmntlts/stravacallback`, avec le
label `pending-dev` (+ un label de catégorie : `training`, `code`, `infra`,
`research`).

Règles :
- **Avant de démarrer** un développement (feature, fix, refacto un peu
  substantiel), lister les issues `pending-dev` ouvertes
  (`mcp__github__list_issues`, labels `["pending-dev"]`, state `OPEN`) pour
  voir si le sujet est déjà répertorié — contexte, décisions déjà prises,
  pistes de correctif — et pour éviter de retravailler un point déjà
  arbitré ou de repartir sur une piste écartée.
- Avant de **terminer une tâche** qui fait émerger des suites (TODO, point de
  revue non traité, amélioration repérée), les **déposer en issues** — ne jamais
  laisser du "pending" uniquement dans le chat ou dans le code.
- **Dédoublonner** : lister les issues ouvertes `pending-dev` avant d'en créer
  (mettre à jour l'existante plutôt que recréer).
- **Fermer** l'issue quand le développement est livré : si le travail en cours
  résout une issue `pending-dev` existante (même partiellement — cocher les
  cases faites), mettre à jour son corps et, une fois complète, la fermer
  (`state: "closed"`, `state_reason: "completed"`) en référençant le
  commit/PR. Ne pas laisser une issue ouverte pour un point déjà livré dans le
  code — vérifier l'état réel du fichier concerné plutôt que de se fier au
  seul texte de l'issue avant de la fermer ou de la marquer résolue.
- Outil : la commande **`/backlog`** (voir `.claude/commands/backlog.md`)
  synchronise les développements en cours avec les issues via le serveur MCP
  GitHub. Les hooks bash n'ont pas accès à `gh`/l'API GitHub ici : ce suivi
  passe par Claude (MCP `mcp__github__*`), pas par un hook automatique.

## Développement `training/`

- Tests : `cd training && python3 -m unittest discover -s tests`
- Cœur sans dépendances externes (stdlib). Dépendances **optionnelles**
  (`training/requirements-optional.txt`, import paresseux, jamais requises pour
  générer/tester) : `fitdecode` pour valider les FIT, `garminconnect` pour la
  planification au calendrier Garmin Connect (`send --push-connect`).
- Ne pas éditer les `.fit` à la main : régénérer via `python3 training/generate.py library`.
- Source unique de la structure : `training/engine/program.py`.
- **Paramètres & mémoire intersessions** : `training/athlete.json` (objectif, date de
  course, jours/sem, volume, allures) est lu par toute session, y compris la Routine
  hebdo. C'est LA mémoire durable du moteur — versionnée dans le repo. Voir
  `python3 training/generate.py config`.
