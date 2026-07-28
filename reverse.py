"""
reverse.py - hybrid -> rev5 lookup.

Scope is deliberately narrow: only OABG and OAKG convert back, because only those
two were rev5 units to begin with (OABD and OAND). OADG and OANG were born as
69-digit numbers and have no rev5 form.

Output is a lookup, not a document edit: the rev5 model number, the pre-approved
ETOs that leave the string, the digit-4 logic that had to be reconstructed, and
anything that could not be represented.
"""
import re

import codebook as CB
import mapping as M

BOOKS = CB.load_books()

# hybrid prefix -> (rev5 cabinet letter, rev5 codebook)
FAMILY = {"OABG": ("B", "OAB5"), "OAKG": ("N", "OAN5")}

# --------------------------------------------------------------- inversions
INV_AIRFLOW = {"C": "A", "D": "B", "E": "C", "F": "D", "A": "E", "B": "F",
               "G": "G", "L": "H"}
INV_VOLTAGE = {"1": "3", "2": "3", "3": "4", "4": "5"}   # rev5 lumps 208-230
INV_COIL = {"0": "0", "B": "A", "C": "B", "D": "D", "E": "E", "F": "F"}
INV_REHEAT = {"0": "0", "A": "1", "B": "2"}
INV_REFRIG = {"0": "0", "1": "A", "2": "B", "3": "C", "4": "D",
              "G": "G", "H": "H", "J": "J"}
INV_DAMPER = {("1", "0"): "0", ("2", "0"): "1", ("3", "0"): "2",
              ("1", "1"): "3", ("2", "1"): "4", ("3", "1"): "5",
              ("6", "0"): "6", ("7", "0"): "7", ("7", "1"): "8",
              ("A", "0"): "A", ("B", "0"): "B", ("C", "0"): "C",
              ("A", "1"): "D", ("B", "1"): "E", ("C", "1"): "F"}
INV_MON = {("0", "0"): "0", ("1", "0"): "1", ("2", "0"): "2", ("1", "1"): "3",
           ("3", "0"): "4", ("3", "1"): "5", ("0", "3"): "6"}
INV_SMOKE = {"0": "0", "1": "1", "2": "2", "3": "3"}
INV_CORROSIVE = {"0": "0", "A": "6", "B": "5", "C": "4", "D": "7", "E": "2", "F": "9"}
INV_CONTROLLER = {"00": "-", "AB": "1", "AC": "1", "AD": "1", "AE": "2",
                  "AF": "3", "AG": "3", "AH": "3", "AK": "4", "AL": "5", "AM": "6"}
# (hybrid d47 hailguards, hybrid d48 service lights) -> rev5 d38.
# The two rev5 books assign these letters differently.
INV_ACCESSORIES = {
    "OAB5": {("0","0"):"0", ("A","0"):"A", ("A","A"):"B", ("0","A"):"C",
             ("A","B"):"D", ("A","C"):"E", ("0","B"):"F", ("0","C"):"G"},
    "OAN5": {("0","0"):"0", ("A","0"):"A", ("0","A"):"B", ("A","A"):"C",
             ("0","B"):"D", ("0","C"):"E", ("A","B"):"F", ("A","C"):"G"},
}

INV_ERV = {"OAN5": {"0": "0", "1": "C", "2": "B", "3": "G", "4": "F"},
           "OAB5": {"0": "0", "1": "A", "2": "B", "3": "C", "4": "D"}}

# (hybrid d13, hybrid d45) -> rev5 d13
INV_COMP = {(a, b): r for r, ((a, b), _n) in M.COMPRESSOR.items()}

# (rev6 air-cooled coil, rev6 d44 fan option) -> rev5 d14
AIR_BY_FAN = {("1", "A"): "1", ("1", "B"): "2", ("1", "C"): "4",
              ("2", "A"): "5", ("2", "B"): "6", ("2", "C"): "7"}


