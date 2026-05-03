"""
Interface Streamlit — Agent diagnostic IA TPE/PME (NovetIA).
Lancement : streamlit run app.py
"""

from __future__ import annotations

import copy
import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st

from src.agent import run_diagnostic
from src.config import get_settings
from src.llm_provider import _ollama_post_json
from src.report import build_report_markdown, generate_pdf_report

# TODO: réactiver l'envoi email après configuration SMTP ou API email (voir src/email_report.py).

# --- Authentification démo ----------------------------------------------------
# Volontairement minimal : identifiants en dur, session navigateur uniquement.
# Ne pas journaliser ni afficher les mots de passe.
# TODO production : utilisateurs en base, mots de passe hashés (ex. bcrypt / Argon2),
# flux de connexion sécurisé (HTTPS, gestion de session côté serveur ou tokens).

DEMO_USERS: dict[str, dict[str, str]] = {
    "client@demo.fr": {"password": "client123", "role": "user"},
    "admin@demo.fr": {"password": "admin123", "role": "admin"},
}


def init_auth() -> None:
    if "is_authenticated" not in st.session_state:
        st.session_state.is_authenticated = False
    if "current_user" not in st.session_state:
        st.session_state.current_user = None
    if "current_role" not in st.session_state:
        st.session_state.current_role = None


def authenticate_user(email: str, password: str) -> tuple[bool, str | None]:
    """Valide email / mot de passe contre les comptes démo. Ne trace jamais le secret."""
    key = email.strip().lower()
    row = DEMO_USERS.get(key)
    if not row or row["password"] != password:
        return False, None
    return True, row["role"]


def logout() -> None:
    """Termine la session applicative (démo : réinitialise aussi l'historique de session)."""
    st.session_state.is_authenticated = False
    st.session_state.current_user = None
    st.session_state.current_role = None
    st.session_state.history = []
    st.session_state.loaded_diagnostic = None
    st.session_state.chat_history = []
    st.session_state.current_page = "chat"
    for k in ("_report_sig", "_report_pdf_bytes", "_report_pdf_error"):
        st.session_state.pop(k, None)


def render_login_screen() -> None:
    st.markdown("# Connexion")
    st.caption("Identifiez-vous pour accéder à l’agent diagnostic IA.")

    with st.form("login_form"):
        email_in = st.text_input("Email", placeholder="vous@entreprise.fr")
        password_in = st.text_input("Mot de passe", type="password")
        submit = st.form_submit_button("Connexion")

    if submit:
        ok, role = authenticate_user(email_in, password_in)
        if ok:
            st.session_state.is_authenticated = True
            st.session_state.current_user = email_in.strip().lower()
            st.session_state.current_role = role
            st.session_state.current_page = "chat"
            st.session_state.chat_history = []
            st.rerun()
        else:
            st.error("Email ou mot de passe incorrect.")


def render_user_sidebar() -> None:
    st.markdown("### Session")
    user_email = st.session_state.get("current_user") or "—"
    role_raw = st.session_state.get("current_role")
    role_display = (
        "Administrateur"
        if role_raw == "admin"
        else "Utilisateur"
        if role_raw == "user"
        else "—"
    )
    st.caption(user_email)
    st.caption(f"Rôle : {role_display}")
    if st.button("Se déconnecter", use_container_width=True):
        logout()
        st.rerun()
    st.divider()


def render_navigation_sidebar() -> None:
    """Bascule entre la vue chat locale et le diagnostic métier."""
    st.markdown("### Navigation")
    page = st.session_state.get("current_page", "chat")
    if st.button(
        "Assistant IA local",
        use_container_width=True,
        type="primary" if page == "chat" else "secondary",
        key="nav_sidebar_chat",
    ):
        st.session_state.current_page = "chat"
        st.rerun()
    if st.button(
        "Diagnostic IA de l'entreprise",
        use_container_width=True,
        type="primary" if page == "diagnostic" else "secondary",
        key="nav_sidebar_diagnostic",
    ):
        st.session_state.current_page = "diagnostic"
        st.rerun()
    st.divider()


