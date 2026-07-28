#!/usr/bin/env python3
"""
convert.py - convert a current KCC/Trane DOAS model number to the new hybrid
(69-position) model number.

    OABD / OAND  (rev5, 37 printed chars)  ->  OABG / OAKG  (63 printed chars)
    OADG / OANG  (rev6, 63 printed chars)  ->  unchanged positions, retargeted codes

Always returns a complete hybrid model number. Every digit carries a note so the
result can be checked; anything marked CHECK involved a real decision.

    python convert.py OAND480C4-D1B4G0LW-A7U09AF6JR6X82B3E500
    python convert.py --audit  OABD108A4-D1B4G1KPG1FC6AFAKM6D25K3A5E0
"""
import argparse
import re
import sys

import codebook as CB
import mapping as M

BOOKS = CB.load_books()

# hybrid printed layout: 6 groups of 9/9/9/18/9/9
GROUPS = [9, 9, 9, 18, 9, 9]

# OAB rev5 motor-HP table is three columns (ECM | Belt | Direct Drive) and the
# sheet leaves the unused ones blank, so it is transcribed explicitly.
OAB5_HP = {
    "ECM":  {"A": "1 kW", "B": "2 kW", "C": "3 kW", "D": "4 kW"},
    "BELT": {"A": "2 HP", "B": "3 HP", "C": "5 HP", "D": "7.5 HP",
             "E": "10 HP", "F": "15 HP"},
    "DD":   {"E": "1 HP-1800 RPM", "F": "1 HP-3600 RPM", "G": "1.5 HP-1800 RPM",
             "H": "1.5 HP-3600 RPM", "J": "2 HP-1800 RPM", "K": "2 HP-3600 RPM",
             "L": "3 HP-1800 RPM", "M": "3 HP-3600 RPM", "N": "5 HP-1800 RPM",
             "P": "5 HP-3600 RPM"},
}


def desc(book, digs, code, col=0):
    """Description for a code, picking a column of a multi-column block."""
    blk = BOOKS[book].get(digs)
    if not blk:
        return None
    vals = blk[1].get(code)
    if not vals:
        return None
    return vals[col] if col < len(vals) else vals[0]


def hyb_lookup(digs, text, col=None):
    """Find the hybrid code whose description matches `text` (exact, then prefix)."""
    if text is None:
        return None
    t = text.strip().lower()
    blk = BOOKS["HYB"].get(digs)
    if not blk:
        return None
    items = blk[1].items()
    for code, vals in items:                       # exact
        for v in (vals if col is None else vals[col:col + 1]):
            if v.strip().lower() == t:
                return code
    for code, vals in items:                       # prefix
        for v in (vals if col is None else vals[col:col + 1]):
            if v.strip().lower().startswith(t):
                return code
    return None


def motor_type(description):
    d = (description or "").lower()
    for key, code, note in M.MOTOR_TYPE:
        if key in d:
            return code, note
    return "X", "CHECK"


def which_book(model):
    cab = model[2].upper()
    return "OAB5" if cab in ("B", "G") else "OAN5"


