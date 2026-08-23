#!/usr/bin/env python3
"""
Génère le plan périodisé backyard ultra (34 semaines) au format Markdown.

    python3 training/build_plan.py

Source unique de vérité pour le calendrier : chaque séance renvoie à un fichier
.FIT de la bibliothèque (training/workouts/). Modifie PLAN/SESSIONS puis relance.
"""

import os

# clé -> (libellé, fichier .fit ou None, durée approx en minutes)
SESSIONS = {
    "off":        ("Repos",                          None,                            0),
    "recup40":    ("Récup 40'",                       "01_Recup_40",                   40),
    "fac45":      ("Facile 45'",                      "02_Facile_45",                  45),
    "fac60":      ("Facile 60'",                      "03_Facile_60",                  60),
    "fac75":      ("Facile 75'",                      "04_Facile_75",                  75),
    "strides":    ("Facile + lignes droites",         "05_Facile_lignes_droites",      50),
    "seuil2x15":  ("Seuil 2×15'",                     "06_Seuil_2x15",                 55),
    "seuil3x10":  ("Seuil 3×10'",                     "07_Seuil_3x10",                 62),
    "seuil5x1":   ("Seuil 5×1 km",                    "08_Seuil_5x1km",                50),
    "cotes8":     ("Côtes 8×60\"",                    "09_Cotes_8x60",                 45),
    "cotes10":    ("Côtes 10×90\"",                   "10_Cotes_10x90",                55),
    "resist":     ("Résistance fatigue 4×20'",        "11_Resistance_4x20",           110),
    "long90":     ("Longue 1h30",                     "12_Longue_1h30",                90),
    "long120":    ("Longue 2h00",                     "13_Longue_2h00",               120),
    "long150":    ("Longue 2h30",                     "14_Longue_2h30",               150),
    "long180":    ("Longue 3h00",                     "15_Longue_3h00",               180),
    "long240":    ("Longue 4h00",                     "16_Longue_4h00",               240),
    "long300":    ("Longue 5h00",                     "17_Longue_5h00",               300),
    "b2b60":      ("B2B J2 - 1h00",                   "18_B2B_J2_1h00",                60),
    "b2b90":      ("B2B J2 - 1h30",                   "19_B2B_J2_1h30",                90),
    "b2b120":     ("B2B J2 - 2h00",                   "20_B2B_J2_2h00",               120),
    "mc180":      ("Marche-course 3h",                "21_Marche_course_3h",          180),
    "mc240":      ("Marche-course 4h",                "22_Marche_course_4h",          240),
    "by6":        ("Simu Backyard 6 boucles",         "23_Simu_Backyard_6_boucles",   360),
    "by10":       ("Simu Backyard 10 boucles",        "24_Simu_Backyard_10_boucles",  600),
    "nuit":       ("Sortie nuit 2h",                  "25_Sortie_nuit_2h",            120),
}

