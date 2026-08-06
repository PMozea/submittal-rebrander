"""
P&D ENGINEERING TOOL - web app

Three modes:
  Submittal          rebrand a Trane submittal to KCC; optionally convert the
                     model numbers inside it (checkbox)
  Drawing            rebrand a Trane mechanical drawing; optionally stamp the
                     tolerance notes (checkbox)
  Model numbers only text in, text out. No PDF. Converts 39 <-> 69 either way.

Run locally:   streamlit run app.py
Deploy:        see DEPLOY.md
"""
import os
import tempfile

import fitz
import streamlit as st

from rebrand import rebrand_pdf, DRAWING_CONFIG

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOGO = os.path.join(HERE, "kcc_logo.png")

APP_NAME = "P&D ENGINEERING TOOL"

st.set_page_config(page_title=APP_NAME, layout="wide")


# ----------------------------------------------------------- optional password
def _configured_password():
    try:
        return st.secrets["app_password"]
    except Exception:
        return None


def _password_ok():
    pw = _configured_password()
    if not pw:                       # no password set -> app is open
        return True
    if st.session_state.get("authed"):
        return True
    st.title(APP_NAME)
    entered = st.text_input("Enter password to continue", type="password")
    if entered:
        if entered == pw:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


if not _password_ok():
    st.stop()


# ----------------------------------------------------------------- main app
st.title(APP_NAME)

DIR_FWD = "39 to 69  (rev5 / rev6 to hybrid)"
DIR_REV = "69 to 39  (hybrid to rev5)"

MODE_BLURB = {
    "Submittal": "Rebrand a Trane equipment submittal to KCC. Every 'Trane' "
                 "mention and the header logo are replaced, and model numbers "
                 "can optionally be converted to the hybrid nomenclature.",
    "Drawing": "Rebrand a Trane mechanical drawing to KCC, and optionally stamp "
               "the standard tolerance notes above the title block.",
    "Model numbers only": "Convert model numbers on their own - paste them in, "
                          "read them out. No PDF involved. To convert the model "
                          "numbers inside a submittal, use the Submittal mode and "
                          "tick the model-number box.",
    "AHRI model numbers": "Convert an AHRI certification model number from rev5 "
                          "to hybrid. These are patterns, not single units: a "
                          "\"*\" is a digit AHRI does not rate, and \"[3,8]\" is a "
                          "digit certified either way. OAB and OAN cabinets.",
}

with st.sidebar:
    st.header("Options")
    doc_type = st.radio("Document type",
                        ["Submittal", "Drawing", "Model numbers only",
                         "AHRI model numbers"])

    direction = DIR_FWD
    convert_models = False
    add_notes = False

    if doc_type == "Model numbers only":
        direction = st.radio("Direction", [DIR_FWD, DIR_REV])
        if direction == DIR_FWD:
            st.caption("Takes a 39-digit rev5 number (or a 69-digit rev6 number) "
                       "and returns the 69-digit hybrid, with a per-digit audit.")
        else:
            st.caption("Takes a 69-digit hybrid number and returns the rev5 "
                       "equivalent with the pre-approved ETOs it needs. OABG and "
                       "OAKG only - OADG and OANG were never rev5 models.")

    if doc_type == "Submittal":
        convert_models = st.checkbox(
            "Convert model numbers to hybrid (BETA)", value=False,
            help="Rewrite each unit's model number in the new 69-position hybrid "
                 "nomenclature. OABD becomes OABG and OAND becomes OAKG. Always "
                 "review the audit table below before sending the file on.")

    if doc_type == "Drawing":
        add_notes = st.checkbox(
            "Add tolerance notes", value=False,
            help="Stamp the standard tolerance NOTES block (bends, formed dims, "
                 "bend angles) above the title block on any sheet that does not "
                 "already have it. Sheets that already show NOTES are skipped.")

    custom_logo = None
    if doc_type in ("Submittal", "Drawing"):
        custom_logo = st.file_uploader("Replacement logo (optional)",
                                       type=["png", "jpg", "jpeg"])
        st.markdown("Leave blank to use the built-in KCC logo.")

    st.divider()
    st.markdown("**Always eyeball the downloaded file** before sending it on - "
                "logo detection and tight model cells are the parts most worth a "
                "glance.")


# --------------------------------------------------------------------------
# helpers shared by both directions
# --------------------------------------------------------------------------

def _printed(model):
    """Digit count with the hyphens removed. The hyphens stand in for unused
    positions, so a valid number is 37 (rev5) or 63 (rev6 / hybrid) digits."""
    return len(model.replace("-", "").strip())


def _audit_rows(notes):
    return [{"Digit": "d" + ",".join(map(str, d)), "Code": c, "Flag": lvl,
             "Derived from": str(w)[:70]} for d, c, lvl, w in notes]