def condenser_back(d14, d44, d51):
    """hybrid d14/d44/d51 -> (rev5 d4, rev5 d14, note). Digit 4 carries the heat
    pump and indoor/outdoor information that rev6 keeps in d14 and d51."""
    if d14 == "0":
        return "D", "0", None
    if d14 in ("1", "2"):                       # air cooled, not a heat pump
        return "D", AIR_BY_FAN.get((d14, d44), "4"), None
    if d14 in ("5", "6"):                       # ASHP - outdoor only
        base = "1" if d14 == "5" else "2"
        note = ("d51=B (indoor) with an ASHP coil - ASHP is outdoor only"
                if d51 == "B" else None)
        return "E", AIR_BY_FAN.get((base, d44), "4"), note
    if d14 in ("7", "8"):                       # WSHP
        return ("F" if d51 == "B" else "E"), ("8" if d14 == "7" else "3"), None
    if d14 in ("3", "4"):                       # plain water cooled - not built
        return "D", ("8" if d14 == "3" else "3"), (
            f"d14={d14} is water-cooled cooling-only, which KCC does not build; "
            "treated as a rev5 water-cooled unit")
    return "D", "0", f"unrecognised hybrid d14={d14!r}"

# hybrid digits with no rev5 position: pre-approved ETOs.
# Labels match the ETO folder names exactly so there is no ambiguity about which
# one to pull.
ETO = {(35,): ("Preapproved ETO - 1 - ERV Purge Addition, (Rev5 Only)", {"1"}),
       (37,): ("Preapproved ETO - 2 - ERV Rotation Sensor Addition, (Rev5 Only)", {"1"}),
       (58,): ("Preapproved ETO - 3 - Condensate Overflow Switch Addition, (Rev5 Only)",
               {"A", "1"}),
       (45,): ("Preapproved ETO - 5 - Compressor Sound Blankets (Rev5 Only)",
               {"A", "B"})}
ETO_SGR = "Preapproved ETO - 4 - Shaft Grounding Ring, (Rev5 Only)"
SGR_CODES = {"3", "4", "7", "8"}          # shaft grounding ring lives in d22/d26

# hybrid digits with no rev5 position AND no ETO
ORPHAN = {(54,): "Cooling controls", (55,): "Face and bypass on indoor coil",
          (59,): "Frostat"}

INV_WHEEL_IN = {v: k for k, v in {**{f"{n}": c for n, c in
                 [(10, "AR"), (12, "AA"), (14, "AC"), (16, "AE"), (18, "AG"),
                  (20, "AJ"), (22, "AL"), (25, "AN")]}}.items()}


def _desc(book, digs, code, col=0):
    blk = BOOKS[book].get(digs)
    if not blk:
        return None
    v = blk[1].get(code)
    return (v[col] if col < len(v) else v[0]) if v else None


def _find_code(book, digs, text, col=0):
    """rev5 code whose description matches `text` (exact, then prefix)."""
    if text is None:
        return None
    t = text.strip().lower()
    blk = BOOKS[book].get(digs)
    if not blk:
        return None
    for code, vals in blk[1].items():
        if col < len(vals) and vals[col].strip().lower() == t:
            return code
    for code, vals in blk[1].items():
        for v in vals:
            if v.strip().lower() == t or v.strip().lower().startswith(t) \
               or t.startswith(v.strip().lower()):
                return code
    return None


def _wheel_label(hcode):
    """hybrid wheel code -> the rev5-style size label, or None."""
    for size, c in [(10, "AR"), (11, "BT"), (12, "AA"), (14, "AC"), (16, "AE"),
                    (18, "AG"), (20, "AJ"), (22, "AL"), (25, "AN")]:
        if c == hcode:
            return f"{size*10}"
    for size, c in [(10, "AS"), (12, "AB"), (14, "AD"), (16, "AF"), (18, "AH"),
                    (20, "AK"), (22, "AM"), (25, "AP")]:
        if c == hcode:
            return f"{size*10}.6"
    for size, c in [(10, "BR"), (12, "BA"), (14, "BC"), (16, "BE"), (18, "BG"),
                    (20, "BJ"), (22, "BL"), (25, "BN")]:
        if c == hcode:
            return f"{size*10} X 2"
    for size, c in [(10, "BS"), (12, "BB"), (14, "BD"), (16, "BF"), (18, "BH"),
                    (20, "BK"), (22, "BM"), (25, "BP")]:
        if c == hcode:
            return f"{size*10}.6 X 2"
    return None