# (semaine, phase, décharge?, note, mardi, jeudi, samedi, dimanche)
PLAN = [
    # ---- Phase 1 : FONDATION (aérobie + habitude de fréquence) ----
    (1,  "Fondation", False, "On installe la régularité, allure basse",        "fac60",    "strides",   "long90",  "b2b60"),
    (2,  "Fondation", False, "Le volume monte doucement",                       "fac60",    "strides",   "long120", "b2b60"),
    (3,  "Fondation", False, "Intro force en côtes",                            "cotes8",   "fac60",     "long120", "b2b90"),
    (4,  "Fondation", True,  "Décharge — on assimile",                          "fac45",    "recup40",   "long90",  "b2b60"),
    (5,  "Fondation", False, "Intro seuil",                                     "seuil2x15","fac60",     "long150", "b2b90"),
    (6,  "Fondation", False, "Force + endurance",                               "cotes10",  "fac75",     "long150", "b2b90"),
    (7,  "Fondation", False, "Premier gros week-end",                           "seuil3x10","fac60",     "long180", "b2b120"),
    (8,  "Fondation", True,  "Décharge",                                        "strides",  "recup40",   "long120", "b2b60"),

    # ---- Phase 2 : FORCE-ENDURANCE (temps de pied, B2B) ----
    (9,  "Force-endurance", False, "Résistance à la fatigue",                   "resist",   "fac60",     "long180", "b2b120"),
    (10, "Force-endurance", False, "Marche-course : gestion ravito",            "cotes10",  "fac75",     "mc180",   "b2b90"),
    (11, "Force-endurance", False, "Charge soutenue",                           "seuil3x10","fac75",     "long180", "b2b120"),
    (12, "Force-endurance", True,  "Décharge",                                  "strides",  "recup40",   "long120", "b2b60"),
    (13, "Force-endurance", False, "Premier 4h en temps de pied",               "resist",   "fac60",     "mc240",   "b2b120"),
    (14, "Force-endurance", False, "Volume soutenu",                            "cotes10",  "fac75",     "long180", "b2b120"),
    (15, "Force-endurance", False, "Deuxième 4h",                               "seuil3x10","fac75",     "mc240",   "b2b120"),
    (16, "Force-endurance", True,  "Décharge",                                  "fac60",    "recup40",   "long150", "b2b60"),

    # ---- Phase 3 : SPÉCIFIQUE BACKYARD (boucles, nuit, nutrition) ----
    (17, "Spécifique", False, "1re simu backyard (6 boucles)",                  "resist",   "fac60",     "by6",     "b2b90"),
    (18, "Spécifique", False, "Plus longue sortie continue : 4h",               "cotes10",  "fac75",     "long240", "b2b120"),
    (19, "Spécifique", False, "Temps de pied + ravito",                         "seuil3x10","fac75",     "mc240",   "b2b120"),
    (20, "Spécifique", True,  "Décharge",                                       "strides",  "recup40",   "long150", "b2b60"),
    (21, "Spécifique", False, "2e simu backyard",                               "resist",   "fac60",     "by6",     "b2b120"),
    (22, "Spécifique", False, "Le gros morceau : 5h",                           "cotes10",  "fac75",     "long300", "b2b120"),
    (23, "Spécifique", False, "Course de nuit (jeu.) + long",                   "seuil3x10","nuit",      "mc240",   "b2b120"),
    (24, "Spécifique", True,  "Décharge",                                       "fac60",    "recup40",   "long150", "b2b60"),
    (25, "Spécifique", False, "Répétition majeure : 10 boucles / nuit",         "resist",   "fac60",     "by10",    "b2b60"),
    (26, "Spécifique", False, "Consolidation",                                  "cotes10",  "fac75",     "long240", "b2b120"),

    # ---- Phase 4 : PIC ----
    (27, "Pic", False, "Gros volume",                                           "resist",   "fac75",     "long240", "b2b120"),
    (28, "Pic", True,  "Mini-décharge avant le pic",                            "seuil2x15","fac60",     "long180", "b2b90"),
    (29, "Pic", False, "Spécifique boucles",                                    "cotes10",  "fac75",     "by6",     "b2b120"),
    (30, "Pic", False, "Plus gros continu : 5h",                                "resist",   "fac75",     "long300", "b2b120"),
    (31, "Pic", False, "RÉPÉTITION GÉNÉRALE (10 boucles, nuit, nutrition)",     "strides",  "fac45",     "by10",    "b2b60"),

    # ---- Phase 5 : AFFÛTAGE ----
    (32, "Affûtage", False, "On réduit le volume, on garde la fraîcheur",       "seuil2x15","fac45",     "long150", "b2b60"),
    (33, "Affûtage", False, "Affûtage",                                         "strides",  "recup40",   "long90",  "b2b60"),
    (34, "Affûtage", False, "SEMAINE DE COURSE",                                "recup40",  "strides",   "off",     "off"),
]

OUT = os.path.join(os.path.dirname(__file__), "plan.md")


def label(key):
    return SESSIONS[key][0]


def week_minutes(row):
    return sum(SESSIONS[k][2] for k in row[4:8])


def main():
    lines = []
    lines.append("# Plan Backyard Ultra — 34 semaines (Sept. → Avril)\n")
    lines.append("Objectif : **18-24 yards** · 4 jours/semaine · "
                 "Mar. (qualité) · Jeu. (facile) · Sam. (longue) · Dim. (B2B).\n")
    lines.append("> Chaque séance renvoie à un fichier `.FIT` de "
                 "`training/workouts/` à importer dans Garmin Connect. "
                 "Les jours non listés = repos ou renfo/mobilité.\n")

    current_phase = None
    for row in PLAN:
        wk, phase, deload, note, mar, jeu, sam, dim = row
        if phase != current_phase:
            current_phase = phase
            lines.append(f"\n## Phase — {phase}\n")
            lines.append("| Sem. | Mardi | Jeudi | Samedi | Dimanche | Total | Note |")
            lines.append("|---:|---|---|---|---|---:|---|")
        tag = " 🟢" if deload else ""
        h = week_minutes(row) / 60
        lines.append(
            f"| {wk}{tag} | {label(mar)} | {label(jeu)} | "
            f"{label(sam)} | {label(dim)} | {h:.1f} h | {note} |"
        )

    lines.append("\n🟢 = semaine de décharge (récupération, ~-35 % de volume).\n")

    # Récap charge
    peak = max(PLAN, key=week_minutes)
    lines.append(f"\n**Pic de charge** : semaine {peak[0]} "
                 f"(~{week_minutes(peak)/60:.1f} h). "
                 "La montée en charge est progressive avec décharge toutes "
                 "les 3-4 semaines pour absorber le travail sans se blesser.\n")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Plan écrit dans {OUT} ({len(PLAN)} semaines)")


if __name__ == "__main__":
    main()