# ------------------------------------------------------------------ convert
def convert_rev5(model, text=""):
    book = which_book(model)
    raw, leftover = CB.split_model(model, BOOKS[book], "REV5")
    g = lambda n: raw.get((n,), "")
    gm = lambda *ds: raw.get(tuple(ds), "")
    D, notes = {}, []

    def put(digs, code, note="ok", why=""):
        D[digs] = code
        notes.append((digs, code, note, why))

    low = text.lower()

    # --- identity block
    put((1, 2), "OA")
    cab, n = M.CABINET[book].get(g(3), (None, "CHECK"))
    if cab is None:
        put((3,), g(3), "ERROR",
            f"rev5 cabinet {g(3)} is discontinued - no rev6 equivalent")
        cab = g(3)
    else:
        put((3,), cab, n, f"rev5 cabinet {g(3)}")
    put((4,), "G", "ok", "rev D -> rev 6")

    cap3 = gm(5, 6, 7)
    mbh = int(cap3) if cap3.isdigit() else 0
    tons = round(mbh / 12)
    put((5, 6, 7), f"{tons:03d}", "ok" if mbh % 12 == 0 else "CHECK",
        f"{mbh} MBh -> {tons} tons")

    c, n = M.AIRFLOW.get(g(8), ("C", "CHECK"))
    put((8,), c, n, desc(book, (8,), g(8)))
    c, n = M.VOLTAGE.get(g(9), ("3", "ERROR"))
    why = desc(book, (9,), g(9)) or f"unknown rev5 voltage code {g(9)!r}"
    if n == "ERROR":
        why += "  <-- single phase; KCC does not build these. Verify input."
    put((9,), c, n, why)

    c, n = M.COIL.get(g(11), ("0", "CHECK"));   put((11,), c, n, desc(book, (11,), g(11)))
    c, n = M.REHEAT.get(g(12), ("0", "CHECK")); put((12,), c, n, desc(book, (12,), g(12)))
    (c13, c45), n = M.COMPRESSOR.get(g(13), (("0", "0"), "CHECK"))
    put((13,), c13, n, desc(book, (13,), g(13)))
    # Condenser coil, condenser fans and installation location all follow from
    # rev5 digit 4 (heat pump / indoor WSHP) together with digit 14.
    hp = g(4) in M.HEATPUMP_D4
    indoor = g(4) == "F"
    cd = g(14)
    cwhy = desc(book, (14,), cd) or f"d14={cd}"
    if cd == "0":
        c14, c44, n = "0", "0", "ok"
    elif cd in M.COND_WATER:
        c14, c44 = M.COND_WATER[cd], "0"
        n = "ok" if hp else "CHECK"
        cwhy += " -> WSHP (every water-cooled unit is a heat pump)"
        if not hp:
            cwhy += f"; rev5 d4={g(4)} does not indicate a heat pump"
    elif cd in M.COND_AIR:
        base, c44, gone = M.COND_AIR[cd]
        n = "ok"
        if indoor:
            c14, n = base, "ERROR"
            cwhy += " - d4=F is indoor WSHP but this coil is air cooled"
        elif hp:
            c14 = M.ASHP.get(base, base)
            cwhy += " -> ASHP (d4=E)"
        else:
            c14 = base
        if gone:
            n = "CHECK" if n == "ok" else n
            cwhy += " - retired in rev6"
    else:
        c14, c44, n = "0", "0", "ERROR"
        cwhy = f"unrecognised rev5 condenser code {cd!r}"
    put((14,), c14, n, cwhy)
    c51 = "B" if indoor else "A"
    c, n = M.REFRIGERANT.get(g(15), ("0", "CHECK")); put((15,), c, n, desc(book, (15,), g(15)))

    # --- heat: rev5 d20 (type pri/sec) + d21 (fuel) -> hybrid d16/d18
    kind, sec = M.HEAT_PRI_KIND.get(g(20), ("NONE", "0"))
    fuel = g(21)
    if kind == "IF":
        d16 = M.IF_BY_FUEL.get(fuel, "A")
        n16 = "ok" if fuel in M.IF_BY_FUEL else "CHECK"
    else:
        d16, n16 = M.KIND_TO_D16.get(kind, "0"), "ok"
    put((16,), d16, n16, f"{desc(book,(20,),g(20))} + fuel {fuel}")
    d18 = M.DF_BY_FUEL.get(fuel, "1") if sec == "DF" else sec
    put((18,), d18, "ok", "secondary heat type")

    # Heat capacities. Which column applies depends on the heat type, and the two
    # rev5 books do NOT use the same column order (OAB d23 is ELEC|DF, OAN d23 is
    # IF|ELEC|DF), so columns are resolved by their label, never by position.
    KINDCOL = {"IF": "IF", "ESTG": "ELEC", "ESCR": "ELEC", "HW": "HW"}
    lbl = KINDCOL.get(kind)
    if kind == "NONE" or g(22) == "0":
        put((17,), "0", "ok", "no primary heat")
    elif lbl is None:
        put((17,), "X", "ERROR", f"primary heat type {kind} has no capacity column")
    else:
        ci = CB.heat_column(BOOKS[book], (22,), lbl)
        if ci is None:
            put((17,), "X", "ERROR", f"{book} d22 has no {lbl} column")
        else:
            cap = desc(book, (22,), g(22), ci)
            h17 = hyb_lookup((17,), cap, CB.heat_column(BOOKS["HYB"], (17,), lbl))
            put((17,), h17 or "X", "ok" if h17 else "ERROR",
                f"{cap}  [{lbl} column]")

    # Secondary. Hybrid d19 is ELECTRIC only, and direct fired is discontinued.
    SECCOL = {"DF": "DF", "3": "HW", "4": "ELEC", "5": "ELEC"}
    if sec == "0" or g(23) == "0":
        put((19,), "0", "ok", "no secondary heat")
    else:
        slbl = SECCOL.get(sec)
        hsi = CB.heat_column(BOOKS["HYB"], (19,), slbl) if slbl else None
        si = CB.heat_column(BOOKS[book], (23,), slbl) if slbl else None
        scap = desc(book, (23,), g(23), si) if si is not None else None
        if slbl == "DF":
            put((19,), "X", "ERROR",
                f"secondary is direct fired ({scap}) - discontinued, and hybrid "
                "d19 is electric only")
        elif slbl is None:
            put((19,), "X", "ERROR", f"secondary heat type {sec} has no capacity column")
        elif si is None:
            put((19,), "X", "ERROR", f"{book} d23 has no {slbl} column")
        elif hsi is None:
            put((19,), "X", "ERROR",
                f"{scap} - hybrid d19 is electric only, no {slbl} column")
        else:
            h19 = hyb_lookup((19,), scap, hsi)
            put((19,), h19 or "X", "ok" if h19 else "ERROR",
                f"{scap}  [{slbl} column]" +
                ("" if h19 else " - no hybrid equivalent"))

    # --- supply fan: rev5 d16 (type) + d18 (HP) + d17 (wheel)
    mt = desc(book, (16,), g(16))
    c22, n22 = motor_type(mt)
    if book == "OAB5":
        fam = "DD" if "direct" in (mt or "").lower() else ("ECM" if "ecm" in (mt or "").lower() else "BELT")
        hp = OAB5_HP[fam].get(g(18))
    else:
        hp = desc(book, (18,), g(18))
    if g(18) == "0":
        put((21,), "0", "ok", "no supply fan motor")
    else:
        h21 = hyb_lookup((21,), hp)
        put((21,), h21 or "X", "ok" if h21 else "CHECK", hp)
    put((22,), c22, n22, mt)
    wl = desc(book, (17,), g(17))
    wc, wn = M.wheel_code(wl)
    put((23, 24), wc, wn, f"{wl} -> {wc}")

    # --- exhaust fan: rev5 d29 (HP) + d27 (type & dampers) + d28 (wheel)
    if book == "OAB5":
        pmt = desc(book, (27,), g(27))
        fam = "DD" if "direct" in (pmt or "").lower() else ("ECM" if "ecm" in (pmt or "").lower() else "BELT")
        ehp = OAB5_HP[fam].get(g(29)) if g(29) != "0" else "No Powered Exhaust"
    else:
        pmt = desc(book, (27,), g(27))
        ehp = desc(book, (29,), g(29))
    h25 = hyb_lookup((25,), ehp)
    put((25,), h25 or ("0" if g(29) == "0" else "X"),
        "ok" if h25 else "CHECK", ehp)
    c26, n26 = motor_type(pmt)
    put((26,), c26, n26, pmt)
    d39 = "0"
    for key, code in M.EXHAUST_DAMPER:
        if key in (pmt or "").lower():
            d39 = code
    ewl = desc(book, (28,), g(28))
    ewc, ewn = M.wheel_code(ewl)
    put((27, 28), ewc, ewn, f"{ewl} -> {ewc}")

    # --- monitoring, controls
    (c29, c43), n = M.AIRFLOW_MON.get(g(37), (("0", "0"), "CHECK"))
    put((29,), c29, n, desc(book, (37,), g(37)))

    ctl = desc(book, (25, 26), gm(25, 26)) or ""
    cl = ctl.lower()
    if "lab space" in cl:            d31 = "5"
    elif "lab discharge" in cl:      d31 = "6"
    elif "lab multi-zone" in cl:     d31 = "7"
    elif "horizon thrive" in cl:     d31 = "8"
    elif "discharge air" in cl:      d31 = "2"
    elif "space control" in cl:      d31 = "1"
    elif "multi-zone vav" in cl:     d31 = "3"
    elif "single-zone vav" in cl:    d31 = "4"
    elif "non ddc" in cl:            d31 = "0"
    else:                            d31 = "X"
    put((31,), d31, "ok" if d31 != "X" else "CHECK", ctl)
    if "bacnet" in cl:
        put((32,), "4", "ok", "BACnet -> BACnet & MODBUS")
    elif "lon" in cl:
        put((32,), "4", "CHECK", "LON has no hybrid code; BACnet & MODBUS substituted")
    else:
        put((32,), "0", "ok", "no building interface")

    # --- filters / UV
    f = desc(book, (34,), g(34)) or ""
    fl = f.lower()
    uv = "1" if "uvc" in fl else "0"
    base = re.sub(r",?\s*(and\s+)?(alm|with uvc|and uvc|uvc)\b", "", fl)
    base = re.sub(r"\(alm\)", "", base).replace("aluminum mesh intake filters", "").strip(" ,")
    if "tcacs" in base:              d33, n33 = "X", "CHECK"
    elif not base:                   d33, n33 = "0", "ok"
    elif "no filters" in base:       d33, n33 = "0", "ok"
    elif "merv-8" in base and "merv-13" in base: d33, n33 = "D", "ok"
    elif "merv-8" in base and "merv-14" in base: d33, n33 = "E", "ok"
    elif "merv-13" in base:          d33, n33 = "B", "ok"
    elif "merv-14" in base:          d33, n33 = "C", "ok"
    elif "merv-8" in base:           d33, n33 = "A", "ok"
    else:                            d33, n33 = "X", "CHECK"
    put((33,), d33, n33, f)

    # --- ERV: type + the purge artifact
    e = g(31)
    if e == "X":
        purge = "1"
        d34, why = M.erv_from_text(text)
        if d34:
            n34 = "CHECK"
            why = f"rev5 'X' purge artifact - {why}"
        else:
            d34, n34 = "X", "ERROR"
            why = ("rev5 'X' says purge was selected but not the ERV type; "
                   f"{why}. Set d34 by hand.")
    else:
        d34, n34 = M.ERV_TYPE[book].get(e, ("0", "CHECK"))
        why, purge = desc(book, (31,), e), "0"
    if any(k in low for k in ("purge",)):
        purge = "1"
    put((34,), d34, n34, why)
    put((35,), purge, "ok" if purge == "0" else "CHECK",
        "purge recovered from rev5 X artifact" if purge == "1" else "no purge")

    wheel = desc(book, (32,), g(32)) or "0"
    m = re.match(r"^(\d{2})", wheel)
    d36 = M.ERV_DIA_TO_CODE.get(int(m.group(1)), "0") if m else "0"
    put((36,), d36, "ok" if d36 != "0" or wheel == "No ERV" else "CHECK", f"ERC-{wheel}")
    put((37,), "1" if "rotation sensor" in low else "0",
        "ok", "ETO - not encoded in rev5")

    (c38, c62), n = M.DAMPER.get(g(33), (("1", "0"), "CHECK"))
    put((38,), c38, n, desc(book, (33,), g(33)))
    put((39,), d39, "ok", f"exhaust dampers from '{pmt}'")

    # --- electrical
    el = desc(book, (36,), g(36)) or ""
    ell = el.lower()
    d52 = "A" if "convenience outlet" in ell else "0"
    b = ell.replace("w/ convenience outlet", "").replace("w/convenience outlet", "").strip()
    if "dual point" in b:                       d41 = "G"
    elif "65 sccr" in b and "non-fused" in b:   d41 = "C"
    elif "65 sccr" in b:                        d41 = "D"
    elif "65 kaic" in b and "non-fused" in b:   d41 = "E"
    elif "65 kaic" in b:                        d41 = "F"
    elif "non-fused" in b:                      d41 = "A"
    elif "fused" in b:                          d41 = "B"
    elif "terminal block" in b:                 d41 = "0"
    else:                                       d41 = "X"
    put((41,), d41, "ok" if d41 != "X" else "CHECK", el)

    c, n = M.CORROSIVE.get(g(24), ("0", "CHECK"))
    put((42,), c, n, desc(book, (24,), g(24)))
    put((43,), c43, "ok", "outdoor air monitoring")
    put((44,), c44, "ok", "condenser fans, from rev5 d14")
    put((45,), "A" if "sound blanket" in low else c45, "ok", "compressor sound package")
    put((46,), M.SMOKE.get(g(35), "0"), "ok", desc(book, (35,), g(35)))

    acc = (desc(book, (38,), g(38)) or "").lower()
    put((47,), "A" if "hailguard" in acc else "0", "ok", acc or "no accessories")
    if "supply & exhaust" in acc:   d48 = "C"
    elif "supply fan" in acc:       d48 = "A"
    elif "exhaust fan" in acc:      d48 = "B"
    else:                           d48 = "0"
    put((48,), d48, "ok", "service lights")
    put((49,), uv, "ok", "UV lights")

    # --- unit-level options
    put((51,), c51, "ok",
        f"rev5 d4={g(4)} ({desc(book,(4,),g(4))})")
    put((52,), d52, "ok", "convenience outlet")
    put((53,), "1" if ("w/ display" in cl or "w/display" in cl) else "0", "ok", "controls display")
    put((54,), "A" if "reliatel" in low else "0",
        "ok" if "reliatel" in low else "CHECK", "cooling controls - no rev5 digit")
    put((55,), "A" if ("face and bypass" in low or "face & bypass" in low) else "0",
        "ok", "ETO - not encoded in rev5")
    put((56,), "1" if "thumbwheel" in cl else "0", "ok", "thermostat")
    put((57,), g(39) if g(39) in "01234567" else "0", "ok", desc(book, (39,), g(39)))
    put((58,), "A" if "condensate overflow" in low else "0", "ok", "ETO - not encoded in rev5")
    put((59,), "A" if "frostat" in low else "0", "ok", "ETO - not encoded in rev5")
    put((61,), "1" if g(14) in ("3", "8") else "0", "ok", "outdoor coil fluid")
    put((62,), c62, "ok", "minimum damper leakage")
    c, n = M.CONTROLLER.get(g(30), ("00", "CHECK"))
    put((63, 64), c, n, desc(book, (30,), g(30)))

    return assemble(D), notes, book, raw


