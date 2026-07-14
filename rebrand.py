#!/usr/bin/env python3
"""
rebrand.py - Rebrand a Trane equipment submittal to KCC.

Identifies the Trane submittal by content (the Trane logo's image fingerprint
and the "Trane Equipment Submittal" footer), so on a bundled package it touches
ONLY the Trane pages - never another firm's cover sheet, review form, or logo.

  - "Trane" -> "KCC" everywhere on the Trane pages (footers, "U.S. Inc.", etc.).
  - Product brand "Horizon" -> "KCC" on whole-word boundaries ("Horizontal" is
    never touched). The trademark symbol is dropped, so it reads "KCC", not
    "KCC(TM)" (KCC is not a registered mark).
  - The Trane logo is replaced with the KCC logo, matched by image fingerprint.

Each affected line is redrawn tightly so removing the longer "Horizon(TM)" for
"KCC" leaves no gaps, while separate columns (e.g. the model-number field) stay
put. Other firms' pages are left byte-for-byte identical.

Usage:
  python rebrand.py input.pdf                 -> input_KCC.pdf
  python rebrand.py input.pdf output.pdf
  python rebrand.py input.pdf --logo kcc.png
"""
import argparse
import hashlib
import os
import re

import fitz  # PyMuPDF

TM = "\u2122"

DEFAULT_CONFIG = {
    # literal swaps, applied in order (most specific first)
    "text_replacements": [("Trane U.S. Inc.", "KCC Manufacturing"),
                          ("Trane", "KCC")],
    # regex swaps, applied before everything (e.g. genericise the controller name)
    "regex_replacements": [(r"Symbio\s+\d+\s*-\s*Horizon", "KCC program"),
                           (r"\s*/\s*Thrive\s+v[\d.]+", ""),
                           (r"Installed(\s+by\s+)Others", r"Installed\1KCC")],
    # whole-word product brand swap ("Horizontal" is never matched)
    "brand_replacements": {"Horizon": "Viking"},
    "drop_trademark": True,
    "scope_to_trane_pages": True,
    "page_markers": ["Trane Equipment Submittal", "by Trane / Installed",
                     "Furnished   by Trane"],
    "trane_logo_hashes": {
        "29a39d46f25d514da5f1331ccc35fe5d",   # raw embedded image
        "3934a474bf5c28ac43131af07fc1fa14",   # decoded pixels
    },
    "trane_logo_dims": [(207, 70)],           # fallback: pixel WxH + header pos
}

# Profile for mechanical drawings: swap the (different) title-block Trane logo and
# change any "Trane" text to KCC. No Horizon/controller/footer rules, and no
# submittal-footer scoping (drawings don't have that footer, so process all pages).
DRAWING_CONFIG = {
    "text_replacements": [("Trane", "KCC")],
    "regex_replacements": [],
    "brand_replacements": {},
    "drop_trademark": True,
    "scope_to_trane_pages": False,
    "page_markers": [],
    "trane_logo_hashes": {"53d7abf3fbd7230ab0b4c8d9af3c6e9e",   # drawing title-block logo (PNG, 548x211)
                          "f1739bdab6285b34d894a616dd89b5ab"},  # drawing title-block logo (JPEG, 639x245)
    "trane_logo_dims": [(548, 211), (639, 245)],
    "color_fallback": True,   # if no fingerprint match, find the logo by its orange signature
}


# --- Optional "tolerance notes" block --------------------------------------------
# Some drawings need the standard tolerance NOTES; some don't. When requested, we stamp
# the exact vector block (correct CenturyGothic font + the degree/plus-minus symbols,
# which are line-art, not glyphs) from a shipped template PDF, anchored to the standard
# "DO NOT SCALE DRAWING." line so it lands in the right spot on any KCC drawing sheet.
NOTES_TEMPLATE = os.path.join(os.path.dirname(__file__), "tolerance_notes.pdf")
_NOTES_W, _NOTES_H = 204.20, 27.80            # template page size (pt)
_NOTES_OFF_X, _NOTES_OFF_Y1 = -0.84, -6.64    # block offset vs the DIMENSIONS anchor origin
_NOTES_ANCHORS = ("DO NOT SCALE DRAWING", "DIMENSIONS ARE IN INCHES")


def _page_has_notes(page):
    t = page.get_text()
    return "NOTES:" in t and "UNLESS OTHERWISE SPECIFIED" in t


