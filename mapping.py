"""
mapping.py - rev5 -> hybrid (rev6 "Viking OA") model-number translation rules.

Everything here is table-driven. Nothing falls through: when a rev5 option has no
exact hybrid twin we still emit the closest valid code and record a note, so the
converter always produces a complete 63-character hybrid model number.

Notes carry a level:
   ok      straight equivalent
   note    a defensible choice worth a glance
   CHECK   a real decision was made; verify before releasing the number
"""

# ----------------------------------------------------------------- cabinet
# OABD -> OABG and OAND -> OAKG are confirmed. The other rev5 cabinets follow the
# same one-step shift down the B/D/K/N ladder and are marked for confirmation.
CABINET = {
    "OAB5": {"B": ("B", "ok"), "G": ("D", "CHECK")},
    "OAN5": {"N": ("K", "ok"), "K": ("D", "CHECK"), "D": ("B", "CHECK")},
}

# --------------------------------------------------------------- simple maps
AIRFLOW = {  # rev5 d8 -> hybrid d8   (letters are reassigned)
    "A": ("C", "ok"), "B": ("D", "ok"), "C": ("E", "ok"), "D": ("F", "ok"),
    "E": ("A", "ok"), "F": ("B", "ok"),
    "G": ("G", "CHECK"),   # Vert/Split Vert Return-Exhaust -> Vert/Vert/Vert ded exh
    "H": ("L", "CHECK"),   # Horiz/Split Vert Return-Exhaust -> Horiz/Vert/Vert ded exh
}

VOLTAGE = {  # rev5 d9 -> hybrid d9
    # KCC does not build single-phase units, and the hybrid has no single-phase
    # code, so codes 1 and 2 should never appear. If one does, the input is
    # suspect (bad parse / wrong codebook) - flag it rather than quietly
    # emitting a three-phase code.
    "1": ("3", "ERROR"),   # 115/60/1  - single phase, not manufactured
    "2": ("3", "ERROR"),   # 208-230/60/1 - single phase, not manufactured
    "3": ("1", "CHECK"),   # rev5 lumps 208-230; hybrid splits 208 / 230-240
    "4": ("3", "ok"),
    "5": ("4", "ok"),
}

COIL = {  # rev5 d11 -> hybrid d11
    "0": ("0", "ok"), "A": ("B", "ok"), "B": ("C", "ok"),
    "C": ("C", "note"),          # 4-row interlaced -> DX 4-Row
    "D": ("D", "ok"), "E": ("E", "ok"),
    "F": ("F", "CHECK"),         # Glycol/CHW -> hybrid splits 4-row (F) / 6-row (G)
    "G": ("X", "CHECK"),         # DX 4-Row w/ MSP: hybrid K-P are Future use
}

REHEAT = {  # rev5 d12 -> hybrid d12
    "0": ("0", "ok"), "1": ("A", "ok"), "2": ("B", "ok"),
    "3": ("A", "CHECK"),         # Micro Channel Modulating: hybrid C is Future use
    "4": ("B", "CHECK"),         # Micro Channel On/Off:     hybrid D is Future use
}

# rev5 d13 -> (hybrid d13 compressor, hybrid d45 sound package)
COMPRESSOR = {
    "0": (("0", "0"), "ok"), "A": (("A", "0"), "ok"), "B": (("B", "0"), "ok"),
    "C": (("C", "0"), "ok"), "D": (("D", "0"), "ok"), "E": (("E", "0"), "ok"),
    "F": (("A", "A"), "ok"), "G": (("B", "A"), "ok"), "H": (("C", "A"), "ok"),
    "J": (("D", "A"), "ok"), "K": (("E", "A"), "ok"), "L": (("F", "0"), "ok"),
    "M": (("F", "A"), "ok"),
}

# rev5 d14 -> (hybrid d14 outdoor coil, hybrid d44 condenser fan option)
CONDENSER = {
    "0": (("0", "0"), "ok"),
    "1": (("1", "A"), "ok"),
    "2": (("1", "B"), "ok"),     # head pressure on/off -> Passive HPC
    "3": (("4", "0"), "ok"),     # WC Copper/Steel
    "4": (("1", "C"), "ok"),     # head pressure variable speed -> Active HPC
    "5": (("2", "A"), "ok"),
    "6": (("2", "B"), "ok"),
    "7": (("2", "C"), "ok"),
    "8": (("3", "0"), "ok"),     # WC Copper/Nickel
}

REFRIGERANT = {  # rev5 d15 -> hybrid d15
    "0": ("0", "ok"), "A": ("1", "ok"), "B": ("2", "ok"), "C": ("3", "ok"),
    "D": ("4", "ok"),
    "E": ("0", "CHECK"),         # HGBP 1st circuit: no hybrid equivalent
    "F": ("0", "CHECK"),         # HGBP 1st & 2nd:   no hybrid equivalent
    "G": ("G", "ok"), "H": ("H", "ok"), "J": ("J", "ok"),
}

