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
from src.demo_auth import validate_login
from src.local_chat import detect_diagnostic_intent, run_ollama_chat_assistant
from src.report import build_report_markdown, generate_pdf_report

# TODO: réactiver l'envoi email après configuration SMTP ou API email (voir src/email_report.py).

# --- Authentification démo ----------------------------------------------------
# Identifiants : CLIENT_EMAIL, CLIENT_PASSWORD, ADMIN_EMAIL, ADMIN_PASSWORD (.env).
# Chargement via os.getenv dans src/demo_auth.py (après load_dotenv dans src/config.py).
# Session navigateur uniquement. Ne pas journaliser les mots de passe.
# TODO production : utilisateurs en base, mots de passe hashés (ex. bcrypt / Argon2),
# flux de connexion sécurisé (HTTPS, gestion de session côté serveur ou tokens).


def init_auth() -> None:
    if "is_authenticated" not in st.session_state:
        st.session_state.is_authenticated = False
    if "current_user" not in st.session_state:
        st.session_state.current_user = None
    if "current_role" not in st.session_state:
        st.session_state.current_role = None


def complete_login(email: str, role: str | None) -> None:
    """Établit la session après authentification réussie."""
    if not role:
        return
    st.session_state.is_authenticated = True
    st.session_state.current_user = email.strip().lower()
    st.session_state.current_role = role
    st.session_state.current_page = "chat"
    st.session_state.chat_history = []


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
    st.caption(
        "Comptes de démonstration uniquement — ne pas utiliser en production.",
    )

    with st.form("login_form"):
        email_in = st.text_input("Email", placeholder="vous@entreprise.fr")
        password_in = st.text_input("Mot de passe", type="password")
        submit = st.form_submit_button("Connexion")

    if submit:
        ok, role = validate_login(email_in, password_in)
        if ok:
            complete_login(email_in, role)
            st.rerun()
        else:
            st.error(
                "Identifiants incorrects. Vérifiez l’adresse e-mail et le mot de passe. "
                "Pour la démo locale, les comptes par défaut sont configurés dans le fichier "
                "`.env` (variables CLIENT_* et ADMIN_* — voir `.env.example`)."
            )


def render_user_sidebar() -> None:
    st.markdown("#### Session")
    user_email = st.session_state.get("current_user") or "—"
    role_raw = st.session_state.get("current_role")
    role_display = (
        "Administrateur"
        if role_raw == "admin"
        else "Utilisateur"
        if role_raw == "user"
        else "—"
    )
    st.caption(f"👤 {user_email}")
    st.caption(f"🔑 Rôle : **{role_display}**")
    if st.button("🚪 Se déconnecter", use_container_width=True):
        logout()
        st.rerun()
    st.divider()


def render_navigation_sidebar() -> None:
    """Bascule entre la vue chat locale et le diagnostic métier."""
    st.markdown("#### Navigation")
    page = st.session_state.get("current_page", "chat")
    if st.button(
        "💬 Assistant IA local",
        use_container_width=True,
        type="primary" if page == "chat" else "secondary",
        key="nav_sidebar_chat",
    ):
        st.session_state.current_page = "chat"
        st.rerun()
    if st.button(
        "📋 Diagnostic IA entreprise",
        use_container_width=True,
        type="primary" if page == "diagnostic" else "secondary",
        key="nav_sidebar_diagnostic",
    ):
        st.session_state.current_page = "diagnostic"
        st.rerun()
    active = "Assistant IA local" if page == "chat" else "Diagnostic IA entreprise"
    st.caption(f"📍 Page active : **{active}**")
    st.divider()


def render_configuration_sidebar() -> None:
    """Réglages LLM affichés dans la section Configuration."""
    st.markdown("#### Configuration")
    with st.expander("⚙️ Modèles et options (détail)", expanded=False):
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
            "**Chat local** : même serveur / modèle Ollama, avec options dédiées "
            f"(`OLLAMA_CHAT_TEMPERATURE`={cfg.ollama_chat_temperature}, "
            f"`OLLAMA_CHAT_MAX_TOKENS`={cfg.ollama_chat_num_predict}, "
            f"`OLLAMA_CHAT_NUM_CTX`={cfg.ollama_chat_num_ctx})."
        )


def render_admin_panel() -> None:
    if st.session_state.get("current_role") != "admin":
        return
    hist = st.session_state.get("history") or []
    with st.expander("🔐 Espace admin", expanded=False):
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
# Chat : src/local_chat.py (prompt système court + /api/chat + options OLLAMA_CHAT_*).
# Diagnostic : src/agent.py + LLMProvider (prompt long ; Ollama utilise /api/generate).


def init_navigation() -> None:
    if "current_page" not in st.session_state:
        st.session_state.current_page = "chat"


def init_chat_history() -> None:
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []


def call_ollama_chat(history: list[dict[str, str]]) -> str:
    """Délègue au module chat local (prompt système + options Ollama dédiées)."""
    try:
        cfg = get_settings()
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    return run_ollama_chat_assistant(history, cfg)


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
    st.write("")
    render_product_guide_expander()

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
    st.write("")
    render_product_guide_expander()

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
    report_md = build_report_markdown(
        company,
        recs,
        executive_summary=result.get("executive_summary"),
        final_recommendation=result.get("final_recommendation"),
    )
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
        section[data-testid="stSidebar"] h4 {
            font-size: 0.9rem !important;
            font-weight: 600 !important;
            letter-spacing: 0.02em;
            color: #374151 !important;
            margin-top: 0.35rem !important;
            margin-bottom: 0.4rem !important;
        }
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