def _notes_anchor(page):
    for blk in page.get_text("dict")["blocks"]:
        for line in blk.get("lines", []):
            for s in line["spans"]:
                if any(m in s["text"] for m in _NOTES_ANCHORS):
                    return s["origin"]
    return None


def _stamp_tolerance_notes(doc, tmpl_path, report):
    if not os.path.exists(tmpl_path):
        report["warnings"].append(f"Tolerance-notes template not found: {tmpl_path}")
        return
    with fitz.open(tmpl_path) as tmpl:
        for pno in range(len(doc)):
            page = doc[pno]
            if _page_has_notes(page):                       # idempotent: never double-stamp
                report["warnings"].append(f"p{pno+1}: tolerance notes already present - not added.")
                continue
            anc = _notes_anchor(page)
            if anc is None:
                report["warnings"].append(f"p{pno+1}: no DIMENSIONS anchor - tolerance notes not added.")
                continue
            ax, ay = anc
            x0 = ax + _NOTES_OFF_X
            y1 = ay + _NOTES_OFF_Y1
            page.show_pdf_page(fitz.Rect(x0, y1 - _NOTES_H, x0 + _NOTES_W, y1), tmpl, 0)
            report["notes"].append(pno + 1)


def _apply(text, cfg):
    out = text
    for pat, rep in cfg.get("regex_replacements", []):   # run first (most specific)
        out = re.sub(pat, rep, out)
    for a, b in cfg["text_replacements"]:                 # literal, in order
        out = out.replace(a, b)
    for brand, tgt in cfg["brand_replacements"].items():  # whole-word brand
        out = re.sub(r"\b" + re.escape(brand) + r"\b", tgt, out)
    if cfg.get("drop_trademark", True):
        out = out.replace(TM, "")
    return out


def _alias(font):
    return "hebo" if "bold" in font.lower() else "helv"


def _image_is_trane(doc, xref, w, h, rects, cfg):
    # Cheap reject by native pixel size first (metadata only - no image decode).
    if (w, h) not in cfg["trane_logo_dims"]:
        return False
    try:                                    # confirm by raw-bytes hash (no decode)
        if hashlib.md5(doc.extract_image(xref)["image"]).hexdigest() in cfg["trane_logo_hashes"]:
            return True
    except Exception:
        pass
    return any(r.y0 < 140 and r.x0 < 240 for r in rects)   # header-position fallback