def reverse(model):
    """hybrid -> rev5. Returns dict with model, etos, logic, flags."""
    s = model.replace("-", "").strip().upper()
    prefix = s[:4]
    out = {"input": model, "model": None, "etos": [], "logic": [], "flags": []}

    if prefix not in FAMILY:
        fam = s[:3]
        if fam in ("OAD", "OAN") and s[3:4] == "G":
            out["flags"].append(
                f"{fam}G was never a rev5 model - it has no 39-digit form. "
                "Only OABG and OAKG convert back.")
        else:
            out["flags"].append(f"Unrecognised hybrid prefix {prefix!r}.")
        return out
    cab, book = FAMILY[prefix]

    raw, _ = CB.split_model(model, BOOKS["HYB"], "REV6")
    g = lambda *d: raw.get(tuple(d), "")
    D = {}

    D[(1, 2)] = "OA"
    D[(3,)] = cab

    # ---- digit 4: revision + heat pump + indoor/outdoor, reconstructed
    D[(4,)], cond, cnote = condenser_back(g(14), g(44), g(51))
    if D[(4,)] in ("E", "F"):
        kind = {"E": "heat pump", "F": "indoor WSHP"}[D[(4,)]]
        out["logic"].append(
            f"digit 4 = {D[(4,)]} ({kind}) - from hybrid d14={g(14)} "
            f"({_desc('HYB',(14,),g(14))}) + d51={g(51)}")
    if cnote:
        out["flags"].append(cnote)

    tons = int(g(5, 6, 7)) if g(5, 6, 7).isdigit() else 0
    D[(5, 6, 7)] = f"{tons*12:03d}"
    out["logic"].append(f"digits 5-7 = {tons} tons -> {tons*12} MBh")

    def put(d5, val, why=None):
        D[(d5,)] = val if val is not None else "0"
        if val is None and why:
            out["flags"].append(why)

    put(8, INV_AIRFLOW.get(g(8)), f"d8={g(8)} ({_desc('HYB',(8,),g(8))}) has no rev5 airflow config")
    put(9, INV_VOLTAGE.get(g(9)), f"d9={g(9)} ({_desc('HYB',(9,),g(9))}) has no rev5 voltage")
    if g(9) in ("1", "2"):
        out["logic"].append("digit 9 = 3 (rev5 lumps 208 and 230-240 as one code)")
    put(11, INV_COIL.get(g(11)), f"d11={g(11)} ({_desc('HYB',(11,),g(11))}) has no rev5 coil")
    put(12, INV_REHEAT.get(g(12)), f"d12={g(12)} ({_desc('HYB',(12,),g(12))}) has no rev5 reheat")
    put(13, INV_COMP.get((g(13), "0")) or INV_COMP.get((g(13), g(45))),
        f"d13={g(13)} has no rev5 compressor")
    put(14, cond, f"d14={g(14)} ({_desc('HYB',(14,),g(14))}) has no rev5 condenser")
    put(15, INV_REFRIG.get(g(15)), f"d15={g(15)} has no rev5 capacity control")

    # ---- heat: hybrid d16 + d18 -> rev5 d20 (type) + d21 (fuel)
    h16, h18 = g(16), g(18)
    kind = {"A": ("IF", "1"), "B": ("IF", "7"), "D": ("IF", "2"), "E": ("IF", "8"),
            "H": ("ESTG", "3"), "J": ("ESCR", "3"), "G": ("HW", "5"),
            "K": ("STM", "6"), "0": ("NONE", "0")}.get(h16)
    if kind is None:
        out["flags"].append(f"d16={h16} ({_desc('HYB',(16,),h16)}) has no rev5 heat type")
        kind = ("NONE", "0")
    pri, fuel = kind
    sec = {"0": "0", "1": "DF", "2": "DF", "3": "3", "4": "4", "5": "5", "6": "6"}.get(h18, "0")
    d20 = None
    for code, (k, s2) in M.HEAT_PRI_KIND.items():
        if k == pri and s2 == sec:
            d20 = code
            break
    put(20, d20, f"heat combination d16={h16}/d18={h18} has no rev5 code")
    put(21, fuel)
    # Capacity columns are resolved by label on both sides: the two rev5 books
    # order them differently (OAB d23 is ELEC|DF, OAN d23 is IF|ELEC|DF).
    KINDCOL = {"IF": "IF", "ESTG": "ELEC", "ESCR": "ELEC", "HW": "HW"}
    lbl = KINDCOL.get(pri)
    if pri == "NONE" or g(17) == "0":
        put(22, "0")
    elif lbl is None:
        put(22, None, f"primary heat type {pri} has no rev5 capacity column")
    else:
        hci = CB.heat_column(BOOKS["HYB"], (17,), lbl)
        cap = _desc("HYB", (17,), g(17), hci if hci is not None else 0)
        ci = CB.heat_column(BOOKS[book], (22,), lbl)
        put(22, _find_code(book, (22,), cap, ci) if ci is not None else None,
            f"d17={g(17)} ({cap}) has no rev5 {lbl} capacity")

    # hybrid d19 is ELECTRIC only
    if g(19) == "0":
        put(23, "0")
    else:
        scap = _desc("HYB", (19,), g(19), 0)
        si = CB.heat_column(BOOKS[book], (23,), "ELEC")
        put(23, _find_code(book, (23,), scap, si) if si is not None else None,
            f"d19={g(19)} ({scap}) has no rev5 electric secondary capacity")

    # ---- fans
    put(16, {"1": "0" if book == "OAN5" else "1",
             "2": "1" if book == "OAN5" else None,
             "9": "0" if book == "OAB5" else None,
             "3": "4" if book == "OAN5" else None,
             "4": "4" if book == "OAN5" else None}.get(g(22)),
        f"d22={g(22)} ({_desc('HYB',(22,),g(22))}) has no rev5 motor type")
    if g(22) in SGR_CODES:
        out["etos"].append((ETO_SGR, f"supply fan motor, hybrid d22={g(22)}"))
    put(18, _find_code(book, (18,), _desc("HYB", (21,), g(21))),
        f"d21={g(21)} ({_desc('HYB',(21,),g(21))}) has no rev5 motor HP")
    wl = _wheel_label(g(23, 24))
    put(17, _find_code(book, (17,), wl) if wl else None,
        f"d23,24={g(23,24)} ({_desc('HYB',(23,24),g(23,24))}) has no rev5 wheel")

    if g(26) in SGR_CODES:
        out["etos"].append((ETO_SGR, f"exhaust fan motor, hybrid d26={g(26)}"))
    ewl = _wheel_label(g(27, 28))
    put(28, (_find_code(book, (28,), ewl) if ewl else None) if g(25) != "0" else "0",
        f"d27,28={g(27,28)} has no rev5 exhaust wheel")
    put(29, _find_code(book, (29,), _desc("HYB", (25,), g(25))) if g(25) != "0" else "0",
        f"d25={g(25)} has no rev5 exhaust motor HP")

    # exhaust motor type + dampers recombine into rev5 d27
    damper = {"A": "gravity", "B": "isolation", "C": "barometric"}.get(g(39), "")
    d27 = None
    for code, vals in (BOOKS[book].get((27,)) or ("", {}))[1].items():
        t = vals[0].lower()
        if g(25) == "0" and "no powered exhaust" in t:
            d27 = code; break
        if "direct drive" in t and "vfd" in t and damper and damper in t:
            d27 = code; break
    if d27 is None:
        for code, vals in (BOOKS[book].get((27,)) or ("", {}))[1].items():
            if "direct drive" in vals[0].lower() and "vfd" in vals[0].lower():
                d27 = code; break
    put(27, d27, "could not rebuild rev5 d27 (exhaust motor + dampers)")

    (c29, c43) = (g(29), g(43))
    put(37, INV_MON.get((c29, c43)), f"d29={c29}/d43={c43} has no rev5 monitoring code")

    # ---- controls: hybrid d31/d32/d53/d56 -> rev5 two-char d25,26
    want = {"1": "space control", "2": "discharge air", "3": "multi-zone vav",
            "4": "single-zone vav", "5": "lab space", "6": "lab discharge",
            "7": "lab multi-zone", "8": "horizon thrive"}.get(g(31), "")
    proto = "bacnet" if g(32) == "4" else ""
    disp = "display" if g(53) == "1" else ""
    best = None
    for code, vals in (BOOKS[book].get((25, 26)) or ("", {}))[1].items():
        t = vals[0].lower()
        if want and want in t and (not proto or proto in t) \
           and (("w/ display" in t or "w/display" in t) == bool(disp)):
            best = code; break
    D[(25, 26)] = best or "XX"
    if best is None:
        out["flags"].append(f"could not rebuild rev5 controls from d31={g(31)}, "
                            f"d32={g(32)}, d53={g(53)}")

    f33, uv = g(33), g(49)
    ftxt = {"0": "", "A": "MERV-8", "B": "MERV-13", "C": "MERV-14",
            "D": "MERV-8 & MERV-13", "E": "MERV-8 & MERV-14"}.get(f33, "")
    best = None
    for code, vals in (BOOKS[book].get((34,)) or ("", {}))[1].items():
        t = vals[0].lower()
        has_uv = "uvc" in t
        if ftxt and all(p.lower() in t for p in ftxt.split(" & ")) and has_uv == (uv == "1"):
            best = code; break
    put(34, best, f"d33={f33}/d49={uv} has no rev5 filter code")

    put(31, INV_ERV[book].get(g(34)),
        f"d34={g(34)} ({_desc('HYB',(34,),g(34))}) has no rev5 energy recovery")
    dia = {v: k for k, v in M.ERV_DIA_TO_CODE.items()}.get(g(36))
    put(32, _find_code(book, (32,), str(dia)) if dia else "0",
        f"d36={g(36)} has no rev5 ERV wheel size")
    put(33, INV_DAMPER.get((g(38), g(62))), f"d38={g(38)}/d62={g(62)} has no rev5 damper code")
    put(35, INV_SMOKE.get(g(46)), f"d46={g(46)} ({_desc('HYB',(46,),g(46))}) has no rev5 smoke option")

    el = (_desc("HYB", (41,), g(41)) or "")
    if g(52) == "A":
        el += " w/Convenience Outlet"
    put(36, _find_code(book, (36,), el), f"d41={g(41)}/d52={g(52)} has no rev5 electrical code")
    put(24, INV_CORROSIVE.get(g(42)), f"d42={g(42)} ({_desc('HYB',(42,),g(42))}) has no rev5 corrosive pkg")

    put(38, INV_ACCESSORIES[book].get((g(47), g(48))),
        f"d47={g(47)}/d48={g(48)} has no rev5 accessories code")
    put(30, INV_CONTROLLER.get(g(63, 64)), f"d63,64={g(63,64)} has no rev5 controller template")
    if g(63, 64) in ("AB", "AC", "AD", "AF", "AG", "AH"):
        out["logic"].append(f"digit 30 lumps several templates - {g(63,64)} "
                            f"({_desc('HYB',(63,64),g(63,64))}) collapses to one rev5 code")
    put(39, g(57) if g(57) in "01234567" else "0")

    # ---- ETOs and orphans
    for digs, (name, on) in ETO.items():
        if g(*digs) in on:
            out["etos"].append((name, f"hybrid d{digs[0]}={g(*digs)}"))
    for digs, name in ORPHAN.items():
        v = g(*digs)
        if v not in ("0", ""):
            out["flags"].append(
                f"d{digs[0]}={v} ({name}: {_desc('HYB',digs,v)}) - no rev5 digit "
                "and no pre-approved ETO. Handle separately.")

    # ---- assemble
    parts = []
    for digs, _t in CB.positions(BOOKS[book], "REV5"):
        parts.append(D.get(digs, "0" * len(digs)))
    s5 = "".join(parts)
    out["model"] = f"{s5[:9]}-{s5[9:17]}-{s5[17:]}" if book == "OAN5" else f"{s5[:9]}-{s5[9:]}"
    out["book"] = book
    return out
