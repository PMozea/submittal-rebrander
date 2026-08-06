"""
ahri.py - convert an AHRI certification model number from rev5 to the hybrid.

An AHRI number is a pattern rather than a single unit: digits AHRI does not rate
are printed as "*", and a digit certified in more than one configuration is
printed as a bracketed list, e.g. "[3,8]". A whole family is covered by one
string.

    OABE108**-D1B[3,8]G****-**********-[C,D]1*******

There is no separate AHRI mapping table and there should not be one - it would
be a second thing to keep in step with the workbooks. Instead the pattern is
expanded into concrete rev5 numbers, each is run through the ordinary
convert_model(), and the results are collapsed back into asterisks and brackets
by comparing them digit by digit. Two options that land on the same hybrid digit
collapse to a single digit for free.

AHRI prints the same 37 rev5 digits as Trane, only chunked 9-9-10-9 instead of
9-8-20, so an ordinal maps onto a rev5 digit number by stepping over the d10 and
d19 hyphen slots. Any hyphenation is accepted on input; only the slot count is
enforced.

AHRI prints only the digits material to the rating - d1-d7, d11-d15, d34 and d36 -
and asterisks everything else whether or not the model number determines it, then
stops at d46. That is AHRI policy rather than anything derivable from the
nomenclature, so it lives in MASK. The full 63-digit conversion is returned
alongside, since it is what the tool actually worked out.

Correlated digits are split rather than flattened. One rev5 choice can move
several hybrid digits at once - a condenser bracket spanning air-cooled and
water-cooled moves the outdoor coil, the condenser fan option and the coil fluid
type together. Printing three independent brackets would describe eight machines
when only two exist, so the pattern is emitted as two complete numbers instead.
Brackets that drive a single digit stay brackets.
"""
import itertools
import random
import re

import convert

BOOK_FOR = {"OAB": "OAB5", "OAN": "OAN5"}

SLOTS = 37                       # printed rev5 digits
AHRI_GROUPS = (9, 9, 10, 9)      # how AHRI chunks them, for error messages
HYB_HYPHENS = {10, 20, 30, 40, 50, 60}
SAMPLES = 250                    # random full assignments, to catch joint effects

# AHRI prints only the digits material to the rating and asterisks the rest,
# whether or not the model number determines them. That is a policy, not
# something derivable from the nomenclature, so it is listed here. Taken from
# five published 69-digit AHRI numbers, which agree exactly.
MASK = {1, 2, 3, 4, 5, 6, 7, 11, 12, 13, 14, 15, 34, 36}
LAST_DIGIT = 46                  # AHRI stops here: groups of 9-9-9-9-6
MAX_RESULTS = 24                 # refuse to explode on a heavily bracketed pattern
SEED = 20260804                  # fixed, so the same pattern always gives the same answer


class AhriError(ValueError):
    """Bad input, with a message worth showing the user."""


def digit_no(ordinal):
    """rev5 digit number of the nth printed digit (d10 and d19 are hyphens)."""
    return ordinal if ordinal <= 9 else (ordinal + 1 if ordinal <= 17 else ordinal + 2)


def parse(pattern):
    """-> ([(ordinal, digit_no, kind, value)], slots_padded); kind is fix/alt/wild.

    A pattern that stops short is padded with trailing wildcards rather than
    refused. Trailing asterisks get trimmed somewhere upstream - AHRI's own
    69-digit numbers arrive at both 42 and 45 slots - and padding cannot put a
    wrong digit in the answer, because a wildcard forces anything it influences
    to "*" rather than to a value."""
    toks = [t for seg in pattern.strip().split("-")
            for t in re.findall(r"\[[^\]]*\]|\S", seg)]
    padded = 0
    if len(toks) < SLOTS and SLOTS - len(toks) <= max(AHRI_GROUPS):
        padded = SLOTS - len(toks)
        toks += ["*"] * padded
    if len(toks) != SLOTS:
        counts = [len(re.findall(r"\[[^\]]*\]|\S", seg))
                  for seg in pattern.strip().split("-")]
        detail = ""
        if len(counts) == len(AHRI_GROUPS):
            off = [(i + 1, c, w) for i, (c, w) in enumerate(zip(counts, AHRI_GROUPS))
                   if c != w]
            if off:
                detail = " " + "; ".join(
                    f"group {i} has {c}, expected {w} "
                    f"({abs(w - c)} {'short' if c < w else 'too many'})"
                    for i, c, w in off) + "."
        raise AhriError(
            f"{len(toks)} digit slots, expected {SLOTS}.{detail} Groups should be "
            f"{'-'.join(str(g) for g in AHRI_GROUPS)}, and a bracket counts as one "
            f"slot.")
    out = []
    for o, t in enumerate(toks, 1):
        if t == "*":
            out.append((o, digit_no(o), "wild", None))
        elif t.startswith("["):
            opts = [c.strip().upper() for c in t[1:-1].split(",") if c.strip()]
            if len(opts) < 2:
                raise AhriError(f"slot {o}: {t} needs at least two options")
            if any(len(c) != 1 for c in opts):
                raise AhriError(f"slot {o}: {t} - each option is a single digit")
            out.append((o, digit_no(o), "alt", opts))
        else:
            out.append((o, digit_no(o), "fix", t.upper()))
    return out, padded


