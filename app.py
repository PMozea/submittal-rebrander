"""
Submittal Rebrander - web app (Trane -> KCC)

Deployed copy: anyone with the link can drag in a Trane submittal PDF and
download the KCC version. Optionally protected by a password.

Run locally:   streamlit run app.py
Deploy:        see DEPLOY.md
"""
import os
import tempfile

import fitz
import streamlit as st

from rebrand import rebrand_pdf, convert_models_pdf, DRAWING_CONFIG

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

MODE_BLURB = {
    "Submittal": "Rebrand a Trane equipment submittal to KCC. Every 'Trane' "
                 "mention and the header logo are replaced, and model numbers "
                 "can optionally be converted to the hybrid nomenclature.",
    "Drawing": "Rebrand a Trane mechanical drawing to KCC, and optionally stamp "
               "the standard tolerance notes above the title block.",
    "Model numbers only": "Convert every model number in a PDF to the hybrid "
                          "nomenclature and change nothing else.",
    "Hybrid 69 to Rev5 lookup": "Look up the rev5 equivalent of a hybrid model "
                                "number, with the pre-approved ETOs it needs.",
}

with st.sidebar:
    st.header("Options")
    doc_type = st.radio("Document type",
                        ["Submittal", "Drawing", "Model numbers only",
                         "Hybrid 69 to Rev5 lookup"])
    convert_models = False
    if doc_type == "Hybrid 69 to Rev5 lookup":
        st.caption("Paste a hybrid model number to get its rev5 equivalent, the "
                   "pre-approved ETOs, and any flags. OABG and OAKG only - OADG "
                   "and OANG were never rev5 models.")
    if doc_type == "Model numbers only":
        st.caption("Converts every model number to the hybrid nomenclature and "
                   "changes nothing else. Use this when the submittal is already "
                   "KCC-branded.")
    if doc_type == "Submittal":
        convert_models = st.checkbox(
            "Convert model numbers to hybrid (BETA)", value=False,
            help="Rewrite each unit's model number in the new 69-position hybrid "
                 "nomenclature. OABD becomes OABG and OAND becomes OAKG. Always "
                 "review the audit table below before sending the file on.")
    add_notes = False
    if doc_type == "Drawing":
        add_notes = st.checkbox(
            "Add tolerance notes", value=False,
            help="Stamp the standard tolerance NOTES block (bends, formed dims, "
                 "bend angles) above the title block on any sheet that does not "
                 "already have it. Sheets that already show NOTES are skipped.")
    custom_logo = None
    if doc_type not in ("Model numbers only", "Hybrid 69 to Rev5 lookup"):
        custom_logo = st.file_uploader("Replacement logo (optional)",
                                       type=["png", "jpg", "jpeg"])
        st.markdown("Leave blank to use the built-in KCC logo.")
    st.divider()
    st.markdown("**Always eyeball the downloaded file** before sending it on - "
                "logo detection and tight model cells are the parts most worth a "
                "glance.")

if doc_type == "Hybrid 69 to Rev5 lookup":
    from reverse import reverse as _reverse

    st.caption(MODE_BLURB["Hybrid 69 to Rev5 lookup"])
    st.subheader("Hybrid 69 to Rev5 lookup")
    txt = st.text_area(
        "Hybrid model number(s) - one per line",
        height=110,
        placeholder="OAKG040E3-DAB1GB900-S1BGL1AJ3-24A11J03CGF1C03000-AA1000000-00AM00000")
    c1, c2 = st.columns([1, 6])
    if c1.button("Convert", type="primary"):
        st.session_state["rev5_input"] = txt
    if c2.button("Clear"):
        st.session_state.pop("rev5_input", None)

    pending = st.session_state.get("rev5_input", "")
    if pending.strip():
        for raw in [ln.strip() for ln in pending.splitlines() if ln.strip()]:
            try:
                res = _reverse(raw)
            except Exception as exc:                      # noqa: BLE001
                st.error(f"{raw}: {exc}")
                continue
            st.markdown("---")
            st.caption(raw)
            if res["model"]:
                st.markdown(f"### `{res['model']}`")
            if res["etos"]:
                st.markdown("**Pre-approved ETOs required** - these are not "
                            "carried in the rev5 model number and must be added "
                            "to the order:")
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
    st.stop()


st.caption(MODE_BLURB.get(doc_type, "") +
           ("  Files are processed in memory and are not stored on the server."
            if doc_type != "Hybrid 69 to Rev5 lookup" else ""))

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
            if doc_type == "Model numbers only":
                report = convert_models_pdf(in_path, out_path)
            else:
                cfg = DRAWING_CONFIG if doc_type == "Drawing" else None
                report = rebrand_pdf(in_path, out_path, logo_path, config=cfg,
                                     add_notes=add_notes,
                                     convert_models=convert_models)

        c1, c2, c3 = st.columns(3)
        if doc_type == "Model numbers only":
            c1.metric("Model numbers converted", len(report.get("models", [])))
            c2.metric("Pages changed", len(report.get("scope_pages", [])))
        else:
            c1.metric("Text replacements", len(report["text"]))
            c2.metric("Logos swapped", len(report["logos"]))
        c3.metric("Warnings", len(report["warnings"]))

        models = report.get("models", [])
        if models:
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
                    st.dataframe(
                        [{"Digit": "d" + ",".join(map(str, d)), "Code": c,
                          "Flag": lvl, "Derived from": str(w)[:70]}
                         for d, c, lvl, w in nt],
                        use_container_width=True, hide_index=True)
            st.info("BETA - model conversion is new. Check the numbers above, "
                    "especially anything flagged, before releasing the submittal.")

        if report.get("notes"):
            st.success(f"Tolerance notes added on page(s): {report['notes']}")
        for w in report["warnings"]:
            st.warning(w)

        with open(out_path, "rb") as fh:
            data = fh.read()
        out_name = uploaded.name.rsplit(".", 1)[0] + "_KCC.pdf"
        label = ("Download converted submittal"
                 if doc_type == "Model numbers only"
                 else f"Download KCC {doc_type.lower()}")
        st.download_button(label, data=data,
                           file_name=out_name, mime="application/pdf",
                           type="primary")

        st.subheader("Before / after (page 1)")
        a, b = st.columns(2)
        a.image(_png(in_path), caption="Original", use_container_width=True)
        b.image(_png(out_path), caption="Rebranded", use_container_width=True)

        with st.expander(f"All {len(report['text'])} text replacements"):
            for pno, old, new in report["text"]:
                st.text(f"p{pno}:  {old!r}  ->  {new!r}")
