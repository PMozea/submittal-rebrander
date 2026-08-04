"""
modelswap.py - find KCC/Trane DOAS model numbers in a submittal PDF, convert them
to the new hybrid nomenclature, and rewrite them in place.

Long numbers are wrapped the way Trane's own submittal software already does it:
fill the cell, break with a hyphen, continue on the next line. The type size is
stepped down until the wrapped block clears whatever sits below it, so nothing
else on the page has to move.

Hand-edited submittals (ETO revisions) need extra care on three counts, all of
them handled below:
  - characters are patched by white-boxing and retyping, so one model number can
    arrive as a dozen separate spans on a single line (see _runs)
  - those patch boxes are white-filled and white-stroked, and must not be read as
    table geometry (see _visible)
  - a large ETO stamp often sits under the table, and the row has to be able to
    push it down along with the tag line (see _has_room)
"""
import re

import fitz

from convert import convert_model


def _alias(font):
    return "hebo" if "bold" in (font or "").lower() else "helv"

# OA + cabinet + revision + 3-digit size + 2 + at least one more hyphenated group
MODEL_RE = re.compile(r"OA[BDGKN][A-G]\d{3}[A-Z0-9]{2}(?:-[A-Z0-9]+)+")

VALID_LEN = {37, 63}          # printed chars, hyphens excluded (rev5 / rev6)

# A near miss worth reporting: long enough to be a mangled model number rather
# than an unrelated code that happens to fit the pattern.
NEAR_MISS = range(20, 71)

# Trane sets a wrapped model number in 9pt on a 10pt pitch and grows the table
# row to suit: a single-line row closes at y=103.45, a two-line row at y=109.46.
# We match that. If the row cannot be grown safely we fall back to shrinking the
# type so it fits the row as-is.
BASE_SIZE = 9.0
MIN_SIZE = 6.5
LEAD = 1.112                  # 10.01pt pitch at 9pt, as Trane uses
RULE_GAP = 3.62               # gap from the last baseline to the closing rule

# Baseline jitter between retyped character patches on one line, measured at
# 0.32pt on the Mt Horeb ETO submittal. Well under the 10pt line pitch.
BASELINE_TOL = 1.5

# The row is already tall enough if its rule clears the last baseline by this
# much. Native two-line rev6 rows sit 3.04pt below the last baseline, slightly
# tighter than RULE_GAP, and must not be nudged for the sake of half a point.
GROW_SLACK = 1.0

# Ink bottom of a span, as a fraction of type size below the baseline. A span
# bbox is generous - a 24pt stamp reports 33pt of height - which made the old
# room test refuse moves that were geometrically fine.
DESCENDER = 0.15


def _wrap(s, font, size, width):
    """Fill to the cell width, break with a hyphen, continue - the way Trane's
    own submittals already print a long number.

    The model number already contains hyphens (they stand in for the unused
    digit positions), so a break that lands on one must not add a second."""
    lines, rest = [], s
    while rest:
        if font.text_length(rest, size) <= width:
            lines.append(rest)
            break
        # widest prefix that fits. A prefix already ending in a hyphen needs no
        # second one, so it must not be measured with an extra character - that
        # was breaking a nine-digit group early.
        def _fits(n):
            cand = rest[:n]
            return font.text_length(cand if cand.endswith("-") else cand + "-",
                                    size) <= width
        cut = len(rest)
        while cut > 1 and not _fits(cut):
            cut -= 1
        # prefer to break on a hyphen the number already carries, the way the
        # native rev6 pages do (they break at the digit-40 hyphen)
        nat = rest.rfind("-", 1, cut + 1)
        if nat >= cut * 0.5:
            lines.append(rest[:nat + 1])
            rest = rest[nat + 1:]
        else:
            lines.append(rest[:cut] + "-")
            rest = rest[cut:]
    return lines


# --------------------------------------------------------------------------
# finding the number
# --------------------------------------------------------------------------

def _page_spans(page):
    return [s for blk in page.get_text("dict")["blocks"]
            for line in blk.get("lines", [])
            for s in line["spans"] if s["text"].strip()]


def _runs(page, spans=None):
    """Spans grouped into visual lines, then into runs of horizontally touching
    spans, each run joined back into one string.

    Matching span by span misses any number the editor has broken up, so the
    line is rebuilt first. Lines are clustered on the baseline, anchored on the
    first span so a slowly drifting sequence cannot chain itself together."""
    spans = _page_spans(page) if spans is None else spans
    lines = []
    for s in sorted(spans, key=lambda s: (s["origin"][1], s["bbox"][0])):
        for ln in lines:
            if abs(s["origin"][1] - ln["y"]) <= BASELINE_TOL:
                ln["spans"].append(s)
                break
        else:
            lines.append({"y": s["origin"][1], "spans": [s]})

    runs = []
    for ln in lines:
        ln["spans"].sort(key=lambda s: s["bbox"][0])
        cur = []
        for s in ln["spans"]:
            if cur and s["bbox"][0] - cur[-1]["bbox"][2] > max(1.5, 0.35 * s["size"]):
                runs.append(cur)
                cur = []
            cur.append(s)
        if cur:
            runs.append(cur)

    out = []
    for r in runs:
        out.append({"text": "".join(s["text"] for s in r), "spans": r,
                    "x0": r[0]["bbox"][0],
                    "top": min(s["bbox"][1] for s in r),
                    "base": r[0]["origin"][1]})
    return out


