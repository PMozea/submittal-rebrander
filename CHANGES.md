# CHANGES — this update

Two files changed: **`app.py`** and **`modelswap.py`**. Everything else in the repo
is byte-identical to what is deployed, including `cur.xlsx` and `hyb.xlsx`.

`kcc_logo.png` and `tolerance_notes.pdf` are **not in this zip** — they were not in
the bundle I was working from. Leave the copies already in the repo alone.

---

## 1. `app.py` — four modes become three

| Before | After |
|---|---|
| Submittal | Submittal — unchanged, still has the model-number checkbox |
| Drawing | Drawing — unchanged |
| Model numbers only (PDF in, PDF out) | **Model numbers only — text in, text out, no PDF** |
| Hybrid 69 to Rev5 lookup | folded into the above |

The new mode has a **Direction** radio in the sidebar:

- `39 to 69 (rev5 / rev6 to hybrid)` → `convert.convert_model()`, shows the
  converted number, any ERROR/CHECK flags, and the per-digit audit
- `69 to 39 (hybrid to rev5)` → `reverse.reverse()`, shows the rev5 number, the
  pre-approved ETOs, changed logic and flags — same output as the old lookup tab

Multiple numbers, one per line, work in both directions.

Because the direction is manual, wrong-direction input is caught rather than
misparsed: feeding a 63-digit OABG/OAKG to `39 to 69` says "already a hybrid,
switch the direction", and a 37-digit number to `69 to 39` says the converse. A
digit count that is neither 37 nor 63 is rejected with the count.

`rebrand.convert_models_pdf()` is left in `rebrand.py` — it still works as a CLI,
it is just no longer reachable from the UI.

### Known gap in the new mode
In the PDF path, a rev5 `X` at d31 is resolved by reading the `ERV/HRV:`
description off the same page (see handoff §9). Pasting a bare number gives the
converter nothing to read, so **every `X` unit will hard-ERROR at d34** with
"set d34 by hand". Correct behaviour — it refuses to guess — but unavoidable in
this mode rather than occasional. Not addressed here.

---

## 2. `modelswap.py` — hand-edited (ETO) submittals

Signature unchanged: `swap_models(doc, report)`. No change needed in `rebrand.py`.

Symptom on `Mt_Horeb_Primary_Center_ETO_EDITED.pdf`: of three model numbers, two
were silently skipped and the third was drawn through its own table rule.

Cause: the ETO edits patch characters by white-boxing and retyping them.

1. **`_runs()` rebuilds each visual line before matching.** One number arrived as
   twelve spans on one line with 0.32pt of baseline jitter. Spans are clustered
   on the baseline (`BASELINE_TOL = 1.5`, anchored per line so a drifting
   sequence cannot chain), split into runs on x-gaps, joined, then matched;
   matches map back to the covering spans. `MODEL_RE` cannot match a trailing
   hyphen, so a line ending on a real d40 hyphen has it re-attached before the
   continuation below is looked for.

2. **Near misses warn instead of vanishing.** A `MODEL_RE` hit whose printed
   length is not 37 or 63 now lands in `report["warnings"]`. Scoped to 20–70
   digits (`NEAR_MISS`) to stay quiet on unrelated codes. This is what hid the
   failure: a 30-character fragment matched, failed validation, and was dropped
   with no output at all.

3. **`_visible()` rejects white-on-white drawings** in `_cell_right()` and
   `_rules()`. The retype patches are white-filled and white-stroked, and were
   being read as table geometry — putting the cell's right edge at 515.0 instead
   of 526.6 and the row rule at 98.5 instead of 103.45. The narrow cell is why a
   converted number broke at d30 instead of the d40 hyphen the native rev6 pages
   use: the d40 prefix needs 212.08pt, which fits 217.50 but not 205.90.

4. **Row growth is column-aware and rule-aware.** `_has_room()` compares each
   moving span against what stays put *in the same x-range*, and measures from
   the baseline plus `DESCENDER` rather than the span bbox (a 24pt ETO stamp
   reports 33pt of height, which made the old whole-page minimum refuse every
   move). The tag line and the ETO stamp now move down with the row. If the row
   still cannot grow, the closing rule is a hard clearance limit, so nothing is
   drawn across it. `GROW_SLACK = 1.0` stops a 0.58pt nudge on rows that are
   already tall enough — native two-line rows sit 3.04pt below the last
   baseline, slightly tighter than `RULE_GAP`.

5. **A number that converts to itself leaves its page untouched** and is
   reported as-is, instead of redrawing identical text.

### Verification
- `Mt_Horeb_Primary_Center_ETO_EDITED.pdf`: 1 of 3 found → 3 of 3. Pages 17 and
  27 rewritten, page 7 (identity conversion) untouched, 40 other pages
  pixel-identical.
- `lido_model_number_page.pdf` (cover + 6 product-data pages): old and new both
  find all 6 and every page renders **pixel-identical**. No warnings raised.
- Streamlit `AppTest` over all three modes, both directions, and the four
  rejection paths.
- `Virtua_Mt__Holly.pdf` — **not tested**, file wasn't available.

---

## Open items, deliberately not changed

1. **`cur.xlsx`, OAB rev 5, UNIT CONTROLS (d25–d26):** "Non DDC -
   Electromechanical" is keyed `0`, but `OAN rev5` keys the same option `00`.
   The converter reads d25+d26 as two characters, so it resolves in OAN5 and
   misses in OAB5 → `desc()` returns None → the `"non ddc"` test cannot fire →
   `d31 = "X"` with an empty message. **Every Non-DDC OAB unit gets an invalid
   `X` at d31.** One-cell fix, no code change (the workbooks load at runtime).
   A guard so a missing code says which code and book was missed — rather than
   nothing — would stop the next mismatch hiding the same way.
2. **`use_container_width`** is deprecated; Streamlit's warning says it was
   slated for removal after 2025-12-31. Two `st.dataframe` and two `st.image`
   calls. The replacement, `width='stretch'`, needs a higher floor than the
   current `streamlit>=1.30` in `requirements.txt`.
3. **`clean=True` on save** rewrites third-party content streams — on the Mt
   Horeb file it changes how two GreenTrol cut-sheet pages render, with no edits
   made. Pre-existing, unrelated to this change, but it contradicts
   `convert_models_pdf`'s docstring claim that untouched pages stay
   byte-for-byte identical.
4. **rev6 `d32` 1 → 4** fires on Lido RTU-6: the page says
   `Building Interface: BACnet`, and the converted number claims BACnet &
   MODBUS. Handoff §16 question 4 is live on real jobs.
5. `PROJECT_HANDOFF_v2.md` is now stale in its mode list (§1) and its
   `modelswap` notes (§3, §13). Not updated here.

---

## `_dev/` — not for the repo

`check_modelswap.py` runs the old and new `modelswap` side by side on a PDF and
reports which pages disagree; `modelswap_old.py` is the currently deployed copy
it compares against. Handy for the next `modelswap` change. Do **not** upload
these to the repo root — a stale `modelswap_old.py` next to `modelswap.py` is
exactly the sort of thing that gets imported by accident.

    python check_modelswap.py Virtua_Mt__Holly.pdf