def assemble(D):
    out = []
    for digs, _t in CB.positions(BOOKS["HYB"], "REV6"):
        out.append(D.get(digs, "0" * len(digs)))
    s = "".join(out) + "00000"          # digits 65-69 reserved
    parts, i = [], 0
    for n in GROUPS:
        parts.append(s[i:i + n]); i += n
    return "-".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--text", default="", help="unit's Product Data text block")
    ap.add_argument("--audit", action="store_true")
    a = ap.parse_args()
    new, notes, book, raw = convert_rev5(a.model, a.text)
    print(f"  old : {a.model}")
    print(f"  new : {new}")
    if a.audit:
        print(f"\n  book: {book}")
        print(f"  {'hybrid':<9}{'code':<6}{'flag':<7}source")
        for digs, code, note, why in notes:
            d = "d" + ",".join(map(str, digs))
            print(f"  {d:<9}{code:<6}{note:<7}{str(why)[:60]}")
        bad = [n for n in notes if n[2] == "CHECK"]
        err = [n for n in notes if n[2] == "ERROR"]
        print(f"\n  {len(bad)} digit(s) flagged CHECK, {len(err)} flagged ERROR")
        for digs, code, _n, why in err:
            print(f"  !! d{','.join(map(str, digs))}: {why}")


if __name__ == "__main__":
    main()