def _covering(run, a, b):
    """The spans of `run` that carry characters [a, b) of its joined text."""
    out, off = [], 0
    for s in run["spans"]:
        end = off + len(s["text"])
        if off < b and end > a:
            out.append(s)
        off = end
    return out


def _find(page, spans=None):
    """Model-number occurrences, rebuilt from however many spans carry them.

    Returns (found, rejects): `found` is a list of (model, spans); `rejects`
    holds anything that looked like a model number but did not validate, so the
    caller can warn instead of dropping it silently."""
    runs = _runs(page, spans)
    found, rejects, used = [], [], set()
    for i, run in enumerate(runs):
        if i in used:
            continue
        m = MODEL_RE.search(run["text"])
        if not m:
            continue
        used.add(i)
        # MODEL_RE cannot match a trailing hyphen (its last group needs a
        # character after the "-"), but a line that ends on one is a wrapped
        # number carrying a real hyphen at an unused digit. Keep it, or the
        # continuation below is never looked for.
        end = m.end()
        if run["text"][end:end + 1] == "-":
            end += 1
        parts = [run["text"][m.start():end]]
        group = list(_covering(run, m.start(), end))
        last_top = run["top"]
        # a continuation sits just below, left-aligned, when the line ends "-"
        while parts[-1].endswith("-"):
            nxt = None
            for j, c in enumerate(runs):
                if j in used:
                    continue
                if (abs(c["x0"] - run["x0"]) < 1.5
                        and 0 < c["top"] - last_top < 14):
                    nxt = j
                    break
            if nxt is None:
                break
            used.add(nxt)
            cont = runs[nxt]
            # the trailing "-" is a real hyphen standing in for an unused digit
            # (e.g. d40), not a soft wrap hyphen, so it is kept
            parts.append(cont["text"].strip())
            group.extend(cont["spans"])
            last_top = cont["top"]
        model = "".join(parts)
        printed = len(model.replace("-", ""))
        if printed in VALID_LEN:
            found.append((model, group))
        elif printed in NEAR_MISS:
            rejects.append((model, printed))
    return found, rejects


# --------------------------------------------------------------------------
# page geometry
# --------------------------------------------------------------------------

def _white(v):
    return v is None or all(c > 0.98 for c in v)


def _visible(dr):
    """False for a drawing that cannot appear on paper - no visible stroke and no
    visible fill.

    The ETO edits patch characters with white-filled, white-stroked boxes. Those
    are not table borders, and reading them as such put the cell's right edge at
    515.0 instead of 526.6 and the row rule at 98.5 instead of 103.45."""
    return not (_white(dr.get("color")) and _white(dr.get("fill")))


def _rules(page, y_lo, y_hi):
    """Horizontal segments (grouped by y) and vertical segments in a band."""
    horiz, vert = {}, {}
    for dr in page.get_drawings():
        if not _visible(dr):
            continue
        w = dr.get("width") or 0.5
        col = dr.get("color")
        for it in dr["items"]:
            segs_h, segs_v = [], []
            if it[0] == "l":
                p1, p2 = it[1], it[2]
                if abs(p1.y - p2.y) < 0.6:
                    segs_h = [(min(p1.x, p2.x), max(p1.x, p2.x), p1.y)]
                elif abs(p1.x - p2.x) < 0.6:
                    segs_v = [(p1.x, min(p1.y, p2.y), max(p1.y, p2.y))]
            elif it[0] == "re":
                r = it[1]
                segs_h = [(r.x0, r.x1, r.y0), (r.x0, r.x1, r.y1)]
                segs_v = [(r.x0, r.y0, r.y1), (r.x1, r.y0, r.y1)]
            for a, b, y in segs_h:
                if y_lo <= y <= y_hi:
                    horiz.setdefault(round(y, 2), []).append((a, b, w, col))
            for x, a, b in segs_v:
                if b > y_lo and a < y_hi:
                    vert.setdefault(round(x, 2), []).append((a, b, w, col))
    return horiz, vert


def _row_rule(page, x0, model_top):
    """y of the rule that closes the model number's table row."""
    horiz, _vert = _rules(page, model_top + 2, model_top + 80)
    for y in sorted(horiz):
        if any(a <= x0 + 2 and b >= x0 + 40 for a, b, _w, _c in horiz[y]):
            return y
    return None


