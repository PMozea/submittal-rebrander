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

# OA + cabinet + revision + 3-digit size + 2 + at least one more hyphenated group
MODEL_RE = re.compile(r"OA[BDGKN][A-G]\d{3}[A-Z0-9]{2}(?:-[A-Z0-9]+)+")

VALID_LEN = {37, 63}          # printed chars, hyphens excluded (rev5 / rev6)

BASE_SIZE = 8.0               # 9pt needs a 6pt push of everything below; 8pt does not
MIN_SIZE = 6.5
LEAD = 1.025                  # line pitch as a multiple of the type size


def _wrap(s, font, size, width):
    """Trane's rule: fill to the cell width, break with a hyphen, continue."""
    lines, cur = [], ""
    for ch in s:
        if cur and font.text_length(cur + ch + "-", size) > width:
            lines.append(cur + "-")
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


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
            parts[-1] = parts[-1][:-1]          # drop the soft hyphen
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
        redactions = []
        draws = []
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

            size = BASE_SIZE
            while size >= MIN_SIZE:
                lines = _wrap(new, font, size, width)
                # first baseline keeps the original row alignment where it can
                start = base - (len(lines) - 1) * size * LEAD * 0.35
                start = max(start, top + size * 0.85)
                bottom = start + (len(lines) - 1) * size * LEAD + size * 0.30
                if bottom < limit - 0.5:
                    break
                size -= 0.5
            else:
                lines = _wrap(new, font, MIN_SIZE, width)
                size = MIN_SIZE
                start = base
                report["warnings"].append(
                    f"p{pno+1}: tight fit for {new} - eyeball this page")

            for g in group:
                b = g["bbox"]
                redactions.append(fitz.Rect(b[0] - 1, b[1] - 0.5, b[2] + 1, b[3] + 0.5))
            draws.append((x0, start, lines, size))
            report.setdefault("models", []).append((pno + 1, model, new, book, notes))
            done.append((pno + 1, model, new))

        if not redactions:
            continue
        for r in redactions:
            page.add_redact_annot(r, fill=(1, 1, 1))
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                              graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                              text=fitz.PDF_REDACT_TEXT_REMOVE)
        for x0, y, lines, size in draws:
            for k, ln in enumerate(lines):
                page.insert_text((x0, y + k * size * LEAD), ln,
                                 fontname="helv", fontsize=size, color=(0, 0, 0))
    return done