# ------------------------------------------------------- rev6 -> hybrid
# Structurally identical (same 69 positions). Only codes that the hybrid retired
# or redefined need touching.
REV6_FIX = {
    (9,):  {"5": ("3", "ERROR"), "6": ("3", "ERROR"), "9": ("3", "ERROR"),
            "7": ("3", "ERROR"), "8": ("3", "ERROR")},   # 1-ph & 50 Hz: no hybrid code
    (11,): {k: ("X", "CHECK") for k in "KLMNP"},                 # MSP / micro-channel
    (12,): {"C": ("A", "CHECK"), "D": ("B", "CHECK")},           # micro-channel HGRH
    (13,): {"G": ("A", "CHECK")},                                # two-stage scroll
    (14,): {"6": ("2", "CHECK")},                                # ASHP micro-channel
    (21,): {"V": ("X", "CHECK"), "W": ("X", "CHECK")},           # 2 kW / 3 kW dropped
    (25,): {"V": ("X", "CHECK"), "W": ("X", "CHECK")},
    (32,): {"1": ("4", "note"), "2": ("4", "CHECK"), "3": ("4", "CHECK"),
            "5": ("4", "CHECK"), "X": ("4", "CHECK")},           # only BACnet&MODBUS left
}
REV6_WHEEL_LEGACY = {"CA": "355", "CB": "450", "CC": "450 X 2",
                     "DA": "12/9 Single", "DB": "12/9 Dual"}


