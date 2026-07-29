"""
modelswap.py - find KCC/Trane DOAS model numbers in a submittal PDF, convert them
to the new hybrid nomenclature, and rewrite them in place.

Long numbers are wrapped the way Trane's own submittal software already does it:
fill the cell, break with a hyphen, continue on the next line. The type size is
stepped down until the wrapped block clears whatever sits below it, so nothing
else on the page has to move.
"""
import re

import fitz

from convert import convert_model


def _alias(font):
    return "hebo" if "bold" in (font or "").lower() else "helv"

# OA + cabinet + revision + 3-digit size + 2 + at least one more hyphenated group
MODEL_RE = re.compile(r"OA[BDGKN][A-G]\d{3}[A-Z0-9]{2}(?:-[A-Z0-9]+)+")

VALID_LEN = {37, 63}          # printed chars, hyphens excluded (rev5 / rev6)

# Trane sets a wrapped model number in 9pt on a 10pt pitch and grows the table
# row to suit: a single-line row closes at y=103.45, a two-line row at y=109.46.
# We match that. If the row cannot be grown safely we fall back to shrinking the
# type so it fits the row as-is.
BASE_SIZE = 9.0
MIN_SIZE = 6.5
LEAD = 1.112                  # 10.01pt pitch at 9pt, as Trane uses
RULE_GAP = 3.62               # gap from the last baseline to the closing rule


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


def _rules(page, y_lo, y_hi):
    """Horizontal segments (grouped by y) and vertical segments in a band."""
    horiz, vert = {}, {}
    for dr in page.get_drawings():
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


def _grow_row(page, x0, model_top, needed_bottom):
    """Push the row's closing rule down so a taller model number fits, the way
    Trane's own pages do. Returns (delta, undo_rect, draws) or None."""
    horiz, vert = _rules(page, model_top + 2, model_top + 80)
    rule_y = None
    for y in sorted(horiz):
        if any(a <= x0 + 2 and b >= x0 + 40 for a, b, _w, _c in horiz[y]):
            rule_y = y
            break
    if rule_y is None or needed_bottom <= rule_y + 0.2:
        return None                                   # already tall enough
    delta = round(needed_bottom - rule_y, 2)
    segs = horiz[rule_y]
    x_lo = min(a for a, _b, _w, _c in segs)
    x_hi = max(b for _a, b, _w, _c in segs)
    # verticals that stop at this rule need extending to the new one
    cols = [(x, v[0][2], v[0][3]) for x, v in vert.items()
            if any(abs(b - rule_y) < 0.6 for _a, b, _w, _c in v)]
    return delta, rule_y, x_lo, x_hi, segs, cols


def _find(page):
    """Model-number occurrences, re-joining any that the PDF wrapped across lines."""
    spans = []
    for blk in page.get_text("dict")["blocks"]:
        for line in blk.get("lines", []):
            for s in line["spans"]:
                if s["text"].strip():
                    spans.append(s)
    spans.sort(key=lambda s: (round(s["bbox"][1], 1), s["bbox"][0]))

    found, used = [], set()
    for i, s in enumerate(spans):
        if i in used:
            continue
        t = s["text"].strip()
        if not MODEL_RE.match(t):
            continue
        parts, group = [t], [s]
        used.add(i)
        # a continuation sits just below, left-aligned, when the line ends "-"
        while parts[-1].endswith("-"):
            nxt = None
            for j, c in enumerate(spans):
                if j in used:
                    continue
                if (abs(c["bbox"][0] - s["bbox"][0]) < 1.5
                        and 0 < c["bbox"][1] - group[-1]["bbox"][1] < 14):
                    nxt = (j, c)
                    break
            if not nxt:
                break
            j, c = nxt
            used.add(j)
            # the trailing "-" is a real hyphen standing in for an unused digit
            # (e.g. d40), not a soft wrap hyphen, so it is kept
            parts.append(c["text"].strip())
            group.append(c)
        model = "".join(parts)
        if len(model.replace("-", "")) in VALID_LEN:
            found.append((model, group))
    return found