def render_history_sidebar() -> None:
    """Liste verticale cliquable type navigation (du plus récent au plus ancien)."""
    init_history()
    history: list[dict[str, Any]] = st.session_state.history

    st.markdown("##### Historique (session)")
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

    if st.button("🗑️ Réinitialiser l'historique", type="secondary", use_container_width=True):
        st.session_state.history = []
        st.session_state.loaded_diagnostic = None
        for k in ("_report_sig", "_report_pdf_bytes", "_report_pdf_error"):
            st.session_state.pop(k, None)
        st.session_state["_toast_history_reset"] = True
        st.rerun()


def render_product_guide_expander() -> None:
    """Aide contextuelle : chat vs diagnostic, langage simple (hors logique métier)."""
    with st.expander("❓ Comprendre NovetIA — chat et diagnostic", expanded=False):
        st.markdown(
            """
**À quoi sert cet outil ?**  
Il vous aide à imaginer **concrètement** où l’intelligence artificielle peut vous faire gagner du temps ou clarifier un sujet, **sans** vous noyer de technique.

**Assistant IA local (conversation)**  
Vous discutez avec un modèle installé **sur votre machine**. Les réponses sont **courtes** et rapides : idéal pour une question ponctuelle, une définition ou pour s’orienter.  
Ce n’est **pas** une analyse complète de votre entreprise.

**Diagnostic IA de l’entreprise**  
Vous répondez à un **questionnaire** sur votre activité (taille, secteur, irritants, objectifs…). L’outil vous propose ensuite **trois pistes prioritaires**, une synthèse et un **rapport** à consulter ou à télécharger. C’est le parcours le plus **structuré** : synthèse, priorités et rapport à télécharger.

**En une phrase** : le **chat** répond vite à la volée ; le **diagnostic** s’appuie sur **vos réponses** pour un résultat **plus structuré** et actionnable.
            """.strip()
        )


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
    fr0 = res.get("final_recommendation")
    if isinstance(fr0, dict) and str(fr0.get("par_quoi_commencer", "")).strip():
        next_action = str(fr0.get("par_quoi_commencer")).strip()
    else:
        next_action = str(top.get("action_plan") or top.get("next_steps", "—")).strip() or "—"
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

    exec_txt = res.get("executive_summary")
    if exec_txt and str(exec_txt).strip():
        with st.container(border=True):
            st.markdown("#### Synthèse exécutive")
            st.markdown(str(exec_txt).strip().replace("\n", "\n\n"))

    fr = res.get("final_recommendation")
    if isinstance(fr, dict) and (
        str(fr.get("par_quoi_commencer", "")).strip() or str(fr.get("pourquoi", "")).strip()
    ):
        with st.container(border=True):
            st.markdown("#### Recommandation finale")
            if str(fr.get("par_quoi_commencer", "")).strip():
                st.markdown(f"**Par quoi commencer** : {fr.get('par_quoi_commencer')}")
            if str(fr.get("pourquoi", "")).strip():
                st.markdown(f"**Pourquoi** : {fr.get('pourquoi')}")

    with st.container(border=True):
        st.caption("Prochaine action conseillée")
        if top.get("title"):
            st.markdown(f"**{top.get('title')}**")
        st.markdown(next_action)

    st.markdown("#### Top 3 — cas d'usage IA priorisés")
    for i, rec in enumerate(recs[:3], start=1):
        with st.container(border=True):
            st.markdown(f"##### {rec.get('title', f'Cas {i}')}")
            obj = str(rec.get("business_objective", "")).strip()
            ex = str(rec.get("concrete_example", "")).strip()
            if obj:
                st.markdown(f"**Objectif métier** — {obj}")
            if ex:
                st.markdown(f"**Exemple concret** — {ex}")
            if not obj and not ex:
                st.markdown(rec.get("summary", "") or "—")
            r1, r2, r3 = st.columns(3)
            ts = str(rec.get("time_saved", "—"))
            if len(ts) > 42:
                ts = ts[:39] + "…"
            r1.metric("Gain temps (estim.)", ts)
            r2.metric("Difficulté", str(rec.get("difficulty", "—"))[:24])
            r3.metric("Horizon ROI", str(rec.get("roi", "—"))[:28])
            plan = str(rec.get("action_plan", rec.get("next_steps", ""))).strip()
            if plan and plan != "—":
                with st.expander("Plan d'action (4–8 semaines)", expanded=False):
                    st.markdown(plan.replace("\n", "\n\n"))


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


def render_results(company: dict[str, Any], res: dict[str, Any]) -> None:
    recommendations = res.get("recommendations", [])
    md = build_report_markdown(
        company,
        recommendations,
        executive_summary=res.get("executive_summary"),
        final_recommendation=res.get("final_recommendation"),
    )
    render_results_cards(company, res)
    st.divider()
    with st.expander("Aperçu du rapport (Markdown)", expanded=False):
        st.markdown(md)
    st.divider()
    sig = hashlib.sha256(md.encode("utf-8")).hexdigest()
    pdf_bytes, pdf_err = _ensure_pdf_cached(md)
    render_report_actions(pdf_bytes, pdf_err, sig)


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
    render_configuration_sidebar()
    if st.session_state.current_page == "diagnostic":
        render_history_sidebar()
        render_admin_panel()

if st.session_state.current_page == "chat":
    render_chat_page()
else:
    render_diagnostic_page()