def _grow_row(page, x0, model_top, needed_bottom, rule_y):
    """Push the row's closing rule down so a taller model number fits, the way
    Trane's own pages do. Returns (delta, rule_y, x_lo, x_hi, segs, cols) or None."""
    if rule_y is None or needed_bottom <= rule_y + GROW_SLACK:
        return None                                   # already tall enough
    horiz, vert = _rules(page, model_top + 2, model_top + 80)
    if rule_y not in horiz:
        return None
    delta = round(needed_bottom - rule_y, 2)
    segs = horiz[rule_y]
    x_lo = min(a for a, _b, _w, _c in segs)
    x_hi = max(b for _a, b, _w, _c in segs)
    # verticals that stop at this rule need extending to the new one
    cols = [(x, v[0][2], v[0][3]) for x, v in vert.items()
            if any(abs(b - rule_y) < 0.6 for _a, b, _w, _c in v)]
    return delta, rule_y, x_lo, x_hi, segs, cols


def _cell_right(page, x0, y0, y1, fallback):
    """Right edge of the table cell holding the model number, from its border rule.

    Deriving the wrap width from the existing text is unreliable: where the source
    PDF already wrapped a long number, the first line can be far narrower than the
    cell actually is.
    """
    best = None
    for dr in page.get_drawings():
        if not _visible(dr):
            continue
        for it in dr["items"]:
            xs = []
            if it[0] == "l":
                p1, p2 = it[1], it[2]
                if abs(p1.x - p2.x) < 0.6 and min(p1.y, p2.y) < y1 + 6 and max(p1.y, p2.y) > y0 - 6:
                    xs = [p1.x]
            elif it[0] == "re":
                r = it[1]
                if r.y0 < y1 + 6 and r.y1 > y0 - 6:
                    xs = [r.x0, r.x1]
            for x in xs:
                if x > x0 + 40 and (best is None or x < best):
                    best = x
    return (best - 2.0) if best else fallback


def _ink_bottom(sp):
    return sp["origin"][1] + DESCENDER * sp["size"]


def _clearance(page, group, x0, x1, spans=None, skip=()):
    """Lowest y a rewritten block may reach before touching the text below it.

    `skip` holds spans that are going to be moved out of the way, so they must
    not also be counted as the obstruction."""
    bottom = max(g["bbox"][3] for g in group)
    limit = page.rect.height
    for s in (_page_spans(page) if spans is None else spans):
        if s in group or s in skip:
            continue
        b = s["bbox"]
        if b[1] >= bottom - 1 and b[2] > x0 and b[0] < x1 + 40:
            limit = min(limit, b[1])
    return limit


def _block_below(page, rule_y, reach=30.0, spans=None):
    """Spans sitting just under the row rule (the Tag line, and any ETO stamp),
    and the first thing below them."""
    block, after = [], []
    for sp in (_page_spans(page) if spans is None else spans):
        y0 = sp["bbox"][1]
        if rule_y < y0 < rule_y + reach:
            block.append(sp)
        elif y0 >= rule_y + reach:
            after.append(y0)
    return block, (min(after) if after else 1e9)


def _has_room(block, group, delta, spans, gap=0.5):
    """Can every span in `block` move down by `delta` without running into
    something that is staying put?

    Compared column by column: a stamp in the middle of the page does not
    collide with a label on the left margin, and the old whole-page minimum
    refused every move on an ETO-stamped sheet. Returns (ok, margin)."""
    margin = 1e9
    for sp in block:
        bot = _ink_bottom(sp)
        x0, x1 = sp["bbox"][0], sp["bbox"][2]
        for o in spans:
            if o in block or o in group:
                continue
            ob = o["bbox"]
            if ob[2] <= x0 or ob[0] >= x1:      # different column
                continue
            if ob[1] < bot - 0.1:               # not below
                continue
            margin = min(margin, ob[1] - (bot + delta))
    return margin > gap, margin


# --------------------------------------------------------------------------

