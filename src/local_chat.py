"""
Assistant conversationnel Ollama (page Chat Streamlit).

Distinct du diagnostic IA (prompt long + JSON structuré dans src/agent.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Settings

# Prompt système court — uniquement pour /api/chat (assistant local).
LOCAL_CHAT_SYSTEM_PROMPT = """Tu es l’assistant conversationnel léger d’une démo produit (NovetIA).

Règles :
- Réponds toujours en français.
- Réponses courtes, claires et utiles : vise **5 à 8 lignes maximum**, sauf si l’utilisateur demande explicitement plus de détail.
- Pas de rapport structuré, pas de longues listes numérotées, pas d’analyse approfondie type cabinet de conseil.
- Ne réalise pas de diagnostic d’entreprise, de maturité IA, de cas d’usage priorisés, de ROI chiffré ni de recommandations structurées : pour cela, indique que c’est disponible dans la page **« Diagnostic IA de l’entreprise »** (navigation à gauche) et invite à s’y rendre.
- Pour les questions simples (définitions, usages généraux, aide à reformuler, conseils rapides), réponds normalement et reste synthétique."""

_MAX_CHAT_MESSAGES = 12  # paires user/assistant récentes pour limiter le contexte


def detect_diagnostic_intent(user_message: str) -> bool:
    """
    Détecte une intention d’accès au parcours « Diagnostic IA » structuré (sans appel LLM).
    """
    t = user_message.strip().lower()
    if not t:
        return False
    t = t.replace("’", "'")

    phrases = (
        "je veux faire un diagnostic",
        "je veux faire un diagnostic ia",
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
        "trouve des cas d'usage",
        "trouve des cas d'usage ia",
        "trouver des cas d'usage",
        "cas d'usage ia pour",
        "quels usages ia",
        "quels cas d'usage ia",
        "usages ia pour ma pme",
        "usage ia pour ma",
        "usage ia pour mon",
        "quels usages ia pour",
        "calcule le roi ia",
        "calculer le roi ia",
        "roi ia de",
        "roi ia pour",
        "calcule roi ia",
        "fais-moi une recommandation ia",
        "fait moi une recommandation ia",
        "recommandation ia pour",
        "recommandation ia de",
        "maturité ia",
        "maturite ia",
        "analyse de maturité",
        "analyse de maturite",
        "diagnostic de maturité",
        "diagnostic de maturite",
        "évaluation maturité ia",
        "evaluation maturite ia",
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
    if ("cas d'usage" in t or "cas d usage" in t) and ("ia" in t or "intelligence artificielle" in t):
        return True
    if "roi" in t and "ia" in t and any(x in t for x in ("calcule", "calculer", "estime", "évalue", "evalue")):
        return True
    return False


def _sanitize_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    """Garde uniquement user/assistant et limite la profondeur pour accélérer Ollama."""
    out: list[dict[str, str]] = []
    for m in history:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = str(m.get("content", ""))
        out.append({"role": role, "content": content})
    if len(out) > _MAX_CHAT_MESSAGES:
        return out[-_MAX_CHAT_MESSAGES :]
    return out


def build_ollama_chat_messages(history: list[dict[str, str]]) -> list[dict[str, str]]:
    """Préfixe le prompt système du chat local (sans le stocker dans session_state)."""
    core = _sanitize_history(history)
    return [{"role": "system", "content": LOCAL_CHAT_SYSTEM_PROMPT}, *core]


def run_ollama_chat_assistant(history: list[dict[str, str]], settings: "Settings") -> str:
    """Appelle Ollama /api/chat avec options dédiées assistant (rapide, sortie bornée)."""
    from .llm_provider import ollama_chat_completion

    messages = build_ollama_chat_messages(history)
    return ollama_chat_completion(
        settings.ollama_base_url,
        settings.ollama_model,
        messages,
        temperature=settings.ollama_chat_temperature,
        num_predict=settings.ollama_chat_num_predict,
        num_ctx=settings.ollama_chat_num_ctx,
        timeout=90,
    )