def render_admin_panel() -> None:
    if st.session_state.get("current_role") != "admin":
        return
    hist = st.session_state.get("history") or []
    with st.expander("Espace admin", expanded=False):
        st.caption(f"Diagnostics réalisés (session) : **{len(hist)}**")
        if not hist:
            st.caption("Dernier diagnostic : —")
            st.caption("Score moyen (indice interne) : —")
            return
        last = hist[-1]
        st.caption(
            f"Dernier diagnostic : **{last.get('entreprise', '—')}** "
            f"({last.get('ts_display', '—')})"
        )
        scores = [float(e["score_global"]) for e in hist if e.get("score_global") is not None]
        if scores:
            avg = sum(scores) / len(scores)
            st.caption(f"Score moyen (indice interne) : **{avg:.1f}**")
        else:
            st.caption("Score moyen (indice interne) : —")


# --- Navigation & chat Ollama local ------------------------------------------
# Le chat utilise la même config Ollama que le projet (get_settings → OLLAMA_*),
# via _ollama_post_json (src/llm_provider.py) pour l’appel /api/chat (pas d’API cloud ni clés).


def init_navigation() -> None:
    if "current_page" not in st.session_state:
        st.session_state.current_page = "chat"


def init_chat_history() -> None:
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []


def detect_diagnostic_intent(user_message: str) -> bool:
    """
    Détecte une demande d’ouverture du parcours « Diagnostic IA » (sans appel LLM).
    Règles simples : texte en minuscules + sous-chaînes / combinaisons de mots-clés.
    """
    t = user_message.strip().lower()
    if not t:
        return False
    t = t.replace("’", "'")

    phrases = (
        "je veux faire un diagnostic",
        "faire un diagnostic ia",
        "faire un diagnostic",
        "lance le diagnostic",
        "lance diagnostic",
        "lancer le diagnostic",
        "lancer diagnostic",
        "ouvre le diagnostic",
        "ouvre diagnostic",
        "ouvrir le diagnostic",
        "va sur diagnostic",
        "va au diagnostic",
        "aller au diagnostic",
        "passer au diagnostic",
        "diagnostic ia de l'entreprise",
        "diagnostic ia",
        "audit ia",
        "analyse mon entreprise",
        "diagnostic de mon entreprise",
        "diagnostic de l'entreprise",
        "diagnostic entreprise",
    )
    if any(p in t for p in phrases):
        return True
    if "diagnostic" in t and any(
        x in t
        for x in (
            "lance",
            "lancer",
            "ouvre",
            "ouvrir",
            "va sur",
            "va au",
            "aller",
            "passer",
            "ouvre-moi",
        )
    ):
        return True
    if "diagnostic" in t and "entreprise" in t:
        return True
    return False


def call_ollama_chat(history: list[dict[str, str]]) -> str:
    """Appelle Ollama /api/chat avec get_settings() (OLLAMA_BASE_URL, OLLAMA_MODEL)."""
    try:
        cfg = get_settings()
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    url = f"{cfg.ollama_base_url.rstrip('/')}/api/chat"
    payload: dict[str, Any] = {
        "model": cfg.ollama_model,
        "messages": history,
        "stream": False,
    }
    data = _ollama_post_json(url, payload, cfg.ollama_model)
    msg = data.get("message") or {}
    content = msg.get("content")
    if content is None or str(content).strip() == "":
        raise RuntimeError(
            f"Réponse vide depuis Ollama (chat). Essayez : ollama pull {cfg.ollama_model}"
        )
    return str(content)


