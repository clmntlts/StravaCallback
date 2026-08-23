#!/usr/bin/env python3
"""
Génère la bibliothèque de séances d'entraînement backyard ultra au format .FIT
(importable dans Garmin Connect -> Entraînements -> Importer).

    python3 training/build_workouts.py

Les allures ci-dessous sont des valeurs PAR DÉFAUT pour un coureur ~30-50 km/sem.
==> Édite le dictionnaire PACES avec TES allures (min/km) puis relance le script.
Quand le connecteur Strava est activé, on recalibre ces allures avec tes vraies
données et on régénère tout d'un coup.

Convention d'allure : "m:ss" par kilomètre.
"""

import os

from fit_encoder import (
    Duration,
    Intensity,
    Step,
    Target,
    Workout,
    write,
)

# --------------------------------------------------------------------------- #
# 1) TES ALLURES  (édite ici — min/km)
# --------------------------------------------------------------------------- #
PACES = {
    "recovery": "6:45",   # récupération, très facile
    "easy":     "6:15",   # endurance fondamentale
    "long":     "6:40",   # sortie longue, effort "ultra" (conversation possible)
    "yard":     "6:30",   # allure cible d'une boucle backyard à plat
    "steady":   "5:35",   # allure soutenue / seuil bas (tempo long)
    "tempo":    "5:00",   # seuil (allure semi/10 km soutenu)
    "cruise":   "4:55",   # fractionné au seuil
}

OUT_DIR = os.path.join(os.path.dirname(__file__), "workouts")


# --------------------------------------------------------------------------- #
# Helpers d'allure / durée
# --------------------------------------------------------------------------- #
def _pace_seconds(pace: str) -> int:
    m, s = pace.split(":")
    return int(m) * 60 + int(s)


def _mm_s(pace_seconds: int) -> int:
    """Vitesse en mm/s à partir d'une allure en s/km."""
    return round(1_000_000 / pace_seconds)


def speed_range(pace_key: str, slower: int = 20, faster: int = 20):
    """Fourchette de vitesse (mm/s) autour d'une allure, en s/km de marge."""
    base = _pace_seconds(PACES[pace_key])
    low = _mm_s(base + slower)   # allure plus lente -> vitesse basse
    high = _mm_s(base - faster)  # allure plus rapide -> vitesse haute
    return low, high


def MIN(minutes: float) -> int:
    return int(round(minutes * 60 * 1000))


def SEC(seconds: float) -> int:
    return int(round(seconds * 1000))


def KM(km: float) -> int:
    return int(round(km * 100000))  # centimètres


# --------------------------------------------------------------------------- #
# Constructeur de séance avec gestion des blocs de répétition
# --------------------------------------------------------------------------- #
class Builder:
    def __init__(self, name: str):
        self.w = Workout(name)

    # -- étapes simples ----------------------------------------------------- #
    def warmup(self, minutes: float):
        low, high = speed_range("easy", 40, 5)
        self.w.add(Step("Echauffement", Duration.TIME, MIN(minutes),
                        Target.SPEED, 0, low, high, Intensity.WARMUP))
        return self

    def cooldown(self, minutes: float):
        low, high = speed_range("recovery", 40, 5)
        self.w.add(Step("Retour au calme", Duration.TIME, MIN(minutes),
                        Target.SPEED, 0, low, high, Intensity.COOLDOWN))
        return self

    def run_time(self, minutes: float, pace_key: str, name: str,
                 slower=20, faster=20, intensity=Intensity.ACTIVE):
        low, high = speed_range(pace_key, slower, faster)
        self.w.add(Step(name, Duration.TIME, MIN(minutes),
                        Target.SPEED, 0, low, high, intensity))
        return self

    def run_dist(self, km: float, pace_key: str, name: str,
                 slower=15, faster=15, intensity=Intensity.ACTIVE):
        low, high = speed_range(pace_key, slower, faster)
        self.w.add(Step(name, Duration.DISTANCE, KM(km),
                        Target.SPEED, 0, low, high, intensity))
        return self

    def effort_time(self, seconds: float, name: str,
                    intensity=Intensity.ACTIVE):
        """Effort sans cible d'allure (côte, ligne droite) — pilote au ressenti."""
        self.w.add(Step(name, Duration.TIME, SEC(seconds),
                        Target.OPEN, 0, None, None, intensity))
        return self

    def easy_time(self, minutes: float, name: str,
                  intensity=Intensity.ACTIVE):
        self.w.add(Step(name, Duration.TIME, MIN(minutes),
                        Target.OPEN, 0, None, None, intensity))
        return self

    # -- blocs de répétition ----------------------------------------------- #
    def repeat(self, count: int, build_fn):
        start = len(self.w.steps)
        build_fn(self)
        # Étape "répétition" : boucle vers l'index de départ, `count` fois.
        self.w.add(Step("", Duration.REPEAT_UNTIL_STEPS_CMPLT, start,
                        Target.OPEN, count, None, None, Intensity.ACTIVE))
        return self

    def build(self) -> Workout:
        return self.w