def book_for(pattern):
    p = pattern.strip().upper()[:3]
    if p not in BOOK_FOR:
        raise AhriError(f"cabinet {p!r} is not supported - OAB and OAN only")
    return BOOK_FOR[p]


def _block_for(book, d):
    for digs, blk in convert.BOOKS[book].items():
        if d in digs:
            return digs, blk
    return None, None


def _chars_at(book, d):
    """Characters that legitimately appear at rev5 digit `d`."""
    digs, blk = _block_for(book, d)
    if not blk:
        return []
    i = digs.index(d)
    return sorted({c[i] for c in blk[1]
                   if len(c) > i and re.fullmatch(r"[A-Z0-9]", c[i])})


def _assemble(slots, choice):
    """A concrete rev5 number, in Trane's 9-8-20 grouping."""
    ch = [choice[o] for o, _d, _k, _v in slots]
    return "".join(ch[:9]) + "-" + "".join(ch[9:17]) + "-" + "".join(ch[17:])


def _baseline(slots, book):
    """Something legal in every wildcard slot.

    Only the wildcard slots use it, and any hybrid digit a wildcard can move is
    reported as "*", so the choice does not leak into the answer - it just has to
    convert without falling over."""
    base = {}
    for o, d, kind, val in slots:
        if kind == "fix":
            base[o] = val
        elif kind == "alt":
            base[o] = val[0]
        else:
            opts = _chars_at(book, d)
            base[o] = "0" if "0" in opts else (opts[0] if opts else "0")
    return base


def _convert(slots, choice):
    try:
        return convert.convert_model(_assemble(slots, choice))
    except Exception:                                     # noqa: BLE001
        return None, None, None


def _unknown_positions(slots, book, base, ref, ref_notes, rng):
    """Hybrid positions that any wildcard can move - these become "*".

    A deterministic single-digit sweep guarantees every one-digit dependency is
    caught. Random full assignments on top of it catch digits that only move
    when two wildcards move together, which a one-at-a-time sweep would miss.

    Flags are filtered the same way. A flag raised because of the placeholder in
    a wildcard slot says nothing about the pattern, so only flags that survive
    every assignment are kept."""
    wild = [(o, d) for o, d, k, _v in slots if k == "wild"]
    unknown, blind = set(), []
    keep = {tuple(n) for n in (ref_notes or [])}

    for o, d in wild:
        opts = [c for c in _chars_at(book, d) if c != base[o]]
        if not opts:
            blind.append(d)
            continue
        for c in opts:
            trial = dict(base)
            trial[o] = c
            h, n, _b = _convert(slots, trial)
            if h and len(h) == len(ref):
                unknown |= {i for i in range(len(ref)) if h[i] != ref[i]}
                keep &= {tuple(x) for x in (n or [])}

    pool = {o: _chars_at(book, d) or ["0"] for o, d in wild}
    for _ in range(SAMPLES):
        trial = dict(base)
        for o, _d in wild:
            trial[o] = rng.choice(pool[o])
        h, n, _b = _convert(slots, trial)
        if h and len(h) == len(ref):
            unknown |= {i for i in range(len(ref)) if h[i] != ref[i]}
            keep &= {tuple(x) for x in (n or [])}
    return unknown, blind, sorted(keep)


def _alt_influence(slots, base, alt_o, opts, ref):
    """Hybrid positions this one bracket moves, and the value it takes per option."""
    moved = {}
    for c in opts:
        trial = dict(base)
        trial[alt_o] = c
        h, _n, _b = _convert(slots, trial)
        if not h or len(h) != len(ref):
            continue
        for i, ch in enumerate(h):
            moved.setdefault(i, []).append(ch)
    return {i: v for i, v in moved.items() if len(set(v)) > 1}