def render_chat_page() -> None:
    init_chat_history()
    cfg_ok = None
    try:
        cfg_ok = get_settings()
    except ValueError as exc:
        st.error(str(exc))

    st.markdown("# Assistant IA local")
    st.caption("Discutez avec le modèle local avant de lancer un diagnostic structuré.")
    if cfg_ok is not None:
        st.caption(
            f"**Ollama** (chat) : `{cfg_ok.ollama_model}` @ `{cfg_ok.ollama_base_url}` · "
            f"fournisseur **diagnostic** configuré : **{cfg_ok.llm_provider}**"
        )

    if err_chat := st.session_state.pop("_chat_error", None):
        with st.container():
            st.error(err_chat)

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Votre message"):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        if detect_diagnostic_intent(prompt):
            st.session_state.chat_history.append(
                {
                    "role": "assistant",
                    "content": "Bien sûr, je t’ouvre le diagnostic IA de l’entreprise.",
                }
            )
            st.session_state.current_page = "diagnostic"
            st.rerun()
        try:
            with st.spinner("Réponse du modèle local…"):
                reply = call_ollama_chat(st.session_state.chat_history)
            st.session_state.chat_history.append({"role": "assistant", "content": reply})
        except RuntimeError as exc:
            st.session_state.chat_history.pop()
            st.session_state["_chat_error"] = str(exc)
        st.rerun()

    render_footer_signature()


def render_diagnostic_page() -> None:
    st.markdown("# Diagnostic IA TPE/PME")
    st.caption("Démo — scoring déterministe et enrichissement LLM.")
    try:
        cfg = get_settings()
        if cfg.llm_provider == "openai":
            st.caption(
                f"**LLM diagnostic** : OpenAI (`{cfg.openai_model}`). "
                "Les résultats indiquent si l’appel a réussi ou si le **repli scoring** s’applique."
            )
        elif cfg.llm_provider == "mistral":
            st.caption(
                f"**LLM diagnostic** : Mistral (`{cfg.mistral_model}`). "
                "Les résultats indiquent si l’appel a réussi ou si le **repli scoring** s’applique."
            )
        else:
            st.caption(
                f"**LLM diagnostic** : Ollama local (`{cfg.ollama_model}` @ `{cfg.ollama_base_url}`). "
                "Les résultats indiquent si l’appel a réussi ou si le **repli scoring** s’applique."
            )
    except ValueError as exc:
        st.error(str(exc))

    if st.session_state.pop("_toast_diagnostic_reloaded", False):
        st.success("Diagnostic rechargé")
    if st.session_state.pop("_toast_history_reset", False):
        st.success("Historique réinitialisé")

    submitted, company = render_diagnostic_form()

    if submitted and company is not None:
        with st.spinner("Analyse en cours (scoring + LLM)…"):
            result = run_diagnostic(company)
        save_diagnostic_to_history(company, result)
        st.rerun()

    company_view: dict[str, Any] | None = None
    res_view: dict[str, Any] | None = None
    init_history()
    _hist = st.session_state.history
    _ld = st.session_state.get("loaded_diagnostic")
    if isinstance(_ld, dict):
        _hi = _ld.get("history_index")
        if _hi is None or _hi < 0 or _hi >= len(_hist):
            st.session_state.loaded_diagnostic = None
        else:
            _co = _ld.get("company")
            _re = _ld.get("result")
            if _co is not None and _re is not None:
                company_view, res_view = _co, _re

    if company_view and res_view:
        st.divider()
        render_results(company_view, res_view)

    render_footer_signature()


# --- Historique session ------------------------------------------------------


def init_history() -> None:
    """Initialise les clés d'historique dans session_state."""
    if "history" not in st.session_state:
        st.session_state.history = []
    if "loaded_diagnostic" not in st.session_state:
        st.session_state.loaded_diagnostic = None


def _now_local_str() -> str:
    return datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")


def global_score_from_result(res: dict[str, Any]) -> float | None:
    """Score global : moyenne des 3 premiers scores du moteur ou des recommandations."""
    ranked = res.get("ranked_scores") or []
    if ranked:
        vals = [float(s[0]) for s in ranked[:3]]
        if vals:
            return round(sum(vals) / len(vals), 1)
    recs = res.get("recommendations") or []
    nums = [float(r["score"]) for r in recs if r.get("score") is not None]
    if nums:
        return round(sum(nums[:3]) / min(len(nums), 3), 1)
    return None


def priority_level_from_score(score: float | None) -> str:
    if score is None:
        return "—"
    if score >= 14:
        return "Élevée"
    if score >= 8:
        return "Moyenne"
    return "Standard"


