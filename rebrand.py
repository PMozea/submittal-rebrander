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
    "text_replacements": [("Trane", "KCC")],
    "brand_replacements": {"Horizon": "KCC"},
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


def _apply(text, cfg):
    out = text
    for a, b in cfg["text_replacements"]:
        out = out.replace(a, b)
    for brand, tgt in cfg["brand_replacements"].items():
        out = re.sub(r"\b" + re.escape(brand) + r"\b", tgt, out)
    if cfg.get("drop_trademark", True):
        out = out.replace(TM, "")
    return out


def _alias(font):
    return "hebo" if "bold" in font.lower() else "helv"


def _image_is_trane(doc, xref, rects, cfg):
    try:
        raw = hashlib.md5(doc.extract_image(xref)["image"]).hexdigest()
    except Exception:
        raw = None
    ph, dims = None, None
    try:
        pm = fitz.Pixmap(doc, xref)
        ph, dims = hashlib.md5(pm.samples).hexdigest(), (pm.width, pm.height)
    except Exception:
        pass
    if raw in cfg["trane_logo_hashes"] or ph in cfg["trane_logo_hashes"]:
        return True
    if dims in cfg["trane_logo_dims"]:
        for r in rects:
            if r.y0 < 140 and r.x0 < 240:
                return True
    return False


def rebrand_pdf(in_path, out_path, logo_path, config=None):
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    report = {"text": [], "logos": [], "warnings": [], "scope_pages": []}
    doc = fitz.open(in_path)

    # ---- find the Trane logo(s) by fingerprint ----
    logo_jobs, logo_pages = [], set()
    for pno in range(len(doc)):
        page = doc[pno]
        for img in page.get_images(full=True):
            xref = img[0]
            rects = page.get_image_rects(xref)
            if _image_is_trane(doc, xref, rects, cfg):
                logo_pages.add(pno)
                for r in rects:
                    logo_jobs.append((pno, xref, r))

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

    doc.save(out_path, garbage=4, deflate=True, clean=True)
    doc.close()
    return report


def _cli():
    ap = argparse.ArgumentParser(description="Rebrand a Trane submittal to KCC.")
    ap.add_argument("input"); ap.add_argument("output", nargs="?")
    ap.add_argument("--logo", default=os.path.join(os.path.dirname(__file__), "kcc_logo.png"))
    a = ap.parse_args()
    out = a.output or re.sub(r"\.pdf$", "_KCC.pdf", a.input, flags=re.I)
    rep = rebrand_pdf(a.input, out, a.logo)
    print(f"Wrote {out}")
    print(f"  Trane pages: {rep['scope_pages']}")
    print(f"  text runs redrawn: {len(rep['text'])}")
    print(f"  logos swapped:     {len(rep['logos'])} on page(s) {[p for p,_ in rep['logos']]}")
    for w in rep["warnings"]:
        print(f"  WARNING: {w}")


if __name__ == "__main__":
    _cli()