def _render(slots, book, base, rng):
    """One hybrid pattern, plus the brackets that turned out to be correlated."""
    ref, notes, _bk = _convert(slots, base)
    if not ref:
        raise AhriError("the pattern does not convert - check the fixed digits")

    unknown, blind, notes = _unknown_positions(
        slots, book, base, ref, notes, rng)

    alts = [(o, v) for o, _d, k, v in slots if k == "alt"]
    correlated, seen = [], {}
    for o, opts in alts:
        moved = _alt_influence(slots, base, o, opts, ref)
        # a bracket that only moves digits AHRI asterisks needs no splitting
        moved = {i: v for i, v in moved.items() if (i + 1) in MASK}
        if len(moved) > 1:
            correlated.append((o, opts, moved))

    for pick in itertools.product(*[v for _o, v in alts]) if alts else [()]:
        trial = dict(base)
        for (o, _v), c in zip(alts, pick):
            trial[o] = c
        h, _n, _b = _convert(slots, trial)
        if not h or len(h) != len(ref):
            continue
        for i, ch in enumerate(h):
            seen.setdefault(i, [])
            if ch not in seen[i]:
                seen[i].append(ch)

    tok = {}
    for i in range(len(ref)):
        if (i + 1) in HYB_HYPHENS:
            continue
        if i in unknown:
            tok[i + 1] = "*"
        elif len(seen.get(i, [])) == 1:
            tok[i + 1] = seen[i][0]
        else:
            tok[i + 1] = "[" + ",".join(seen[i]) + "]"
    return tok, correlated, notes, blind


def render_full(tok):
    """All 63 hybrid digits, 7 groups of 9 - what the conversion actually knows."""
    return "".join("-" if n in HYB_HYPHENS else tok[n] for n in range(1, 70))


def render_ahri(tok):
    """AHRI's own form: only the rated digits, the rest asterisked, stopping at
    LAST_DIGIT."""
    segs = []
    for g in range(5):
        wide = 9 if 10 * g + 9 <= LAST_DIGIT else LAST_DIGIT - 10 * g
        segs.append("".join(tok[10 * g + 1 + j] if (10 * g + 1 + j) in MASK else "*"
                            for j in range(wide)))
    return "-".join(segs)


def _pattern_text(slots):
    """Rebuild the AHRI-format string (9-9-10-9) from slots."""
    t = []
    for _o, _d, kind, val in slots:
        t.append("*" if kind == "wild"
                 else ("[" + ",".join(val) + "]" if kind == "alt" else val))
    return ("".join(t[:9]) + "-" + "".join(t[9:18]) + "-"
            + "".join(t[18:28]) + "-" + "".join(t[28:]))


def convert_ahri(pattern, _depth=0, _book=None, _rng=None):
    """Convert an AHRI rev5 pattern to hybrid AHRI pattern(s).

    Returns (results, info). `results` is a list of dicts with 'rev5', 'hybrid'
    and 'pins'; more than one means a correlated bracket had to be split.
    """
    book = _book or book_for(pattern)
    rng = _rng or random.Random(SEED)
    slots, padded = parse(pattern)

    if slots[3][3] == "G":
        raise AhriError("digit 4 is 'G' - that is a rev6 number, which is "
                        "already in hybrid form; this tab converts rev5 only")

    base = _baseline(slots, book)
    tok, correlated, notes, blind = _render(slots, book, base, rng)

    if not correlated or _depth >= 4:
        info = {"book": book, "blind": blind, "notes": notes, "padded": padded,
                "unsplit": [(digit_no(o), opts) for o, opts, _m in correlated]}
        return [{"rev5": _pattern_text(slots), "ahri": render_ahri(tok),
                 "hybrid": render_full(tok), "pins": {}}], info

    # split on the correlated brackets, keeping the separable ones as brackets
    results, info = [], None
    o, opts, moved = correlated[0]
    for c in opts:
        pinned = [(so, sd, "fix", c) if so == o else (so, sd, sk, sv)
                  for so, sd, sk, sv in slots]
        sub, sub_info = convert_ahri(_pattern_text(pinned), _depth + 1, book, rng)
        for r in sub:
            r["pins"][digit_no(o)] = c
            results.append(r)
        info = sub_info
        if len(results) > MAX_RESULTS:
            raise AhriError(
                f"this pattern splits into more than {MAX_RESULTS} numbers - "
                f"narrow the brackets and run it again")
    info = dict(info or {}, padded=padded, split_on=[(digit_no(o), opts, sorted(m + 1 for m in moved))])
    return results, info