# rev5 d20 -> (primary heat kind, hybrid d18 secondary heat type)
HEAT_PRI_KIND = {
    "0": ("NONE", "0"), "A": ("IF", "0"), "B": ("NONE", "DF"),
    "C": ("ESTG", "0"), "D": ("ESCR", "0"), "E": ("IF", "DF"),
    "F": ("ESCR", "DF"), "G": ("IF", "4"), "H": ("ESCR", "4"),
    "J": ("HW", "0"), "K": ("STM", "0"), "L": ("NONE", "4"),
    "M": ("ESTG", "DF"), "N": ("ESTG", "4"), "P": ("HW", "DF"),
    "Q": ("HW", "4"), "R": ("STM", "DF"), "S": ("STM", "4"),
    "T": ("IF", "5"), "U": ("ESCR", "5"), "V": ("NONE", "5"),
    "W": ("ESTG", "5"), "Y": ("HW", "5"), "Z": ("STM", "5"),
    "X": ("SPECIAL", "X"),
}

# (primary kind, rev5 d21 fuel) -> hybrid d16
IF_BY_FUEL = {"1": "A", "7": "B", "2": "D", "8": "E"}   # NG80 NG81 LP80 LP81
KIND_TO_D16 = {"ESTG": "H", "ESCR": "J", "HW": "G", "STM": "K",
               "NONE": "0", "SPECIAL": "X"}
DF_BY_FUEL = {"1": "1", "7": "1", "2": "2", "8": "2"}   # DF NG / DF LP

# which column of the 3-column heat-capacity table applies
KIND_TO_HEATCOL = {"IF": 0, "ESTG": 1, "ESCR": 1, "HW": 2,
                   "NONE": 0, "SPECIAL": 0}

# rev5 motor-type description -> hybrid d22 / d26  (ODP is the default family)
MOTOR_TYPE = [
    ("shaft grounding",            "3", "ok"),
    ("vfd by others",              "2", "ok"),
    ("ecm",                        "9", "ok"),
    ("belt drive",                 "X", "CHECK"),   # no belt drive in hybrid
    ("direct drive",               "1", "ok"),
    ("special",                    "X", "ok"),
    ("no powered exhaust",         "0", "ok"),
    ("no supply fan",              "0", "ok"),
]

EXHAUST_DAMPER = [("gravity", "A"), ("barometric", "C"), ("isolation", "B")]

# rev5 d24 -> hybrid d42
CORROSIVE = {
    "0": ("0", "ok"),
    "1": ("C", "CHECK"),   # S/S Interior + S/S Coil Casing -> hybrid has no combo
    "2": ("E", "ok"),      # S/S Interior, Eco Coated Coils
    "3": ("X", "CHECK"),   # Copper/Copper evap: no hybrid equivalent
    "4": ("C", "ok"),      # S/S Coil Casing
    "5": ("B", "ok"),      # S/S Interior
    "6": ("A", "ok"),      # Eco Coated Coils
    "7": ("D", "ok"),      # S/S Coil Casing with Eco Coated Coils
    "8": ("X", "CHECK"),   # Copper/Copper Evap, HGRH Coils
    "9": ("F", "ok"),      # Corrosion Resistant Package
}

# rev5 d33 -> (hybrid d38 damper, hybrid d62 min leakage class)
DAMPER = {
    "0": (("1", "0"), "ok"), "1": (("2", "0"), "ok"), "2": (("3", "0"), "ok"),
    "3": (("1", "1"), "ok"), "4": (("2", "1"), "ok"), "5": (("3", "1"), "ok"),
    "6": (("6", "0"), "ok"), "7": (("7", "0"), "ok"), "8": (("7", "1"), "ok"),
    "A": (("A", "0"), "ok"), "B": (("B", "0"), "ok"), "C": (("C", "0"), "ok"),
    "D": (("A", "1"), "ok"), "E": (("B", "1"), "ok"), "F": (("C", "1"), "ok"),
}

# rev5 d37 -> (hybrid d29 piezo rings, hybrid d43 outdoor air monitoring)
AIRFLOW_MON = {
    "0": (("0", "0"), "ok"), "1": (("1", "0"), "ok"), "2": (("2", "0"), "ok"),
    "3": (("1", "1"), "ok"), "4": (("3", "0"), "ok"), "5": (("3", "1"), "ok"),
    "6": (("0", "3"), "ok"),          # OA monitoring for direct-fired -> DF profile plates
}

SMOKE = {"0": "0", "1": "1", "2": "2", "3": "3"}

