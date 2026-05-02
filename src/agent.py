"""
Orchestration du diagnostic : données dirigeant, scoring, enrichissement LLM, repli déterministe.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .config import Settings, get_settings
from .llm_provider import get_llm_provider
from .scoring import rank_use_cases, top_n_use_cases
from .tools import filter_use_cases_by_sector, load_ai_use_cases


def _flatten_typical_tasks(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(x) for x in value)
    return str(value or "")


def _recommendation_from_use_case(uc: dict[str, Any], score: float | None = None) -> dict[str, Any]:
    """Construit une recommandation structurée sans appel LLM."""
    return {
        "title": str(uc.get("title", "Cas d'usage")),
        "summary": str(uc.get("description", "")),
        "impact": str(uc.get("potential_gain", "À estimer")),
        "difficulty": str(uc.get("difficulty", "non précisée")),
        "time_saved": str(uc.get("potential_gain", "À estimer")),
        "roi": str(uc.get("roi_speed", "À estimer")),
        "next_steps": (
            f"Vérifier les prérequis : {uc.get('required_data', 'N/A')}. "
            f"Exemples d'outils : {uc.get('example_tool', 'N/A')}."
        ),
        "typical_tasks": _flatten_typical_tasks(uc.get("typical_tasks")),
        "score": score,
        "from_llm": False,
    }


def _extract_json_payload(text: str) -> str:
    """Tente d'isoler un tableau JSON depuis la réponse modèle."""
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", t, re.IGNORECASE)
    if fence:
        t = fence.group(1).strip()
    start = t.find("[")
    end = t.rfind("]")
    if start != -1 and end != -1 and end > start:
        return t[start : end + 1]
    return t


def _parse_llm_recommendations(raw: str) -> list[dict[str, Any]] | None:
    try:
        payload = _extract_json_payload(raw)
        data = json.loads(payload)
        if not isinstance(data, list):
            return None
        out: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            out.append(
                {
                    "title": str(item.get("title", "")).strip() or "Recommandation",
                    "summary": str(item.get("summary", item.get("rationale", ""))).strip(),
                    "impact": str(item.get("impact", "")).strip(),
                    "difficulty": str(item.get("difficulty", "")).strip(),
                    "time_saved": str(item.get("time_saved", item.get("gain_temps", ""))).strip(),
                    "roi": str(item.get("roi", item.get("roi_approximatif", ""))).strip(),
                    "next_steps": str(item.get("next_steps", item.get("prochaines_etapes", ""))).strip(),
                    "typical_tasks": str(item.get("typical_tasks", "")).strip(),
                    "score": item.get("score"),
                    "from_llm": True,
                }
            )
        return out if out else None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _build_llm_prompt(company: dict[str, Any], top_cases: list[dict[str, Any]]) -> str:
    cases_json = json.dumps(top_cases, ensure_ascii=False, indent=2)
    company_json = json.dumps(company, ensure_ascii=False, indent=2)
    return f"""Tu es un consultant IA spécialisé TPE/PME (France).

Contexte dirigeant (JSON) :
{company_json}

Les 3 cas d'usage pré-sélectionnés par un moteur de scoring interne (JSON) :
{cases_json}

Tâche : enrichis ces 3 cas pour le dirigeant. Réponds UNIQUEMENT avec un tableau JSON valide
de 3 objets, même ordre logique que les cas fournis, sans texte avant ou après.

Chaque objet doit avoir exactement ces clés (chaînes) :
- "title" : titre court du cas
- "summary" : 2 à 4 phrases actionnables (contexte entreprise + valeur)
- "impact" : effet métier attendu (qualitatif + ordre de grandeur si possible)
- "difficulty" : faible | moyenne | élevée (cohérent avec le cas)
- "time_saved" : estimation gain de temps (ex. "2-4 h/semaine")
- "roi" : vitesse de retour approximatif (ex. "1-2 mois", "3-6 mois")
- "next_steps" : 3 prochaines étapes concrètes pour la PME
- "typical_tasks" : tâches ciblées (une ligne)

Réponse = uniquement le JSON array, encodage UTF-8, guillemets doubles.
"""


def run_diagnostic(company_data: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    """
    Exécute le diagnostic complet.

    Retourne un dict avec :
    - recommendations: liste de 3 recommandations structurées
    - used_llm: bool
    - llm_error: message optionnel si repli
    - ranked_scores: scores des 3 premiers (debug / transparence)
    """
    cfg = settings or get_settings()
    use_cases = load_ai_use_cases()
    sector = str(company_data.get("secteur", "") or company_data.get("sector", ""))
    filtered = filter_use_cases_by_sector(sector, use_cases)

    problems = str(company_data.get("problemes", "") or company_data.get("problems", ""))
    rep = str(company_data.get("taches_repetitives", "") or company_data.get("repetitive_tasks", ""))
    goal = str(company_data.get("objectif", "") or company_data.get("priority_goal", ""))
    tools = str(company_data.get("outils", "") or company_data.get("tools", ""))

    ranked = rank_use_cases(filtered, sector, problems, rep, goal, tools)
    top3 = top_n_use_cases(filtered, sector, problems, rep, goal, tools, n=3)
    scores_preview = [(float(s), uc.get("title")) for s, uc in ranked[:3]]

    if not top3:
        return {
            "recommendations": [],
            "used_llm": False,
            "llm_error": "Aucun cas d'usage disponible (fichier data manquant ou vide).",
            "ranked_scores": scores_preview,
        }

    title_to_score = {str(uc.get("title")): float(s) for s, uc in ranked}
    base_recos = []
    for uc in top3:
        sc = title_to_score.get(str(uc.get("title")))
        base_recos.append(_recommendation_from_use_case(uc, score=sc))

    llm_error: str | None = None
    try:
        provider = get_llm_provider(cfg)
        prompt = _build_llm_prompt(company_data, top3)
        raw = provider.generate(prompt)
        parsed = _parse_llm_recommendations(raw)
        if parsed and len(parsed) >= 3:
            # Fusion légère : conserve score du scoring sur les 3 premiers titres proches
            for i in range(3):
                if i < len(base_recos) and base_recos[i].get("score") is not None:
                    parsed[i]["score"] = base_recos[i]["score"]
            return {
                "recommendations": parsed[:3],
                "used_llm": True,
                "llm_error": None,
                "ranked_scores": scores_preview,
            }
        if parsed and len(parsed) > 0:
            merged = parsed + base_recos[len(parsed) :]
            merged = merged[:3]
            return {
                "recommendations": merged,
                "used_llm": True,
                "llm_error": "Réponse LLM partielle ; complétion par scoring.",
                "ranked_scores": scores_preview,
            }
        llm_error = "Réponse LLM non interprétable (JSON). Repli sur le scoring."
    except Exception as exc:  # noqa: BLE001 — repli explicite pour démo
        llm_error = f"LLM indisponible ou erreur : {exc}"

    return {
        "recommendations": base_recos,
        "used_llm": False,
        "llm_error": llm_error,
        "ranked_scores": scores_preview,
    }
