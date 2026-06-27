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

from rebrand import rebrand_pdf

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOGO = os.path.join(HERE, "kcc_logo.png")

st.set_page_config(page_title="Submittal Rebrander", layout="wide")


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
    st.title("Submittal Rebrander")
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
st.title("Submittal Rebrander  -  Trane to KCC")
st.caption("Upload a Trane equipment submittal. Every 'Trane' mention and the "
           "header logo are replaced with KCC, and the result is returned for "
           "download. Files are processed in memory and are not stored on the server.")

with st.sidebar:
    st.header("Options")
    custom_logo = st.file_uploader("Replacement logo (optional)",
                                   type=["png", "jpg", "jpeg"])
    st.markdown("Leave blank to use the built-in KCC logo.")
    st.divider()
    st.markdown("**Always eyeball the downloaded file** before sending it on - "
                "logo detection and tight model cells are the parts most worth a "
                "glance.")

uploaded = st.file_uploader("Trane submittal (PDF)", type=["pdf"])


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
            report = rebrand_pdf(in_path, out_path, logo_path)

        c1, c2, c3 = st.columns(3)
        c1.metric("Text replacements", len(report["text"]))
        c2.metric("Logos swapped", len(report["logos"]))
        c3.metric("Warnings", len(report["warnings"]))

        for w in report["warnings"]:
            st.warning(w)

        with open(out_path, "rb") as fh:
            data = fh.read()
        out_name = uploaded.name.rsplit(".", 1)[0] + "_KCC.pdf"
        st.download_button("Download KCC submittal", data=data,
                           file_name=out_name, mime="application/pdf",
                           type="primary")

        st.subheader("Before / after (page 1)")
        a, b = st.columns(2)
        a.image(_png(in_path), caption="Original", use_container_width=True)
        b.image(_png(out_path), caption="Rebranded", use_container_width=True)

        with st.expander(f"All {len(report['text'])} text replacements"):
            for pno, old, new in report["text"]:
                st.text(f"p{pno}:  {old!r}  ->  {new!r}")