# rev5 d30 -> hybrid d63,64
CONTROLLER = {
    "-": ("00", "ok"), "0": ("00", "ok"),
    "1": ("AB", "CHECK"),   # rev5 lumps v8.X / v9.X / v10.X -> AB / AC / AD
    "2": ("AE", "ok"),
    "3": ("AF", "CHECK"),   # rev5 lumps v11.1-v11.3 -> AF / AG / AH
    "4": ("AK", "ok"), "5": ("AL", "ok"), "6": ("AM", "ok"),
}

# --------------------------------------------------------- ERV (d31 -> d34/d35)
# rev5 d31 = "X" is a known selection-tool artifact: rev5 had no purge digit, so
# choosing an ERV with purge dropped X into the type digit. The type is recovered
# from the submittal text (composite w/ bypass in every observed case) and purge
# is set on the hybrid's dedicated digit 35.
ERV_TYPE = {
    "OAN5": {"0": ("0", "ok"), "A": ("1", "CHECK"), "B": ("2", "ok"),
             "C": ("1", "ok"), "D": ("1", "CHECK"), "E": ("3", "CHECK"),
             "F": ("4", "ok"), "G": ("3", "ok"), "H": ("3", "CHECK")},
    "OAB5": {"0": ("0", "ok"), "A": ("1", "ok"), "B": ("2", "ok"),
             "C": ("3", "ok"), "D": ("4", "ok")},
}
ERV_X_FALLBACK = ("1", "purge artifact: type from text, purge set on d35")

# rev5 ERV wheel label -> hybrid d36 (first two digits are the diameter)
ERV_DIA_TO_CODE = {30: "A", 36: "B", 41: "C", 46: "D", 52: "E", 58: "F",
                   64: "G", 68: "H", 74: "J", 81: "K", 86: "L", 92: "M"}

# ---------------------------------------------------- fan wheel (CF <-> ANPA)
# rev5 names the wheel by size: CFnnn -> nnn/10 inches, ".6" = 60% width,
# "x2" = dual. OAB also carries four legacy metric Comefri sizes.
_SINGLE = {10: "AR", 11: "BT", 12: "AA", 14: "AC", 16: "AE", 18: "AG",
           20: "AJ", 22: "AL", 25: "AN"}
_SINGLE60 = {10: "AS", 12: "AB", 14: "AD", 16: "AF", 18: "AH", 20: "AK",
             22: "AM", 25: "AP"}
_DUAL = {10: "BR", 11: "BT", 12: "BA", 14: "BC", 16: "BE", 18: "BG",
         20: "BJ", 22: "BL", 25: "BN"}
_DUAL60 = {10: "BS", 12: "BB", 14: "BD", 16: "BF", 18: "BH", 20: "BK",
           22: "BM", 25: "BP"}
_MM_TO_IN = {315: 12, 355: 14, 450: 18, 500: 20}


def wheel_code(label):
    """'180 X 2' -> BG, '140.6' -> AD, '355' -> AC. Returns (code, note)."""
    import re
    if label is None:
        return "XX", "CHECK"
    s = str(label).upper().replace("CF", "").replace("ANPA", "").strip()
    if s in ("0", "NO ERV", "NO SUPPLY FAN", "NO POWERED EXHAUST", ""):
        return "00", "ok"
    dual = bool(re.search(r"X\s*2", s))
    s = re.sub(r"X\s*2", "", s).strip()
    sixty = s.endswith(".6")
    if sixty:
        s = s[:-2]
    try:
        n = int(float(s))
    except ValueError:
        return "XX", "CHECK"          # 12/9 T2 & 12/9 BT belt-drive wheels
    note = "ok"
    if n in _MM_TO_IN:
        n = _MM_TO_IN[n]
        note = "note"                 # metric Comefri size converted to inches
    elif n >= 100:
        n //= 10
    tbl = (_DUAL60 if sixty else _DUAL) if dual else (_SINGLE60 if sixty else _SINGLE)
    code = tbl.get(n)
    return (code, note) if code else ("XX", "CHECK")


# --------------------------------------------------------- ETO keyword scan
# The five "Rev5 Only" pre-approved ETOs are native digits on the hybrid. They are
# not encoded anywhere in a rev5 model number, so they default to 0 and are only
# raised if the submittal text mentions them.
ETO_KEYWORDS = {
    "d35_purge":       (["erv purge", "wheel purge", "purge"], "1"),
    "d37_rotation":    (["rotation sensor"], "1"),
    "d58_condensate":  (["condensate overflow"], "A"),
    "d45_blankets":    (["sound blanket"], "A"),
    "d59_frostat":     (["frostat"], "A"),
    "d55_facebypass":  (["face and bypass", "face & bypass"], "A"),
}