def swap_models(doc, report, pages=None):
    """Convert every model number in `doc`. Returns a list of (page, old, new)."""
    font = fitz.Font("helv")
    done = []
    for pno in range(len(doc)):
        if pages is not None and pno not in pages:
            continue
        page = doc[pno]
        spans = _page_spans(page)
        hits, rejects = _find(page, spans)
        for text, printed in rejects:
            report["warnings"].append(
                f"p{pno+1}: {text} looks like a model number but has {printed} "
                f"printed digits, not 37 or 63 - not converted")
        if not hits:
            continue
        page_text = page.get_text()
        redactions, draws, growths = [], [], []
        for model, group in hits:
            try:
                new, notes, book = convert_model(model, page_text)
            except Exception as exc:                    # noqa: BLE001
                report["warnings"].append(f"p{pno+1}: could not convert {model}: {exc}")
                continue

            if new == model:
                # rev6 numbers often carry no retired codes. Report it, leave the
                # page alone - redrawing identical text can only lose fidelity.
                report.setdefault("models", []).append(
                    (pno + 1, model, new, book, notes))
                done.append((pno + 1, model, new))
                continue

            first = group[0]
            x0 = first["bbox"][0]
            x1 = max(g["bbox"][2] for g in group)
            top = min(g["bbox"][1] for g in group)
            bot0 = max(g["bbox"][3] for g in group)
            right = _cell_right(page, x0, top, bot0, fallback=max(x1, x0 + 214.0))
            width = max(right - x0, 120.0)
            base = first["origin"][1]

            # Preferred: 9pt on Trane's 10pt pitch, growing the table row if the
            # number needs a second line - exactly what their own pages do.
            lines = _wrap(new, font, BASE_SIZE, width)
            pitch = BASE_SIZE * LEAD
            need = base + (len(lines) - 1) * pitch + RULE_GAP
            rule_y = _row_rule(page, x0, top)

            plan = None
            if len(lines) > 1:
                plan = _grow_row(page, x0, top, need, rule_y)
            if plan:
                delta = plan[0]
                block, _nxt = _block_below(page, plan[1], spans=spans)
                ok, room = _has_room(block, group, delta, spans)
                if ok:
                    growths.append((plan, block, delta))
                    if room < 2.0:
                        report["warnings"].append(
                            f"p{pno+1}: row grown {delta:.1f}pt for {new} with only "
                            f"{room:.1f}pt to spare - eyeball this page")
                else:
                    plan = None                          # nowhere to push it

            if plan:
                size, start = BASE_SIZE, base
            else:
                limit = _clearance(page, group, x0, x1, spans=spans)
                # the row's closing rule is as hard a limit as the text below it;
                # drawing across it is what made the Mt Horeb page look wrong
                fit = min(limit, rule_y) if rule_y is not None else limit
                if len(lines) == 1 or \
                        base + (len(lines) - 1) * pitch + BASE_SIZE * 0.3 < fit - 0.5:
                    size, start = BASE_SIZE, base
                else:
                    size = BASE_SIZE                    # shrink to the existing row
                    while size >= MIN_SIZE:
                        size -= 0.5
                        lines = _wrap(new, font, size, width)
                        start = max(base - (len(lines) - 1) * size * LEAD * 0.35,
                                    top + size * 0.85)
                        if start + (len(lines) - 1) * size * LEAD + size * 0.30 < fit - 0.5:
                            break
                    else:
                        lines, size, start = _wrap(new, font, MIN_SIZE, width), MIN_SIZE, base
                        report["warnings"].append(
                            f"p{pno+1}: cannot fit {new} in the row and the row "
                            f"cannot be grown - eyeball this page")

            for g in group:
                b = g["bbox"]
                redactions.append(fitz.Rect(b[0] - 1, b[1] - 0.5, b[2] + 1, b[3] + 0.5))
            draws.append((x0, start, lines, size))
            report.setdefault("models", []).append((pno + 1, model, new, book, notes))
            done.append((pno + 1, model, new))

        # text that has to slide down to make room for the taller row
        for _plan, block, delta in growths:
            for sp in block:
                b = sp["bbox"]
                redactions.append(fitz.Rect(b[0] - 1, b[1] - 0.5, b[2] + 1, b[3] + 0.5))

        if not redactions:
            continue
        for r in redactions:
            page.add_redact_annot(r, fill=(1, 1, 1))
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                              graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                              text=fitz.PDF_REDACT_TEXT_REMOVE)

        # redraw the row borders one row taller, then the shifted text
        for plan, block, delta in growths:
            _delta, rule_y, x_lo, x_hi, segs, cols = plan
            page.draw_rect(fitz.Rect(x_lo - 1, rule_y - 1.2, x_hi + 1, rule_y + 1.2),
                           color=None, fill=(1, 1, 1))
            for x, w, col in cols:                       # extend the verticals
                page.draw_line((x, rule_y - 1.0), (x, rule_y + delta),
                               color=col or (0, 0, 0), width=w)
            for a, b, w, col in segs:                    # closing rule, moved down
                page.draw_line((a, rule_y + delta), (b, rule_y + delta),
                               color=col or (0, 0, 0), width=w)
            for sp in block:
                page.insert_text((sp["bbox"][0], sp["origin"][1] + delta),
                                 sp["text"], fontname=_alias(sp["font"]),
                                 fontsize=sp["size"], color=(0, 0, 0))

        for x0, y, lines, size in draws:
            for k, ln in enumerate(lines):
                page.insert_text((x0, y + k * size * LEAD), ln,
                                 fontname="helv", fontsize=size, color=(0, 0, 0))
    return done