# --------------------------------------------------------------------------- #
# 2) BIBLIOTHÈQUE DE SÉANCES
# --------------------------------------------------------------------------- #
def workouts():
    W = []

    # --- Récupération / endurance fondamentale ---------------------------- #
    W.append(("01_Recup_40",
              Builder("Recup 40'")
              .run_time(40, "recovery", "Tres facile", 45, 0)
              .build()))

    W.append(("02_Facile_45",
              Builder("Facile 45'")
              .run_time(45, "easy", "Endurance", 30, 15)
              .build()))

    W.append(("03_Facile_60",
              Builder("Facile 60'")
              .run_time(60, "easy", "Endurance", 30, 15)
              .build()))

    W.append(("04_Facile_75",
              Builder("Facile 75'")
              .run_time(75, "easy", "Endurance", 30, 15)
              .build()))

    W.append(("05_Facile_lignes_droites",
              Builder("Facile 45' + lignes droites")
              .run_time(35, "easy", "Endurance", 30, 15)
              .repeat(6, lambda b: (
                  b.effort_time(20, "Ligne droite vite"),
                  b.easy_time(60, "Recup trot", Intensity.RECOVERY)))
              .run_time(5, "recovery", "Retour au calme", 40, 0,
                        Intensity.COOLDOWN)
              .build()))

    # --- Qualité : seuil / tempo ------------------------------------------ #
    W.append(("06_Seuil_2x15",
              Builder("Seuil 2x15'")
              .warmup(15)
              .repeat(2, lambda b: (
                  b.run_time(15, "tempo", "Seuil", 8, 8),
                  b.run_time(3, "recovery", "Recup", 45, 0, Intensity.RECOVERY)))
              .cooldown(10)
              .build()))

    W.append(("07_Seuil_3x10",
              Builder("Seuil 3x10'")
              .warmup(15)
              .repeat(3, lambda b: (
                  b.run_time(10, "tempo", "Seuil", 8, 8),
                  b.run_time(2.5, "recovery", "Recup", 45, 0, Intensity.RECOVERY)))
              .cooldown(10)
              .build()))

    W.append(("08_Seuil_5x1km",
              Builder("Seuil 5x1km")
              .warmup(15)
              .repeat(5, lambda b: (
                  b.run_dist(1.0, "cruise", "1 km seuil", 8, 8),
                  b.effort_time(90, "Trot recup", Intensity.RECOVERY)))
              .cooldown(10)
              .build()))

    # --- Qualité : côtes (force) ------------------------------------------ #
    W.append(("09_Cotes_8x60",
              Builder("Cotes 8x60\"")
              .warmup(15)
              .repeat(8, lambda b: (
                  b.effort_time(60, "Cote - fort"),
                  b.effort_time(90, "Descente trot", Intensity.RECOVERY)))
              .cooldown(10)
              .build()))

    W.append(("10_Cotes_10x90",
              Builder("Cotes 10x90\"")
              .warmup(15)
              .repeat(10, lambda b: (
                  b.effort_time(90, "Cote - fort"),
                  b.effort_time(120, "Descente trot", Intensity.RECOVERY)))
              .cooldown(10)
              .build()))

    # --- Résistance à la fatigue (spécifique ultra) ----------------------- #
    W.append(("11_Resistance_4x20",
              Builder("Resistance fatigue 4x20'")
              .warmup(15)
              .repeat(4, lambda b: (
                  b.run_time(20, "steady", "Soutenu", 12, 8),
                  b.run_time(3, "easy", "Recup", 30, 0, Intensity.RECOVERY)))
              .cooldown(10)
              .build()))

    # --- Sorties longues -------------------------------------------------- #
    for mins, tag in [(90, "1h30"), (120, "2h00"), (150, "2h30"),
                      (180, "3h00"), (240, "4h00"), (300, "5h00")]:
        idx = 12 + [90, 120, 150, 180, 240, 300].index(mins)
        W.append((f"{idx}_Longue_{tag.replace('h','h')}",
                  Builder(f"Sortie longue {tag}")
                  .run_time(mins, "long", "Effort ultra", 30, 20)
                  .build()))

    # --- Back-to-back : 2e jour sur jambes fatiguées ---------------------- #
    for mins, tag, idx in [(60, "1h00", 18), (90, "1h30", 19), (120, "2h00", 20)]:
        W.append((f"{idx}_B2B_J2_{tag}",
                  Builder(f"B2B J2 - {tag}")
                  .run_time(mins, "long", "Jambes fatiguees - facile", 40, 15)
                  .build()))

    # --- Marche-course (time on feet, gestion nutrition) ------------------ #
    W.append(("21_Marche_course_3h",
              Builder("Marche-course 3h")
              .repeat(6, lambda b: (
                  b.run_time(25, "long", "Course", 40, 20),
                  b.easy_time(5, "Marche + ravito", Intensity.REST)))
              .build()))

    W.append(("22_Marche_course_4h",
              Builder("Marche-course 4h")
              .repeat(8, lambda b: (
                  b.run_time(25, "long", "Course", 40, 20),
                  b.easy_time(5, "Marche + ravito", Intensity.REST)))
              .build()))

    # --- Simulations "backyard" (boucle + repos horaire) ------------------ #
    W.append(("23_Simu_Backyard_6_boucles",
              Builder("Simu Backyard 6 boucles")
              .repeat(6, lambda b: (
                  b.run_time(50, "yard", "Boucle (~6.7km)", 40, 20),
                  b.easy_time(10, "Repos + ravito", Intensity.REST)))
              .build()))

    W.append(("24_Simu_Backyard_10_boucles",
              Builder("Simu Backyard 10 boucles")
              .repeat(10, lambda b: (
                  b.run_time(50, "yard", "Boucle (~6.7km)", 45, 25),
                  b.easy_time(10, "Repos + ravito", Intensity.REST)))
              .build()))

    # --- Sortie de nuit --------------------------------------------------- #
    W.append(("25_Sortie_nuit_2h",
              Builder("Sortie nuit 2h - frontale + ravito")
              .run_time(120, "long", "Nuit - facile", 40, 20)
              .build()))

    return W


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    total = 0
    for filename, wkt in workouts():
        path = os.path.join(OUT_DIR, f"{filename}.fit")
        size = write(wkt, path)
        total += 1
        print(f"  {filename}.fit  ({len(wkt.steps)} etapes, {size} o)")
    print(f"\n{total} seances generees dans {OUT_DIR}")


if __name__ == "__main__":
    main()