def raw_score_to_100(raw: float | None) -> int | None:
    """Convertit l'indice de scoring interne en note indicative 0–100 (démo)."""
    if raw is None:
        return None
    return min(100, max(0, int(round(raw * 5))))


def save_diagnostic_to_history(company: dict[str, Any], result: dict[str, Any]) -> None:
    """Ajoute un diagnostic à history (données figées, sans rappel LLM au rechargement)."""
    init_history()
    gs = global_score_from_result(result)
    recs = result.get("recommendations") or []
    report_md = build_report_markdown(company, recs)
    entry: dict[str, Any] = {
        "ts_iso": datetime.now(timezone.utc).isoformat(),
        "ts_display": _now_local_str(),
        "entreprise": company.get("entreprise", "—"),
        "secteur": company.get("secteur", "") or "—",
        "score_global": gs,
        "score_global_100": raw_score_to_100(gs),
        "company": copy.deepcopy(company),
        "result": copy.deepcopy(result),
        "report_markdown": report_md,
    }
    st.session_state.history.append(entry)
    new_idx = len(st.session_state.history) - 1
    st.session_state.loaded_diagnostic = {
        "history_index": new_idx,
        "company": st.session_state.history[new_idx]["company"],
        "result": st.session_state.history[new_idx]["result"],
    }