def _flag_table(models):
    """The per-page audit shared by the submittal path."""
    st.subheader(f"Model numbers converted ({len(models)})")
    st.dataframe(
        [{"Page": p, "Current": old, "New hybrid": new, "Codebook": bk,
          "Flagged": ", ".join(
              "d" + ",".join(map(str, d))
              for d, _c, lvl, _w in nt if lvl in ("CHECK", "ERROR")) or "-"}
         for p, old, new, bk, nt in models],
        use_container_width=True, hide_index=True)
    errs = [(p, d, w) for p, _o, _n, _b, nt in models
            for d, _c, lvl, w in nt if lvl == "ERROR"]
    for p, d, w in errs:
        st.error(f"p{p} d{','.join(map(str, d))}: {w}")
    with st.expander("Per-digit audit"):
        for p, old, new, bk, nt in models:
            st.markdown(f"**p{p}** `{old}` -> `{new}`  ({bk})")
            st.dataframe(_audit_rows(nt), use_container_width=True,
                         hide_index=True)
    st.info("BETA - model conversion is new. Check the numbers above, "
            "especially anything flagged, before releasing the submittal.")


# --------------------------------------------------------------------------
# Model numbers only - text in, text out
# --------------------------------------------------------------------------

def _render_forward(raw):
    from convert import convert_model

    n = _printed(raw)
    if n not in (37, 63):
        st.error(f"{n} printed digits - a model number has 37 (rev5) or 63 "
                 f"(rev6). Check for a missing or extra character.")
        return
    if n == 63 and raw.replace("-", "").strip().upper()[:4] in ("OABG", "OAKG"):
        st.error("This is already a 69-digit hybrid number. Switch the direction "
                 "to \"69 to 39\" to convert it back to rev5.")
        return
    try:
        new, notes, book = convert_model(raw)
    except Exception as exc:                          # noqa: BLE001
        st.error(f"{raw}: {exc}")
        return

    st.markdown(f"### `{new}`")
    st.caption(f"codebook: {book}")
    if new == raw.strip().upper():
        st.info("No change - this number carries no codes the hybrid retired.")

    for digs, _code, lvl, why in notes:
        d = "d" + ",".join(map(str, digs))
        if lvl == "ERROR":
            st.error(f"{d}: {why or '(no message)'}")
        elif lvl == "CHECK":
            st.warning(f"{d}: {why or '(no message)'}")

    with st.expander("Per-digit audit"):
        st.dataframe(_audit_rows(notes), use_container_width=True,
                     hide_index=True)

    if not any(lvl in ("CHECK", "ERROR") for _d, _c, lvl, _w in notes):
        st.success("Clean conversion - nothing flagged.")


def _render_reverse(raw):
    from reverse import reverse as _reverse

    n = _printed(raw)
    if n == 37:
        st.error("This is already a 39-digit rev5 number. Switch the direction "
                 "to \"39 to 69\" to convert it to the hybrid.")
        return
    if n != 63:
        st.error(f"{n} printed digits - a hybrid model number has 63. Check for "
                 f"a missing or extra character.")
        return
    try:
        res = _reverse(raw)
    except Exception as exc:                          # noqa: BLE001
        st.error(f"{raw}: {exc}")
        return

    if res["model"]:
        st.markdown(f"### `{res['model']}`")
    if res["etos"]:
        st.markdown("**Pre-approved ETOs required** - these are not carried in "
                    "the rev5 model number and must be added to the order:")
        for nm, src in res["etos"]:
            st.markdown(f"- **{nm}**  \n  <small>{src}</small>",
                        unsafe_allow_html=True)
    if res["logic"]:
        with st.expander("Logic that changed"):
            for l in res["logic"]:
                st.markdown(f"- {l}")
    for f in res["flags"]:
        st.warning(f)
    if res["model"] and not res["etos"] and not res["flags"]:
        st.success("Clean conversion - no ETOs, no flags.")


def _render_ahri(raw):
    import ahri

    try:
        results, info = ahri.convert_ahri(raw)
    except ahri.AhriError as exc:
        st.error(str(exc))
        return
    except Exception as exc:                          # noqa: BLE001
        st.error(f"{raw}: {exc}")
        return

    for d, opts, moved in info.get("split_on", []):
        st.warning(
            f"rev5 d{d} {opts} moves hybrid "
            f"{', '.join('d' + str(m) for m in moved)} together, so those digits "
            f"cannot be written as independent brackets - split into "
            f"{len(results)} numbers below.")

    for r in results:
        st.markdown(f"### `{r['ahri']}`")
        if r["pins"]:
            st.caption("with " + ", ".join(f"rev5 d{k} = {v}"
                                           for k, v in sorted(r["pins"].items())))
        st.caption(f"full 69-digit conversion: `{r['hybrid']}`")
    st.caption(f"codebook: {info['book']}  -  AHRI prints only the rated digits "
               f"(d1-d7, d11-d15, d34, d36) and asterisks the rest")

    if info.get("blind"):
        st.warning("could not test rev5 digit(s) "
                   + ", ".join("d" + str(d) for d in info["blind"])
                   + " - the sheet carries no codes for them, so any hybrid digit "
                     "they feed may be shown as fixed when it should be *")

    for digs, _code, lvl, why in (info.get("notes") or []):
        if lvl in ("CHECK", "ERROR"):
            d = "d" + ",".join(map(str, digs))
            (st.error if lvl == "ERROR" else st.warning)(
                f"{d}: {why or '(no message)'}")
    st.caption("Only flags that hold for every value of every wildcard are shown - "
               "anything raised by a placeholder digit is filtered out.")