def _cell_right(page, x0, y0, y1, fallback):
    """Right edge of the table cell holding the model number, from its border rule.

    Deriving the wrap width from the existing text is unreliable: where the source
    PDF already wrapped a long number, the first line can be far narrower than the
    cell actually is.
    """
    best = None
    for dr in page.get_drawings():
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


def _clearance(page, group, x0, x1):
    """Lowest y a rewritten block may reach before touching the text below it."""
    bottom = max(g["bbox"][3] for g in group)
    limit = page.rect.height
    for blk in page.get_text("dict")["blocks"]:
        for line in blk.get("lines", []):
            for s in line["spans"]:
                if not s["text"].strip() or s in group:
                    continue
                b = s["bbox"]
                if b[1] >= bottom - 1 and b[2] > x0 and b[0] < x1 + 40:
                    limit = min(limit, b[1])
    return limit


def _block_below(page, rule_y, reach=30.0):
    """Spans sitting just under the row rule (the Tag line), and the first thing
    below them, so we can tell whether the block has room to move down."""
    block, after = [], []
    for blk in page.get_text("dict")["blocks"]:
        for line in blk.get("lines", []):
            for sp in line["spans"]:
                if not sp["text"].strip():
                    continue
                y0 = sp["bbox"][1]
                if rule_y < y0 < rule_y + reach:
                    block.append(sp)
                elif y0 >= rule_y + reach:
                    after.append(y0)
    return block, (min(after) if after else 1e9)


def swap_models(doc, report, pages=None):
    """Convert every model number in `doc`. Returns a list of (page, old, new)."""
    font = fitz.Font("helv")
    done = []
    for pno in range(len(doc)):
        if pages is not None and pno not in pages:
            continue
        page = doc[pno]
        hits = _find(page)
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
            first = group[0]
            x0 = first["bbox"][0]
            x1 = max(g["bbox"][2] for g in group)
            top = min(g["bbox"][1] for g in group)
            bot0 = max(g["bbox"][3] for g in group)
            right = _cell_right(page, x0, top, bot0, fallback=max(x1, x0 + 214.0))
            width = max(right - x0, 120.0)
            base = first["origin"][1]
            limit = _clearance(page, group, x0, x1)

            # Preferred: 9pt on Trane's 10pt pitch, growing the table row if the
            # number needs a second line - exactly what their own pages do.
            lines = _wrap(new, font, BASE_SIZE, width)
            pitch = BASE_SIZE * LEAD
            need = base + (len(lines) - 1) * pitch + RULE_GAP
            plan = _grow_row(page, x0, top, need) if len(lines) > 1 else None
            if plan:
                delta, rule_y = plan[0], plan[1]
                block, nxt = _block_below(page, rule_y)
                room = min(nxt, limit if limit < 1e8 else 1e9)
                low = max((sp["bbox"][3] for sp in block), default=rule_y)
                if low + delta >= room - 1.0:
                    plan = None                          # nowhere to push it
                else:
                    growths.append((plan, block, delta))

            if plan or len(lines) == 1 or \
               base + (len(lines) - 1) * pitch + BASE_SIZE * 0.3 < limit - 0.5:
                size, start = BASE_SIZE, base
            else:
                size = BASE_SIZE                        # shrink to the existing row
                while size >= MIN_SIZE:
                    size -= 0.5
                    lines = _wrap(new, font, size, width)
                    start = max(base - (len(lines) - 1) * size * LEAD * 0.35,
                                top + size * 0.85)
                    if start + (len(lines) - 1) * size * LEAD + size * 0.30 < limit - 0.5:
                        break
                else:
                    lines, size, start = _wrap(new, font, MIN_SIZE, width), MIN_SIZE, base
                    report["warnings"].append(
                        f"p{pno+1}: tight fit for {new} - eyeball this page")

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
