"""
Interface Streamlit — Agent diagnostic IA TPE/PME (NovetIA).
Lancement : streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from src.agent import run_diagnostic
from src.config import get_settings
from src.report import build_report_markdown, generate_markdown_report

st.set_page_config(page_title="NovetIA — Diagnostic IA", layout="wide")

st.title("NovetIA — Agent diagnostic IA")
st.caption("Test technique alternance IA & Innovation : dirigeant TPE/PME, scoring + enrichissement LLM.")

with st.sidebar:
    st.subheader("Configuration LLM")
    try:
        cfg = get_settings()
        st.text(f"Provider : {cfg.llm_provider}")
        if cfg.llm_provider == "openai":
            st.caption(f"Modèle : {cfg.openai_model}")
        elif cfg.llm_provider == "mistral":
            st.caption(f"Modèle : {cfg.mistral_model}")
        else:
            st.caption(f"Ollama : {cfg.ollama_model} @ {cfg.ollama_base_url}")
    except Exception as e:  # noqa: BLE001
        st.warning(str(e))

st.markdown(
    "Renseignez le formulaire ci-dessous. L'agent combine une **base de cas JSON**, "
    "un **scoring déterministe** et un **appel LLM** pour formuler trois recommandations prioritaires."
)

with st.form("diagnostic_form"):
    col1, col2 = st.columns(2)
    with col1:
        entreprise = st.text_input("Nom de l'entreprise", placeholder="Ex. Atelier Dupont")
        secteur = st.text_input("Secteur d'activité", placeholder="Ex. commerce, BTP, services…")
        taille = st.selectbox(
            "Taille de l'entreprise",
            ["1–9 salariés", "10–49 salariés", "50–249 salariés", "250+ salariés"],
        )
        maturite = st.select_slider(
            "Niveau de maturité numérique",
            options=["Très faible", "Faible", "Moyen", "Bon", "Élevé"],
            value="Moyen",
        )
    with col2:
        problemes = st.text_area("Principaux problèmes rencontrés", height=100, placeholder="Délais, qualité, charge…")
        taches_rep = st.text_area("Tâches répétitives", height=100, placeholder="Saisie, emails, devis…")
        outils = st.text_input("Outils actuellement utilisés", placeholder="Excel, CRM, messagerie…")
        objectif = st.text_input("Objectif prioritaire", placeholder="Réduire le temps admin, vendre plus…")

    submitted = st.form_submit_button("Lancer le diagnostic", type="primary")

if submitted:
    if not entreprise.strip():
        st.error("Indiquez au minimum le nom de l'entreprise.")
    else:
        company = {
            "entreprise": entreprise.strip(),
            "secteur": secteur.strip(),
            "taille": taille,
            "problemes": problemes.strip(),
            "taches_repetitives": taches_rep.strip(),
            "outils": outils.strip(),
            "objectif": objectif.strip(),
            "maturite": maturite,
        }
        with st.spinner("Analyse en cours (scoring + LLM)…"):
            result = run_diagnostic(company)
        st.session_state["last_company"] = company
        st.session_state["last_result"] = result

if "last_result" in st.session_state:
    res = st.session_state["last_result"]
    company = st.session_state.get("last_company", {})

    err = res.get("llm_error")
    if res.get("used_llm"):
        if err:
            st.warning(err)
        else:
            st.success("Recommandations enrichies par le LLM.")
    elif err:
        st.warning(err)
    else:
        st.info("Mode scoring déterministe.")

    st.subheader("Trois cas d'usage IA prioritaires")
    for i, rec in enumerate(res.get("recommendations", []), start=1):
        with st.expander(f"{i}. {rec.get('title', 'Cas')}", expanded=(i == 1)):
            st.markdown(rec.get("summary", ""))
            c1, c2, c3 = st.columns(3)
            c1.metric("Gain de temps (estim.)", rec.get("time_saved", "—")[:40] + ("…" if len(str(rec.get("time_saved", ""))) > 40 else ""))
            c2.metric("Difficulté", str(rec.get("difficulty", "—"))[:24])
            c3.metric("ROI (indicatif)", str(rec.get("roi", "—"))[:28])
            st.markdown(f"**Impact** : {rec.get('impact', '—')}")
            st.markdown(f"**Prochaines étapes** : {rec.get('next_steps', '—')}")

    st.divider()
    st.subheader("Rapport Markdown")
    md = build_report_markdown(company, res.get("recommendations", []))
    st.markdown(md)
    c_dl, c_save = st.columns(2)
    with c_dl:
        st.download_button(
            label="Télécharger le rapport (.md)",
            data=md.encode("utf-8"),
            file_name="rapport_diagnostic_ia.md",
            mime="text/markdown",
        )
    with c_save:
        if st.button("Enregistrer dans outputs/"):
            path = generate_markdown_report(company, res.get("recommendations", []))
            st.success(f"Fichier créé : `{path}`")