def convert_rev6(model, text=""):
    raw, _ = CB.split_model(model, BOOKS["REV6"], "REV6")
    D, notes = {}, []
    for digs, _t in CB.positions(BOOKS["HYB"], "REV6"):
        code = raw.get(digs, "0" * len(digs))
        note, why = "ok", desc("REV6", digs, code) or ""
        if digs in REV6_FIX and code in REV6_FIX[digs]:
            new, note = REV6_FIX[digs][code]
            why = f"{why} -> retired in hybrid"
            code = new
        elif digs in ((23, 24), (27, 28)) and code in REV6_WHEEL_LEGACY:
            lbl = REV6_WHEEL_LEGACY[code]
            code, note = M.wheel_code(lbl)
            why = f"legacy wheel {lbl}"
        D[digs] = code
        notes.append((digs, code, note, why))
    return assemble(D), notes, "REV6", raw


def convert_model(model, text=""):
    """Dispatch on digit 4 (major design sequence). Returns (new, notes, book)."""
    m = model.replace("-", "").strip().upper()
    if len(m) < 4:
        raise ValueError(f"not a model number: {model!r}")
    rev = m[3]
    if rev == "G":                       # already revision 6
        new, notes, book, _ = convert_rev6(model, text)
    else:                                # revision 5 (D) and anything older
        new, notes, book, _ = convert_rev5(model, text)
    return new, notes, book