def inject_hide_sidebar_when_logged_out() -> None:
    """
    Masque la sidebar Streamlit et le bouton d'ouverture tant que l'utilisateur n'est pas
    authentifié (écran de connexion épuré, tous appareils).
    """
    if st.session_state.get("is_authenticated"):
        return
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"],
        [data-testid="stSidebar"] { display: none !important; }
        [data-testid="collapsedControl"] { display: none !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def inject_minimal_styles() -> None:
    st.markdown(
        """
        <style>
        /* Espacement lecture, tons neutres */
        .block-container { padding-top: 1.25rem; padding-bottom: 2rem; max-width: 920px; }
        h1 { font-weight: 600; letter-spacing: -0.02em; color: #1a1a1a; }
        [data-testid="stSidebar"] { background-color: #fafafa; border-right: 1px solid #eaeaea; }
        section[data-testid="stSidebar"] button {
            justify-content: flex-start !important;
            text-align: left !important;
            white-space: normal !important;
            min-height: auto !important;
            padding-top: 0.35rem !important;
            padding-bottom: 0.35rem !important;
            font-size: 0.8125rem !important;
            line-height: 1.25 !important;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background: #fdfdfd !important;
            border-color: #e8e8e8 !important;
            border-radius: 6px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_llm_sidebar_compact() -> None:
    with st.expander("Configuration LLM", expanded=False):
        try:
            cfg = get_settings()
        except ValueError as exc:
            st.error(str(exc))
            return
        prov = cfg.llm_provider
        if prov == "openai":
            st.caption("**Diagnostic** : OpenAI (API externe)")
            st.caption(f"Modèle : `{cfg.openai_model}`")
        elif prov == "mistral":
            st.caption("**Diagnostic** : Mistral (API externe)")
            st.caption(f"Modèle : `{cfg.mistral_model}`")
        else:
            st.caption("**Diagnostic** : Ollama **local**")
            st.caption(f"Modèle : `{cfg.ollama_model}` @ `{cfg.ollama_base_url}`")
        st.caption(
            "**Assistant IA local (chat)** : utilise les mêmes `OLLAMA_BASE_URL` et `OLLAMA_MODEL`."
        )


def render_history_sidebar() -> None:
    """Liste verticale cliquable type navigation (du plus récent au plus ancien)."""
    init_history()
    history: list[dict[str, Any]] = st.session_state.history

    st.markdown("### Historique")
    if not history:
        st.caption("Aucun diagnostic dans l'historique")
        return

    ld = st.session_state.get("loaded_diagnostic")
    loaded_idx: int | None = ld.get("history_index") if isinstance(ld, dict) else None

    for hist_idx in range(len(history) - 1, -1, -1):
        entry = history[hist_idx]
        name = str(entry.get("entreprise", "—"))
        s100 = entry.get("score_global_100")
        score_label = f"Score {s100}/100" if s100 is not None else "Score —"
        tsdisp = str(entry.get("ts_display") or "")
        date_short = tsdisp.split()[0] if tsdisp else ""
        line1 = f"{name} — {score_label}"
        label = f"{line1}\n{date_short}" if date_short else line1
        is_selected = loaded_idx == hist_idx
        if st.button(
            label,
            key=f"history_item_{hist_idx}",
            use_container_width=True,
            type="primary" if is_selected else "secondary",
        ):
            st.session_state.loaded_diagnostic = {
                "history_index": hist_idx,
                "company": entry["company"],
                "result": entry["result"],
            }
            st.session_state["_toast_diagnostic_reloaded"] = True
            st.rerun()

    if st.button("Réinitialiser l'historique", type="secondary", use_container_width=True):
        st.session_state.history = []
        st.session_state.loaded_diagnostic = None
        for k in ("_report_sig", "_report_pdf_bytes", "_report_pdf_error"):
            st.session_state.pop(k, None)
        st.session_state["_toast_history_reset"] = True
        st.rerun()

    st.divider()


def render_diagnostic_form() -> tuple[bool, dict[str, Any] | None]:
    """Formulaire compact ; retourne (submitted, company ou None)."""
    with st.form("diagnostic_form"):
        col1, col2 = st.columns(2, gap="medium")
        with col1:
            entreprise = st.text_input("Nom de l’entreprise", placeholder="Ex. Atelier Dupont")
            secteur = st.text_input("Secteur d’activité", placeholder="Ex. commerce, BTP, services…")
            taille = st.selectbox(
                "Taille",
                ["1–9 salariés", "10–49 salariés", "50–249 salariés", "250+ salariés"],
            )
            maturite = st.select_slider(
                "Maturité numérique",
                options=["Très faible", "Faible", "Moyen", "Bon", "Élevé"],
                value="Moyen",
            )
        with col2:
            problemes = st.text_area("Problèmes principaux", height=88, placeholder="Délais, qualité, charge…")
            taches_rep = st.text_area("Tâches répétitives", height=88, placeholder="Saisie, emails, devis…")
            outils = st.text_input("Outils actuels", placeholder="Excel, CRM, messagerie…")
            objectif = st.text_input("Objectif prioritaire", placeholder="Réduire l’admin, vendre plus…")

        submitted = st.form_submit_button("Lancer le diagnostic")

    if not submitted:
        return False, None

    if not entreprise.strip():
        st.error("Indiquez au minimum le nom de l’entreprise.")
        return True, None

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
    return True, company


def render_results_cards(company: dict[str, Any], res: dict[str, Any]) -> None:
    """Cartes synthèse : score, priorité, ROI, action, 3 recommandations."""
    recs = res.get("recommendations") or []
    gs = global_score_from_result(res)
    prio = priority_level_from_score(gs)

    top = recs[0] if recs else {}
    roi_main = str(top.get("roi", "—")).strip() or "—"
    next_action = str(top.get("next_steps", "—")).strip() or "—"
    if len(next_action) > 220:
        next_action = next_action[:217] + "…"

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

    c1, c2, c3 = st.columns(3)
    with c1:
        with st.container(border=True):
            st.caption("Score global (indice interne)")
            st.markdown(f"## {gs if gs is not None else '—'}")
    with c2:
        with st.container(border=True):
            st.caption("Niveau de priorité")
            st.markdown(f"## {prio}")
    with c3:
        with st.container(border=True):
            st.caption("ROI estimé (1re reco.)")
            st.markdown(f"### {roi_main}")

    with st.container(border=True):
        st.caption("Prochaine action conseillée")
        if top.get("title"):
            st.markdown(f"**{top.get('title')}**")
        st.markdown(next_action)

    st.markdown("#### Trois recommandations prioritaires")
    for i, rec in enumerate(recs[:3], start=1):
        with st.container(border=True):
            st.markdown(f"**{i}.** {rec.get('title', 'Cas')}")
            st.markdown(rec.get("summary", "") or "—")
            r1, r2, r3 = st.columns(3)
            ts = str(rec.get("time_saved", "—"))
            if len(ts) > 42:
                ts = ts[:39] + "…"
            r1.metric("Gain temps (estim.)", ts)
            r2.metric("Difficulté", str(rec.get("difficulty", "—"))[:24])
            r3.metric("ROI", str(rec.get("roi", "—"))[:28])


def _ensure_pdf_cached(md: str) -> tuple[bytes | None, str | None]:
    """Met à jour le PDF en session si le rapport Markdown a changé ; retourne (pdf_bytes, err)."""
    sig = hashlib.sha256(md.encode("utf-8")).hexdigest()
    if st.session_state.get("_report_sig") != sig:
        st.session_state["_report_sig"] = sig
        st.session_state["_report_pdf_bytes"] = None
        st.session_state["_report_pdf_error"] = None
        try:
            fd, tmp_pdf = tempfile.mkstemp(suffix=".pdf")
            os.close(fd)
            try:
                generate_pdf_report(md, tmp_pdf)
                st.session_state["_report_pdf_bytes"] = Path(tmp_pdf).read_bytes()
            finally:
                try:
                    os.unlink(tmp_pdf)
                except OSError:
                    pass
        except Exception as exc:  # noqa: BLE001 — affichage utilisateur
            st.session_state["_report_pdf_error"] = str(exc)

    pdf_bytes = st.session_state.get("_report_pdf_bytes")
    pdf_err = st.session_state.get("_report_pdf_error")
    return pdf_bytes if isinstance(pdf_bytes, (bytes, bytearray)) else None, pdf_err


def render_report_actions(
    pdf_bytes: bytes | None,
    pdf_err: str | None,
    report_sig: str,
) -> None:
    """Téléchargement du rapport PDF (V1 sans envoi email)."""
    st.markdown("#### Rapport détaillé")
    st.caption("Téléchargez le rapport généré au format PDF.")

    if pdf_err:
        st.error(f"Export PDF impossible : {pdf_err}")
        return

    if not pdf_bytes:
        st.warning("PDF non disponible.")
        return

    key_suffix = report_sig[:16]
    st.download_button(
        label="Télécharger le rapport PDF",
        data=pdf_bytes,
        file_name="rapport_diagnostic_ia.pdf",
        mime="application/pdf",
        key=f"dl_pdf_report_{key_suffix}",
        type="primary",
    )


def render_report_section(company: dict[str, Any], res: dict[str, Any]) -> None:
    recommendations = res.get("recommendations", [])
    md = build_report_markdown(company, recommendations)
    sig = hashlib.sha256(md.encode("utf-8")).hexdigest()
    pdf_bytes, pdf_err = _ensure_pdf_cached(md)
    render_report_actions(pdf_bytes, pdf_err, sig)


def render_results(company: dict[str, Any], res: dict[str, Any]) -> None:
    render_results_cards(company, res)
    st.divider()
    render_report_section(company, res)


# --- App ---------------------------------------------------------------------
def render_footer_signature() -> None:
    st.markdown(
        """
        <div style="
            margin-top: 48px;
            padding-top: 12px;
            border-top: 1px solid #e5e7eb;
            text-align: center;
            color: #9ca3af;
            font-size: 0.78rem;
        ">
            Démo technique — Agent diagnostic IA · Eliot COLLOMB
        </div>
        """,
        unsafe_allow_html=True,
    )


st.set_page_config(page_title="NovetIA — Diagnostic IA", layout="wide", initial_sidebar_state="collapsed")
init_auth()
init_history()
init_navigation()
init_chat_history()

inject_minimal_styles()
if not st.session_state.is_authenticated:
    inject_hide_sidebar_when_logged_out()
    render_login_screen()
    st.stop()

with st.sidebar:
    render_user_sidebar()
    render_navigation_sidebar()
    render_llm_sidebar_compact()
    if st.session_state.current_page == "diagnostic":
        render_history_sidebar()
        render_admin_panel()

if st.session_state.current_page == "chat":
    render_chat_page()
else:
    render_diagnostic_page()