def _warm_orange_fraction(doc, xref, sample_target=160):
    """Fraction of pixels that are Trane-orange (warm, red-dominant). Independent of
    image resolution/encoding. Samples on a grid so large images stay fast."""
    try:
        pix = fitz.Pixmap(doc, xref)
    except Exception:
        return 0.0
    if pix.alpha:
        pix = fitz.Pixmap(pix, 0)          # drop alpha
    if pix.n < 3:                          # grayscale/mask -> not the logo
        return 0.0
    samp, stride, n = pix.samples, pix.stride, pix.n
    step_x = max(1, pix.width // sample_target)
    step_y = max(1, pix.height // sample_target)
    warm = tot = 0
    for y in range(0, pix.height, step_y):
        base = y * stride
        for x in range(0, pix.width, step_x):
            o = base + x * n
            r, g, b = samp[o], samp[o + 1], samp[o + 2]
            tot += 1
            if r > 230 and g > 230 and b > 230:      # white background
                continue
            if r >= 150 and r > g + 30 and g >= b and b < 160 and (r - b) > 60:
                warm += 1
    return warm / tot if tot else 0.0


def _image_is_trane_by_color(doc, xref, w, h, rects, page):
    """Fingerprint-free fallback: a wide, small, edge-placed, strongly-orange image is
    the Trane logo regardless of its resolution/encoding. All guards must agree."""
    if h <= 0:
        return False
    if not (1.8 <= w / h <= 3.3):            # Trane wordmark family (~2.6-3.0)
        return False
    pw, ph = page.rect.width, page.rect.height
    ok_geom = False
    for r in rects:                          # small footprint, hugging a page edge
        small = r.width < 0.55 * pw and (r.width * r.height) < 0.15 * (pw * ph)
        edge = min(r.x0, pw - r.x1) < 0.15 * pw or min(r.y0, ph - r.y1) < 0.15 * ph
        if small and edge:
            ok_geom = True
            break
    if not ok_geom:
        return False
    return _warm_orange_fraction(doc, xref) >= 0.12


def rebrand_pdf(in_path, out_path, logo_path, config=None,
                add_notes=False, notes_template=None):
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    report = {"text": [], "logos": [], "warnings": [], "scope_pages": [], "notes": []}
    doc = fitz.open(in_path)

    # ---- find the Trane logo(s) by fingerprint ----
    logo_jobs, logo_pages = [], set()
    for pno in range(len(doc)):
        page = doc[pno]
        for img in page.get_images(full=True):
            xref, w, h = img[0], img[2], img[3]
            if (w, h) not in cfg["trane_logo_dims"]:
                continue                    # fast reject without decoding/geometry
            rects = page.get_image_rects(xref)
            if _image_is_trane(doc, xref, w, h, rects, cfg):
                logo_pages.add(pno)
                for r in rects:
                    logo_jobs.append((pno, xref, r))

    # ---- fallback: no fingerprint match -> find the logo by its orange signature ----
    # (drawing profile only; runs solely when the exact pass found nothing, so it can
    #  never override correct detection. Reports the new fingerprint to promote later.)
    if not logo_jobs and cfg.get("color_fallback"):
        for pno in range(len(doc)):
            page = doc[pno]
            for img in page.get_images(full=True):
                xref, w, h = img[0], img[2], img[3]
                rects = page.get_image_rects(xref)
                if _image_is_trane_by_color(doc, xref, w, h, rects, page):
                    logo_pages.add(pno)
                    for r in rects:
                        logo_jobs.append((pno, xref, r))
                    try:
                        fp = hashlib.md5(doc.extract_image(xref)["image"]).hexdigest()
                    except Exception:
                        fp = "?"
                    report["warnings"].append(
                        f"Logo found by COLOR fallback (not fingerprint): {w}x{h}, "
                        f"hash {fp}. Add these to DRAWING_CONFIG trane_logo_dims/hashes "
                        f"to make future runs exact and fast.")

    # ---- decide which pages are "Trane submittal" pages ----
    if cfg["scope_to_trane_pages"]:
        scope = set(logo_pages)
        for pno in range(len(doc)):
            t = doc[pno].get_text()
            if any(m in t for m in cfg["page_markers"]):
                scope.add(pno)
    else:
        scope = set(range(len(doc)))
    report["scope_pages"] = sorted(p + 1 for p in scope)

    fonts = {"helv": fitz.Font("helv"), "hebo": fitz.Font("hebo")}

    # ---- build line "runs" to redraw (only on in-scope pages) ----
    # A run = a changed span plus the contiguous spans right after it (so trailing
    # bits like "(TM) - Outdoor Air Unit" reflow tight), stopping at any large gap
    # (a separate column, e.g. the model number, which must not move).
    runs = []                       # each: dict(pno, spans=[span,...])
    page_rects = {p: [] for p in range(len(doc))}
    for pno in scope:
        for blk in doc[pno].get_text("dict")["blocks"]:
            for line in blk.get("lines", []):
                spans = line["spans"]
                for s in spans:
                    if s["text"].strip():
                        page_rects[pno].append(fitz.Rect(s["bbox"]))
                consumed = [False] * len(spans)
                i = 0
                while i < len(spans):
                    s = spans[i]
                    if consumed[i] or _apply(s["text"], cfg) == s["text"]:
                        i += 1
                        continue
                    run = [s]
                    consumed[i] = True
                    gap_thresh = max(12.0, 1.6 * s["size"])
                    j = i + 1
                    while j < len(spans):
                        prev = spans[j - 1]
                        cur = spans[j]
                        if cur["bbox"][0] - prev["bbox"][2] < gap_thresh:
                            run.append(cur)
                            consumed[j] = True
                            j += 1
                        else:
                            break
                    runs.append({"pno": pno, "spans": run})
                    i = j

    # ---- pass 1: redact every span in every run (tight, clamped band) ----
    redacted_pages = set()
    for r in runs:
        for s in r["spans"]:
            oy, sz, b = s["origin"][1], s["size"], fitz.Rect(s["bbox"])
            ry0, ry1 = oy - 0.85 * sz, oy + 0.30 * sz
            for o in page_rects[r["pno"]]:
                if abs(o.y0 - b.y0) < 0.5 and abs(o.x0 - b.x0) < 0.5:
                    continue
                if o.x1 <= b.x0 or o.x0 >= b.x1:
                    continue
                if o.y0 >= oy:
                    ry1 = min(ry1, o.y0 - 0.1)
                elif o.y1 <= oy:
                    ry0 = max(ry0, o.y1 + 0.1)
            if ry1 <= ry0:
                ry0, ry1 = oy - 0.7 * sz, oy + 0.05 * sz
            doc[r["pno"]].add_redact_annot(
                fitz.Rect(b.x0 - 0.3, ry0, b.x1 + 0.3, ry1), fill=(1, 1, 1))
            redacted_pages.add(r["pno"])
    for pno in redacted_pages:
        doc[pno].apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                                  graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                                  text=fitz.PDF_REDACT_TEXT_REMOVE)

    # ---- pass 2: redraw each run, left-anchored, spans laid out tight ----
    for r in runs:
        page = doc[r["pno"]]
        spans = r["spans"]
        cx = spans[0]["origin"][0]
        y = spans[0]["origin"][1]
        old_line = "".join(s["text"] for s in spans)
        for s in spans:
            t = _apply(s["text"], cfg)
            if not t:
                continue
            alias = _alias(s["font"]); size = s["size"]
            page.insert_text((cx, y), t, fontname=alias, fontsize=size, color=(0, 0, 0))
            cx += fonts[alias].text_length(t, size)
        report["text"].append((r["pno"] + 1, old_line, _apply(old_line, cfg)))

    # ---- pass 3: swap the Trane logo(s) ----
    if logo_jobs:
        if not os.path.exists(logo_path):
            report["warnings"].append(f"Logo file not found: {logo_path}")
        else:
            with fitz.open(logo_path) as limg:
                kw, kh = limg[0].rect.width, limg[0].rect.height
            ar = kh / kw
            deleted = set()
            for pno, xref, rect in logo_jobs:
                page = doc[pno]
                if xref not in deleted:
                    page.delete_image(xref); deleted.add(xref)
                w = rect.width
                page.insert_image(fitz.Rect(rect.x0, rect.y0, rect.x0 + w, rect.y0 + w * ar),
                                  filename=logo_path, keep_proportion=True, overlay=True)
                report["logos"].append((pno + 1, tuple(round(v, 1) for v in rect)))
    else:
        report["warnings"].append("No Trane logo found by fingerprint - nothing swapped.")

    # ---- residual audit (in-scope pages only) ----
    scoped_text = "".join(doc[p].get_text() for p in scope)
    for token in ["Trane", "Horizon", TM]:
        n = scoped_text.count(token) if token == TM else \
            len(re.findall(r"\b" + re.escape(token) + r"\b", scoped_text))
        if n:
            label = "trademark symbol" if token == TM else f"'{token}'"
            report["warnings"].append(f"{n} residual {label} on Trane pages - review.")

    # ---- optional: stamp the tolerance-notes block ----
    if add_notes:
        _stamp_tolerance_notes(doc, notes_template or NOTES_TEMPLATE, report)

    doc.save(out_path, garbage=4, deflate=True, clean=True)
    doc.close()
    return report


def _cli():
    ap = argparse.ArgumentParser(description="Rebrand a Trane submittal or drawing to KCC.")
    ap.add_argument("input"); ap.add_argument("output", nargs="?")
    ap.add_argument("--logo", default=os.path.join(os.path.dirname(__file__), "kcc_logo.png"))
    ap.add_argument("--drawing", action="store_true", help="use the drawing profile")
    ap.add_argument("--notes", action="store_true", help="add the tolerance NOTES block")
    a = ap.parse_args()
    out = a.output or re.sub(r"\.pdf$", "_KCC.pdf", a.input, flags=re.I)
    rep = rebrand_pdf(a.input, out, a.logo,
                      config=(DRAWING_CONFIG if a.drawing else None),
                      add_notes=a.notes)
    print(f"Wrote {out}")
    print(f"  Trane pages: {rep['scope_pages']}")
    print(f"  text runs redrawn: {len(rep['text'])}")
    print(f"  logos swapped:     {len(rep['logos'])} on page(s) {[p for p,_ in rep['logos']]}")
    if rep["notes"]:
        print(f"  tolerance notes added on page(s): {rep['notes']}")
    for w in rep["warnings"]:
        print(f"  WARNING: {w}")


if __name__ == "__main__":
    _cli()