if doc_type == "AHRI model numbers":
    st.caption(MODE_BLURB["AHRI model numbers"])
    st.subheader("AHRI rev5 to hybrid")
    txt = st.text_area("AHRI model number(s) - one per line", height=110,
                       placeholder="OABE108**-D1B[3,8]G****-**********-[C,D]1*******")
    c1, c2 = st.columns([1, 6])
    if c1.button("Convert", type="primary"):
        st.session_state["ahri_input"] = txt
    if c2.button("Clear"):
        st.session_state.pop("ahri_input", None)

    for line in [l.strip() for l in
                 st.session_state.get("ahri_input", "").splitlines() if l.strip()]:
        st.markdown("---")
        st.caption(line)
        _render_ahri(line)
    st.stop()


if doc_type == "Model numbers only":
    st.caption(MODE_BLURB["Model numbers only"])
    st.subheader(direction)

    placeholder = ("OAND480C4-D1B4G0LW-A7U09AF6JR6X82B3E500"
                   if direction == DIR_FWD else
                   "OAKG040E3-DAB1GB900-S1BGL1AJ3-24A11J03C-GF1C03000-"
                   "AA1000000-00AM00000")
    txt = st.text_area("Model number(s) - one per line", height=110,
                       placeholder=placeholder)
    c1, c2 = st.columns([1, 6])
    if c1.button("Convert", type="primary"):
        st.session_state["mn_input"] = txt
    if c2.button("Clear"):
        st.session_state.pop("mn_input", None)

    pending = st.session_state.get("mn_input", "")
    for line in [ln.strip() for ln in pending.splitlines() if ln.strip()]:
        st.markdown("---")
        st.caption(line)
        if direction == DIR_FWD:
            _render_forward(line)
        else:
            _render_reverse(line)
    st.stop()


# --------------------------------------------------------------------------
# Submittal / Drawing - PDF in, PDF out
# --------------------------------------------------------------------------

st.caption(MODE_BLURB.get(doc_type, "") +
           "  Files are processed in memory and are not stored on the server.")

uploaded = st.file_uploader("Submittal or drawing (PDF)", type=["pdf"])


def _png(path, page=0, zoom=1.4):
    with fitz.open(path) as d:
        p = d[min(page, len(d) - 1)]
        return p.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes("png")


if uploaded is not None:
    with tempfile.TemporaryDirectory() as td:
        in_path = os.path.join(td, "in.pdf")
        out_path = os.path.join(td, "out.pdf")
        with open(in_path, "wb") as fh:
            fh.write(uploaded.getbuffer())

        logo_path = DEFAULT_LOGO
        if custom_logo is not None:
            logo_path = os.path.join(td, "logo." + custom_logo.name.split(".")[-1])
            with open(logo_path, "wb") as fh:
                fh.write(custom_logo.getbuffer())

        with st.spinner("Rebranding..."):
            cfg = DRAWING_CONFIG if doc_type == "Drawing" else None
            report = rebrand_pdf(in_path, out_path, logo_path, config=cfg,
                                 add_notes=add_notes,
                                 convert_models=convert_models)

        c1, c2, c3 = st.columns(3)
        c1.metric("Text replacements", len(report["text"]))
        c2.metric("Logos swapped", len(report["logos"]))
        c3.metric("Warnings", len(report["warnings"]))

        models = report.get("models", [])
        if models:
            _flag_table(models)

        if report.get("notes"):
            st.success(f"Tolerance notes added on page(s): {report['notes']}")
        for w in report["warnings"]:
            st.warning(w)

        with open(out_path, "rb") as fh:
            data = fh.read()
        out_name = uploaded.name.rsplit(".", 1)[0] + "_KCC.pdf"
        st.download_button(f"Download KCC {doc_type.lower()}", data=data,
                           file_name=out_name, mime="application/pdf",
                           type="primary")

        st.subheader("Before / after (page 1)")
        a, b = st.columns(2)
        a.image(_png(in_path), caption="Original", use_container_width=True)
        b.image(_png(out_path), caption="Rebranded", use_container_width=True)

        with st.expander(f"All {len(report['text'])} text replacements"):
            for pno, old, new in report["text"]:
                st.text(f"p{pno}:  {old!r}  ->  {new!r}")
