"""
Encodeur FIT minimal et sans dépendance pour fichiers d'ENTRAINEMENT structurés
(structured workout files), importables dans Garmin Connect et synchronisables
sur les montres Garmin.

Il implémente juste ce qu'il faut du protocole FIT (Flexible and Interoperable
data Transfer) pour écrire un fichier de type "workout" :
  - message file_id   (global mesg num 0)
  - message workout   (global mesg num 26)
  - messages workout_step (global mesg num 27)

Références : profil FIT SDK de Garmin (types de base, numéros de messages/champs,
algorithme de CRC-16).

Aucune dépendance : pur Python standard.  Utilisation : voir build_workouts.py.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass, field
from typing import List, Optional


# --------------------------------------------------------------------------- #
# CRC-16 FIT (algorithme officiel du SDK, version sans table pré-calculée)
# --------------------------------------------------------------------------- #
_CRC_TABLE = [
    0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
    0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
]


def fit_crc(data: bytes, crc: int = 0) -> int:
    for byte in data:
        tmp = _CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ _CRC_TABLE[byte & 0xF]

        tmp = _CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ _CRC_TABLE[(byte >> 4) & 0xF]
    return crc & 0xFFFF


# --------------------------------------------------------------------------- #
# Types de base FIT (base type byte, taille en octets, format struct)
# --------------------------------------------------------------------------- #
ENUM = (0x00, 1, "B")
UINT8 = (0x02, 1, "B")
UINT16 = (0x84, 2, "H")
UINT32 = (0x86, 4, "I")
UINT32Z = (0x8C, 4, "I")
STRING = (0x07, 1, "s")  # taille variable, gérée à part

# Valeurs "invalides" (= champ non renseigné) par type
INVALID = {
    ENUM: 0xFF,
    UINT8: 0xFF,
    UINT16: 0xFFFF,
    UINT32: 0xFFFFFFFF,
    UINT32Z: 0x00000000,
}

# Epoch FIT : secondes entre 1970-01-01 et 1989-12-31 00:00:00 UTC
FIT_EPOCH_OFFSET = 631065600


def fit_timestamp(unix_seconds: Optional[float] = None) -> int:
    if unix_seconds is None:
        unix_seconds = time.time()
    return int(unix_seconds) - FIT_EPOCH_OFFSET


# Horodatage fixe (1er janv. 2020 UTC = 1577836800) pour un encodage déterministe.
FIXED_TIME_CREATED = 1577836800 - FIT_EPOCH_OFFSET


# --------------------------------------------------------------------------- #
# Enums de workout (sous-ensemble utile)
# --------------------------------------------------------------------------- #
class Sport:
    RUNNING = 1


class Duration:
    TIME = 0                       # duration_value en millisecondes
    DISTANCE = 1                   # duration_value en centimètres
    OPEN = 5                       # appuyer sur "lap" pour passer
    REPEAT_UNTIL_STEPS_CMPLT = 6   # bloc de répétition


class Target:
    SPEED = 0        # custom low/high en mm/s
    HEART_RATE = 1
    OPEN = 2         # pas de cible
    CADENCE = 3
    POWER = 4


class Intensity:
    ACTIVE = 0
    REST = 1
    WARMUP = 2
    COOLDOWN = 3
    RECOVERY = 4


# --------------------------------------------------------------------------- #
# Structure d'une étape de séance
# --------------------------------------------------------------------------- #
@dataclass
class Step:
    name: str = ""
    duration_type: int = Duration.OPEN
    duration_value: int = 0
    target_type: int = Target.OPEN
    target_value: int = 0
    custom_low: Optional[int] = None
    custom_high: Optional[int] = None
    intensity: int = Intensity.ACTIVE


@dataclass
class Workout:
    name: str
    steps: List[Step] = field(default_factory=list)
    sport: int = Sport.RUNNING

    def add(self, step: Step) -> "Workout":
        self.steps.append(step)
        return self


# --------------------------------------------------------------------------- #
# Écriture des enregistrements (definition + data) sur un canal local 0
# --------------------------------------------------------------------------- #
_STEP_NAME_LEN = 32  # longueur fixe du champ nom d'étape (octets, avec le \0)


def _def_record(global_msg_num: int, fields) -> bytes:
    """fields = liste de (field_def_num, size, base_type_byte)."""
    out = bytearray()
    out.append(0x40)              # header : bit6 = definition, local type 0
    out.append(0x00)             # réservé
    out.append(0x00)             # architecture : little endian
    out += struct.pack("<H", global_msg_num)
    out.append(len(fields))
    for fdn, size, base in fields:
        out += bytes([fdn, size, base])
    return bytes(out)


def _string_field(value: str, length: int) -> bytes:
    raw = value.encode("utf-8")
    if len(raw) > length - 1:
        # tronque sans couper un caractère multioctet en plein milieu
        raw = raw[: length - 1].decode("utf-8", "ignore").encode("utf-8")
    return raw + b"\x00" * (length - len(raw))


def _encode_file_id() -> bytes:
    fields = [
        (0, 1, ENUM[0]),      # type
        (1, 2, UINT16[0]),    # manufacturer
        (2, 2, UINT16[0]),    # product
        (3, 4, UINT32Z[0]),   # serial_number
        (4, 4, UINT32[0]),    # time_created
    ]
    data = bytearray()
    data.append(0x00)  # data record, local type 0
    data.append(5)                              # type = workout
    data += struct.pack("<H", 255)             # manufacturer = development
    data += struct.pack("<H", 0)               # product
    data += struct.pack("<I", 1)               # serial_number (uint32z, !=0)
    # time_created FIGÉ (déterministe) : évite un diff git à chaque régénération.
    data += struct.pack("<I", FIXED_TIME_CREATED)
    return _def_record(0, fields) + bytes(data)


def _encode_workout(wkt: Workout) -> bytes:
    name_len = max(1, len(wkt.name.encode("utf-8")) + 1)
    fields = [
        (4, 1, ENUM[0]),            # sport
        (6, 2, UINT16[0]),          # num_valid_steps
        (8, name_len, STRING[0]),   # wkt_name
    ]
    data = bytearray()
    data.append(0x00)
    data.append(wkt.sport)
    data += struct.pack("<H", len(wkt.steps))
    data += _string_field(wkt.name, name_len)
    return _def_record(26, fields) + bytes(data)


def _encode_steps(wkt: Workout) -> bytes:
    # Définition uniforme réutilisée pour toutes les étapes (canal local 0).
    fields = [
        (254, 2, UINT16[0]),            # message_index
        (0, _STEP_NAME_LEN, STRING[0]),  # wkt_step_name
        (1, 1, ENUM[0]),                # duration_type
        (2, 4, UINT32[0]),              # duration_value
        (3, 1, ENUM[0]),                # target_type
        (4, 4, UINT32[0]),              # target_value
        (5, 4, UINT32[0]),              # custom_target_value_low
        (6, 4, UINT32[0]),              # custom_target_value_high
        (7, 1, ENUM[0]),                # intensity
    ]
    out = bytearray(_def_record(27, fields))

    for idx, s in enumerate(wkt.steps):
        low = s.custom_low if s.custom_low is not None else INVALID[UINT32]
        high = s.custom_high if s.custom_high is not None else INVALID[UINT32]
        rec = bytearray()
        rec.append(0x00)  # data record, local type 0
        rec += struct.pack("<H", idx)
        rec += _string_field(s.name, _STEP_NAME_LEN)
        rec.append(s.duration_type)
        rec += struct.pack("<I", s.duration_value)
        rec.append(s.target_type)
        rec += struct.pack("<I", s.target_value)
        rec += struct.pack("<I", low)
        rec += struct.pack("<I", high)
        rec.append(s.intensity)
        out += rec
    return bytes(out)


def encode(wkt: Workout) -> bytes:
    body = _encode_file_id() + _encode_workout(wkt) + _encode_steps(wkt)

    header = bytearray()
    header.append(14)                 # taille header
    header.append(0x20)              # version protocole 2.0
    header += struct.pack("<H", 2140)  # version profil
    header += struct.pack("<I", len(body))
    header += b".FIT"
    header += struct.pack("<H", fit_crc(bytes(header)))  # CRC du header (12 octets)

    out = bytes(header) + body
    out += struct.pack("<H", fit_crc(body))  # CRC final (sur les data records)
    return out


def write(wkt: Workout, path: str) -> int:
    data = encode(wkt)
    with open(path, "wb") as f:
        f.write(data)
    return len(data)
