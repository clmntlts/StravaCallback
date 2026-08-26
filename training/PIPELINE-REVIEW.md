# Revue multi-experts du pipeline — backlog prêt-à-issue (2026-08-26)

Revue multi-agents (8 experts logiciel + entraînement, 2 vérificateurs adverses,
1 synthèse) du moteur d'entraînement backyard ultra. **32 constats retenus**
(confirmed/plausible). Ce fichier sert de source pour créer les issues GitHub
`pending-dev` dans `clmntlts/StravaCallback` (via `/backlog` en session
interactive : le MCP GitHub / `gh` n'étaient pas disponibles lors de la revue).

Verdict : pipeline fonctionnel, 64 tests au vert — **mais au vert par angle mort**
(aucun test n'inspecte les cibles FC). Trois régressions HIGH cassent
silencieusement le livrable montre + email ; le plan tourne sans gouverneur de
volume pendant que le cap adaptatif étrangle les mega-sims backyard.

Convention d'entrée : `[ID] Titre` · **labels** · **sévérité** · **fichier:ligne**
· Problème · Correctif. Les trois 🔴 ont été re-vérifiés manuellement dans le code.

---

## 🔴 Régressions critiques (re-vérifiées)

### [L1] `session_to_connect` mute toute cible FC en `no.target`
- **labels** : pending-dev, code · **sévérité** : high · **fichier** : `training/engine/garmin_connect.py:100`
- **Problème** : `_leaf` ne traduit que `Target.SPEED` ; toute cible `HEART_RATE` (séances aérobies Z2) devient `_TARGET_NONE`, sans warning. La séance planifiée via `--push-connect` (voie réelle de la routine hebdo) perd le garde-fou Z2 → annule le correctif anti-dérive Z3.
- **Correctif** : gérer `Target.HEART_RATE` → `heart.rate.zone` (targetType id 4), en **retranchant l'offset +100** (223-251 → bpm réels) ; lever une erreur sur tout target non géré plutôt que dégrader en silence.

### [L2] `session_to_garmin` (Training API) rend la FC en `OPEN`
- **labels** : pending-dev, code · **sévérité** : high · **fichier** : `training/engine/garmin_workout.py:58`
- **Problème** : même limite que L1 sur la voie Training API officielle (`--push-garmin`, `generate.py:194`) : les cibles FC deviennent `TARGET_OPEN`.
- **Correctif** : ajouter `TARGET_HEART_RATE` + branche HR dans `_leaf` (offset −100) ; erreur/log sur target inconnu.

### [L3] Graphe de progression en `<svg>` inline — vidé par Gmail
- **labels** : pending-dev, code · **sévérité** : high · **fichier** : `training/engine/dashboard.py:122`
- **Problème** : `_load_curve_svg` rend tout le graphe « ambition / prévu / réalisé » en SVG inline. Gmail supprime le SVG → le panneau « Progression » est vide dans le corps d'email (la pièce jointe `dashboard.html` reste correcte).
- **Correctif** : rendre en table HTML de barres (`<div>`/`<td>` en %, technique déjà en place pour la barre de progression) ; vérifier le rendu Gmail réel.

### [E1] Le cap anti-saut de la longue étrangle les sims backyard (unités hétérogènes)
- **labels** : pending-dev, training · **sévérité** : high · **fichier** : `training/engine/adapt.py:219,222`
- **Problème** : le cap compare `minutes(backyard)` — **repos inclus** (12 boucles = 720′) — à `ref_long_s`, temps de **mouvement** seul (~5 h max). backyard(12) exigerait 7,5 h de course continue → toujours écrêté à ~6-8 boucles. Le dashboard affiche 12/14, le `.fit` prescrit bien moins.
- **Correctif** : exclure les templates de simulation (`_LONG_TEMPLATES` existe déjà) du cap de durée ; piloter la progression backyard en **nombre de boucles** (+2/palier), découplé du plafond de durée continue.

---

## Logiciel (autres)

### [L4] Le refresh token Strava avale le corps d'erreur
- **labels** : pending-dev, code · **sévérité** : medium · **fichier** : `training/engine/strava.py:66`
- **Problème** : sur `refresh_token` expiré/invalide, Strava répond 400 avec un JSON explicite ; le code rend un « HTTP Error 400 » générique. C'est le mode de panne n°1 du run hebdo → diagnostic inutile.
- **Correctif** : `except HTTPError` lisant `e.read()`, re-lever avec le corps décodé ; distinguer 400 `invalid_grant` → message « régénérer le jeton ».

### [L5] `_prescribed_prev_seconds` ne reproduit pas la prescription N-1
- **labels** : pending-dev, code · **sévérité** : medium · **fichier** : `training/generate.py:118`
- **Problème** : le recalcul d'adhérence n'applique ni le rolling-max ni le plancher `LONGEST_RUN_MIN` que la délivrance applique → divergence sur l'écrêtage de la longue.
- **Correctif** : factoriser le peuplement rolling + plancher dans un helper unique partagé entre délivrance et recalcul.

### [L6] `clamp()`/`min()`/`max()` dans le CSS `<head>` (email)
- **labels** : pending-dev, code · **sévérité** : medium · **fichier** : `training/engine/dashboard.py:351,355,398,362`
- **Problème** : Gmail abandonne les déclarations `clamp()` → padding 0, contenu collé aux bords (le docstring prétend l'inverse).
- **Correctif** : valeurs fixes email-safe (padding 24/22px, h1 2.4rem) + media query optionnelle pour le responsive.

### [L7] Tests Garmin n'exercent que des cibles d'allure
- **labels** : pending-dev, code · **sévérité** : medium · **fichier** : `training/tests/test_pipeline.py:143`
- **Problème** : l'angle mort qui a laissé passer L1/L2 : aucun test ne vérifie que les séances aérobies portent une cible FC dans les traductions Garmin.
- **Correctif** : test asservissant `easy`/`long` → targetType FC (pas `no.target`/`OPEN`) avec bornes cohérentes `HR_ZONE2` (bpm réels, pas +100).

### [L8] `--activities` crash en traceback brut
- **labels** : pending-dev, code · **sévérité** : low · **fichier** : `training/generate.py:90`
- **Problème** : fichier absent/JSON invalide → traceback brut (asymétrie avec `--live`, protégé).
- **Correctif** : `except (FileNotFoundError, JSONDecodeError)` → `SystemExit` propre.

### [L9] `days_per_week` raboté à 4 en silence
- **labels** : pending-dev, code · **sévérité** : low · **fichier** : `training/engine/config.py:101`
- **Problème** : une intention 5-6 j est persistée mais silencieusement ramenée à 4.
- **Correctif** : avertir à l'onboarding si days>4 ; loguer l'écart brut/effectif. (Lié à l'issue existante « support 5-6 j ».)

### [L10] `display:grid` KPI / Google Fonts `<link>` / `flex` (email)
- **labels** : pending-dev, code · **sévérité** : low · **fichier** : `training/engine/dashboard.py:385,345,371`
- **Problème** : dégradations Gmail cosmétiques (empilement KPI, polices système, `.ptrow` sur deux lignes).
- **Correctif** : passer `.kpis` et `.ptrow` en table `<td>` ; assumer les replis de police.

### [L11] `date.today()` local vs Strava UTC
- **labels** : pending-dev, code · **sévérité** : low · **fichier** : `training/engine/program.py:364`
- **Problème** : off-by-one possible aux frontières de semaine sans `--today` (fuseau local vs UTC Strava).
- **Correctif** : source de date unique (`_today()`) par défaut partout.

---

## Entraînement (autres)

### [E2] Rampe de volume hors profil : +211 % en une semaine
- **labels** : pending-dev, training · **sévérité** : high · **fichier** : `training/engine/program.py:72`
- **Problème** : S24→S25 = 4,75→14,78 h ; pic ~3,7× le volume de départ, mega-bloc unique sans palier. Facteur de blessure.
- **Correctif** : paliers 6→8→10→12 espacés + semaine-pont ~70 % avant chaque grosse sim (voir E4 pour le gouverneur).

### [E3] Aucune répétition nuit blanche ; le « nuit » des sims est décoratif
- **labels** : pending-dev, training · **sévérité** : high · **fichier** : `training/engine/workouts.py:338`
- **Problème** : les sims S25/S31 dites « nuit » passent par `_backyard` sans contenu nuit ; expo max = `night(120)` = 2 h. Le sommeil est le 1er facteur d'abandon en 24 h.
- **Correctif** : flag `night` sur `_backyard` (frontale/batterie/ravito chaud + tip privation) ; ≥1 sim démarrée en soirée couvrant une nuit complète avant l'affûtage.

### [E4] Gouverneurs de volume inactifs sur le plan nominal 34 sem
- **labels** : pending-dev, training · **sévérité** : medium · **fichier** : `training/engine/program.py:302`
- **Problème** : `_smooth_volume` (gardé `if COMPRESSED`) et `_cap_peak` (`peak=null`) ne sont jamais appelés sur le plan complet → aucun frein hebdo total.
- **Correctif** : dériver un `peak_volume_h` par défaut de `start_volume_h`, ou appliquer `_smooth_volume` à tous les plans (cap permissif en Spécifique/Pic).

### [E5] Décharges figées découplées de la charge de phase
- **labels** : pending-dev, training · **sévérité** : medium · **fichier** : `training/engine/program.py:71`
- **Problème** : `DELOAD_SCALE` non appliqué hors compressé → décharges ~4-4,75 h même après un bloc 11-15 h (sur-décharge), le rebond doit tout rattraper.
- **Correctif** : indexer la décharge sur 55-65 % de la moyenne des 3 semaines précédentes + cap de rebond post-décharge.

### [E6] `base_maintained` restaure 100 % du volume course sur base cross-training
- **labels** : pending-dev, training · **sévérité** : medium · **fichier** : `training/engine/adapt.py:190`
- **Problème** : contredit `coach.py:119` (« l'impact ne se travaille qu'en courant ») ; saut de charge d'impact au sol.
- **Correctif** : dissocier cardio (tenu par le vélo) et impact ; plafonner la reprise du volume course/B2B à +30 % de temps de pied max, pas au nominal.

### [E7] Easy ET longue partagent la même cible Z2 pleine largeur (123-151)
- **labels** : pending-dev, training · **sévérité** : medium · **fichier** : `training/engine/workouts.py:112`
- **Problème** : 151 ≈ 82 % FCmax, coûteux en glycogène sur 4-5 h ; aucune pression descendante face à la dérive documentée.
- **Correctif** : plafonner easy/longue à ~mi-Z2 (123-138) ; réserver le haut 151 aux blocs steady/spécifiques.

### [E8] +60 % semaine-à-semaine autorisé sur la longue continue (Spécifique/Pic)
- **labels** : pending-dev, training · **sévérité** : medium · **fichier** : `training/engine/adapt.py:45`
- **Problème** : 3-6× la norme sûre sur la séance la plus traumatisante ; `rolling_max` tient le plafond 3 sem même après une longue ratée.
- **Correctif** : ramener Spécifique/Pic à ~1.25-1.35 pour les longues **continues** ; le +60 % en exception, pas en règle par défaut.

### [E9] Le B2B (jusqu'à 2h30) échappe au cap anti-saut
- **labels** : pending-dev, training · **sévérité** : medium · **fichier** : `training/engine/adapt.py:219`
- **Problème** : le cap est codé `if "long" in` ; le rôle b2b n'est jamais plafonné (décharge b2b(60)→b2b(150) = +150 % sans frein).
- **Correctif** : cap dépendant de phase sur le rôle b2b (réf. plus long b2b bouclé) ; a minima le borner quand la longue est plafonnée.

### [E10] Sim backyard sans garde-fou FC (allure seule)
- **labels** : pending-dev, training · **sévérité** : medium · **fichier** : `training/engine/workouts.py:346`
- **Problème** : `run_dist('yard')` → `Target.SPEED`, pas de cap FC là où la dérive tardive coûte le plus.
- **Correctif** : encoder la boucle en `aerobic()`/HR Z2 comme `_long`, ou resserrer la fenêtre rapide (`faster=0/5`).

### [E11] Ravito 60-80 g/h sans glucides multi-transportables
- **labels** : pending-dev, training · **sévérité** : medium · **fichier** : `training/engine/workouts.py:411`
- **Problème** : >60 g/h de glucose seul sature SGLT1 → détresse GI (1re cause d'abandon).
- **Correctif** : chiffrer le mix glucose:fructose ~1:0.8 au-delà de 60 g/h ; progression gut-training 60→80-100 au fil des sims.

### [E12] Aucune cible sodium/électrolytes chiffrée sur 24h
- **labels** : pending-dev, training · **sévérité** : medium · **fichier** : `training/engine/workouts.py:402`
- **Problème** : « boire régulièrement » sans sodium = scénario d'hyponatrémie de dilution.
- **Correctif** : cible ~300-700 mg/h sur séances >2 h et backyard ; lier le volume de boisson au sodium, pas à la seule soif.

### [E13] `derive_paces` inverse l'ordre yard/recovery
- **labels** : pending-dev, training · **sévérité** : low (latent) · **fichier** : `training/engine/workouts.py:59`
- **Problème** : yard dérivé à 6:14 au lieu de 7:30 (repos horaire rogné) — latent car les allures explicites d'`athlete.json` priment aujourd'hui.
- **Correctif** : aligner `_PACE_OFFSETS` (yard = offset max) ou exclure yard/recovery de la recalibration Strava + test asservissant l'ordre des allures.

### [E14] Tip runwalk 25'/5' prétend « reproduire le rythme de course »
- **labels** : pending-dev, training · **sévérité** : low · **fichier** : `training/engine/workouts.py:320`
- **Problème** : la marche intercalée toutes les 25' n'existe pas en last-man-standing ; libellé trompeur.
- **Correctif** : corriger le libellé ; repositionner runwalk comme travail ravito/estomac.

---

## Plausibles — à investiguer

### [P1] Répétition générale trop lourde à J-21
- **labels** : pending-dev, training · **fichier** : `training/engine/program.py:80`
- S31 = 15,38 h / ~13 h de sim (58 % de l'objectif) placée 3 sem avant la course. Réduire l'ampleur (10-12 boucles) et/ou l'avancer à J-28/35 avec récup franche avant l'affûtage.

### [P2] Écart 14→24 boucles jamais comblé
- **labels** : pending-dev, training · **fichier** : `training/engine/workouts.py:343`
- Saut 6→8→12→14 sans jonction ; allure/repos constants. Nuance : une sim réelle produit la fatigue/dérive naturellement (le FIT est une cible, pas un vécu). Viser ≥1 sim 16-18 boucles ; documenter en tip le repos qui rétrécit comme cible mentale.

### [P3] `base_maintained` neutralise l'alerte 0-sortie
- **labels** : pending-dev, training · **fichier** : `training/engine/adapt.py:180`
- Discutable de prescrire une semaine course nominale après zéro course sur seule preuve vélo. Garder un signal doux « à vérifier » si `n_runs==0` même avec base cross-training.

### [P4] Dégradations `flex` Gmail (`.ptrow`)
- **labels** : pending-dev, code · **fichier** : `training/engine/dashboard.py:371`
- `.ptrow` perd le `space-between` sous Gmail (libellé + % sur deux lignes). Layout table pour `.ptrow`.

---

## Tension de conception à arbitrer (pas un bug)

**E1 (cap trop serré sur backyard) vs E2/E8 (cap/rampe trop lâches sur le volume
et la longue continue)** : le facteur `1.6` est simultanément inopérant sur les
sims (unités hétérogènes) et dangereux sur le continu. Toute correction doit
**découpler** la progression backyard (nombre de boucles) du plafond de durée
continue.

---

## Top 3 actions (par valeur)

1. **Restaurer les cibles FC sur les deux voies Garmin** (L1 + L2, + test L7) —
   régression HIGH silencieuse qui annule le correctif Z3 sur la séance poussée à
   la montre. Offset −100 impératif.
2. **Découpler la progression backyard du cap durée (E1) + activer un gouverneur
   de volume sur le plan complet (E2/E4)** — le dashboard promet 12/14 boucles que
   le `.fit` n'encode pas, et le plan grimpe de +211 % en une semaine.
3. **Réparer le rendu email (L3) + injecter une vraie simu nuit (E3)** — panneau
   « Progression » vide dans Gmail, et zéro répétition nuit blanche sur un objectif
   où le sommeil est le 1er facteur d'abandon.
