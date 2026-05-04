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


def _normalize_difficulty(raw: str) -> str:
    s = (raw or "").strip().lower()
    if any(x in s for x in ("élev", "eleve", "high", "difficile")):
        return "élevé"
    if any(x in s for x in ("moyen", "medium", "modéré", "modere")):
        return "moyen"
    if any(x in s for x in ("faible", "low", "simple", "facile")):
        return "faible"
    return raw.strip() or "—"


def _normalize_roi_horizon(raw: str) -> str:
    s = (raw or "").strip().lower()
    if any(x in s for x in ("rapide", "court", "quick", "1-2", "1 à 2", "immédiat")):
        return "rapide"
    if any(x in s for x in ("long", "12 mois", "an", "18", "24")):
        return "long"
    if any(x in s for x in ("moyen", "medium", "3-6", "3 à 6", "6 mois", "trimestre")):
        return "moyen"
    return raw.strip() or "—"


def _coerce_priority(val: Any, fallback: int) -> int:
    try:
        p = int(val)
        if 1 <= p <= 3:
            return p
    except (TypeError, ValueError):
        pass
    return fallback


def _recommendation_from_use_case(
    uc: dict[str, Any], score: float | None = None, *, priority: int = 1
) -> dict[str, Any]:
    """Construit une recommandation structurée sans appel LLM (même schéma que le livrable LLM)."""
    title = str(uc.get("title", "Cas d'usage"))
    desc = str(uc.get("description", ""))
    typical = _flatten_typical_tasks(uc.get("typical_tasks"))
    steps = (
        f"Vérifier les prérequis : {uc.get('required_data', 'N/A')}. "
        f"Exemples d'outils : {uc.get('example_tool', 'N/A')}."
    )
    return {
        "priority": priority,
        "title": f"⭐ Priorité {priority} — {title}",
        "raw_title": title,
        "business_objective": (desc[:600] + "…") if len(desc) > 600 else desc or "À préciser avec le dirigeant.",
        "concrete_example": typical or "À ancrer sur un processus réel de l'entreprise.",
        "summary": desc,
        "impact": str(uc.get("potential_gain", "À estimer")),
        "difficulty": _normalize_difficulty(str(uc.get("difficulty", "non précisée"))),
        "time_saved": str(uc.get("potential_gain", "À estimer")),
        "roi": _normalize_roi_horizon(str(uc.get("roi_speed", "À estimer"))),
        "action_plan": steps,
        "next_steps": steps,
        "typical_tasks": typical or "—",
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


def _extract_json_object(text: str) -> str:
    """Isole le premier objet JSON `{ ... }` (réponse structurée diagnostic)."""
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", t, re.IGNORECASE)
    if fence:
        t = fence.group(1).strip()
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        return t[start : end + 1]
    return t


def _first_nonempty(d: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = d.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _parse_llm_recommendations(raw: str) -> list[dict[str, Any]] | None:
    """Ancien format : tableau JSON de 3 recommandations (rétrocompatibilité)."""
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


def _row_from_legacy_item(item: dict[str, Any], priority: int) -> dict[str, Any]:
    """Convertit une entrée ancien format JSON vers le modèle enrichi (champs optionnels)."""
    title = str(item.get("title", "")).strip() or "Recommandation"
    summary = str(item.get("summary", item.get("rationale", ""))).strip()
    impact = str(item.get("impact", "")).strip()
    difficulty = _normalize_difficulty(str(item.get("difficulty", "")))
    roi = _normalize_roi_horizon(str(item.get("roi", item.get("roi_approximatif", ""))))
    next_steps = str(item.get("next_steps", item.get("prochaines_etapes", ""))).strip()
    typical = str(item.get("typical_tasks", "")).strip()
    return {
        "priority": priority,
        "title": f"⭐ Priorité {priority} — {title}",
        "raw_title": title,
        "business_objective": impact or summary[:280] if summary else "—",
        "concrete_example": typical or summary or "—",
        "summary": summary,
        "impact": impact or summary,
        "difficulty": difficulty,
        "time_saved": str(item.get("time_saved", item.get("gain_temps", ""))).strip() or "—",
        "roi": roi,
        "action_plan": next_steps,
        "next_steps": next_steps,
        "typical_tasks": typical or "—",
        "score": item.get("score"),
        "from_llm": True,
    }


def _row_from_structured_case(item: dict[str, Any], fallback_priority: int) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    title = _first_nonempty(item, "title", "titre")
    if not title:
        title = "Cas d'usage IA"
    pr = _coerce_priority(item.get("priority") or item.get("priorite"), fallback_priority)
    obj = _first_nonempty(item, "business_objective", "objectif_metier", "objectif_métier")
    ex = _first_nonempty(item, "concrete_example", "exemple_concret", "exemple")
    ts = _first_nonempty(item, "time_saved", "gain_temps", "gain_temps_heures_semaine")
    diff = _normalize_difficulty(_first_nonempty(item, "difficulty", "difficulte", "difficulté"))
    roi = _normalize_roi_horizon(_first_nonempty(item, "roi", "roi_delai", "horizon_roi"))
    plan = _first_nonempty(item, "action_plan", "plan_action", "plan_action_semaines", "next_steps", "prochaines_etapes")
    summary = _first_nonempty(item, "summary", "synthese_case")
    if not summary and (obj or ex):
        summary = (obj + "\n\n" + ex).strip()
    impact = _first_nonempty(item, "impact", "valeur_metier") or obj or summary
    typical = _first_nonempty(item, "typical_tasks", "taches_typiques") or ex
    return {
        "priority": pr,
        "title": f"⭐ Priorité {pr} — {title}",
        "raw_title": title,
        "business_objective": obj or "—",
        "concrete_example": ex or "—",
        "summary": summary or f"{obj}\n\n{ex}".strip() or "—",
        "impact": impact or "—",
        "difficulty": diff,
        "time_saved": ts or "—",
        "roi": roi,
        "action_plan": plan or "—",
        "next_steps": plan or "—",
        "typical_tasks": typical or "—",
        "score": item.get("score"),
        "from_llm": True,
    }


def _parse_llm_diagnostic_object(raw: str) -> dict[str, Any] | None:
    """
    Parse le format diagnostic « cabinet de conseil » : un objet JSON unique.
    Retourne executive_summary, final_recommendation, recommendations (liste normalisée).
    """
    try:
        payload = _extract_json_object(raw)
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    exec_s = _first_nonempty(data, "executive_summary", "synthese_executive", "resume_executif")
    exec_s = exec_s.replace("\r\n", "\n").strip()

    fr_raw = data.get("final_recommendation") or data.get("recommandation_finale") or {}
    if not isinstance(fr_raw, dict):
        fr_raw = {}
    start = _first_nonempty(fr_raw, "par_quoi_commencer", "start_with", "commencer_par", "par_quoi_commencer_par")
    why = _first_nonempty(fr_raw, "pourquoi", "why", "justification")
    final_rec: dict[str, str] | None = None
    if start or why:
        final_rec = {
            "par_quoi_commencer": start or "—",
            "pourquoi": why or "—",
        }

    cases_raw = data.get("use_cases") or data.get("cas_usage") or data.get("cas_d_usage") or []
    if not isinstance(cases_raw, list):
        cases_raw = []

    recs: list[dict[str, Any]] = []
    for i, item in enumerate(cases_raw[:3], start=1):
        row = _row_from_structured_case(item if isinstance(item, dict) else {}, fallback_priority=i)
        if row:
            recs.append(row)

    if not recs:
        return None

    return {
        "executive_summary": exec_s or None,
        "final_recommendation": final_rec,
        "recommendations": recs,
    }


def _parse_llm_response_bundle(raw: str) -> dict[str, Any] | None:
    """Priorité au format objet structuré ; sinon ancien tableau JSON."""
    bundle = _parse_llm_diagnostic_object(raw)
    if bundle and bundle.get("recommendations"):
        return bundle
    legacy = _parse_llm_recommendations(raw)
    if not legacy:
        return None
    recs = [_row_from_legacy_item(legacy[i], i + 1) for i in range(min(3, len(legacy)))]
    return {
        "executive_summary": None,
        "final_recommendation": None,
        "recommendations": recs,
    }


def _build_llm_prompt(company: dict[str, Any], top_cases: list[dict[str, Any]]) -> str:
    cases_json = json.dumps(top_cases, ensure_ascii=False, indent=2)
    company_json = json.dumps(company, ensure_ascii=False, indent=2)
    secteur = str(company.get("secteur") or company.get("sector") or "").strip()
    taille = str(company.get("taille") or company.get("size") or "").strip()
    problemes = str(company.get("problemes") or company.get("problems") or "").strip()
    rep = str(company.get("taches_repetitives") or company.get("repetitive_tasks") or "").strip()
    outils = str(company.get("outils") or company.get("tools") or "").strip()
    objectif = str(company.get("objectif") or company.get("priority_goal") or "").strip()
    maturite = str(company.get("maturite") or company.get("digital_maturity") or "").strip()

    return f"""Tu es un consultant senior spécialisé transformation numérique et IA pour TPE/PME en France.
Tu rédiges un livrable de niveau « cabinet de conseil » : ton précis, concret, sans phrases creuses ni généralités vagues.

## Données dirigeant (JSON — t’en inspirer obligatoirement pour personnaliser)
{company_json}

Champs à exploiter explicitement dans ta rédaction :
- Secteur : {secteur or "(non précisé)"} — illustre avec des exemples métiers crédibles (ex. BTP : devis, planning chantier, PV ; commerce : stocks, SAV ; services : relances, CRM, mails clients…).
- Taille : {taille or "—"}
- Problèmes : {problemes or "—"}
- Tâches répétitives : {rep or "—"}
- Outils actuels : {outils or "—"}
- Objectif prioritaire : {objectif or "—"}
- Maturité numérique : {maturite or "—"}

## Cas d’usage pré-classés par le moteur interne (JSON — tu dois partir de ces 3 cas, même ordre de priorité 1 → 2 → 3)
{cases_json}

## Consignes de style (impératif)
- Zéro formule du type « il est important de », « dans un monde en mutation », « l’IA peut aider les entreprises ».
- Chaque affirmation utile doit être reliée au contexte ci-dessus (secteur, outils, irritants).
- Chiffrages : ordres de grandeur plausibles pour une PME (heures/semaine), pas de promesses irréalistes.

## Tâche
Produis **un seul objet JSON** valide (UTF-8, guillemets doubles), sans texte avant ni après, sans commentaires, sans Markdown autour du JSON.

Structure exacte attendue :
{{
  "executive_summary": "string — au plus 5 lignes courtes, séparées par des sauts de ligne ; synthèse exécutive percutante",
  "use_cases": [
    {{
      "priority": 1,
      "title": "string — titre court du cas (aligné sur le cas #1 fourni)",
      "business_objective": "string — objectif métier mesurable ou clair",
      "concrete_example": "string — scène d’usage dans L’ENTREPRISE (personas, flux, outils)",
      "time_saved": "string — gain estimé ex. « 3–5 h/semaine » pour l’équipe concernée",
      "difficulty": "faible | moyen | élevé",
      "roi": "rapide | moyen | long",
      "action_plan": "string — plan sur 4 à 8 semaines : étapes numérotées S1… avec livrables concrets (pas de blabla)"
    }},
    {{
      "priority": 2,
      "title": "…",
      "business_objective": "…",
      "concrete_example": "…",
      "time_saved": "…",
      "difficulty": "moyen",
      "roi": "moyen",
      "action_plan": "…"
    }},
    {{
      "priority": 3,
      "title": "…",
      "business_objective": "…",
      "concrete_example": "…",
      "time_saved": "…",
      "difficulty": "élevé",
      "roi": "long",
      "action_plan": "…"
    }}
  ],
  "final_recommendation": {{
    "par_quoi_commencer": "string — une seule entrée concrète (pilote, processus ou outil)",
    "pourquoi": "string — 2 à 4 phrases argumentées (risque, effort, valeur rapide)"
  }}
}}

Règles : exactement 3 entrées dans use_cases ; priority 1, 2, 3 ; difficulté et roi parmi les valeurs imposées ci-dessus uniquement.
Réponse = uniquement l’objet JSON."""


def run_diagnostic(company_data: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    """
    Exécute le diagnostic complet.

    Retourne un dict avec :
    - recommendations: liste de 3 recommandations structurées
    - used_llm: bool
    - llm_error: message optionnel si repli
    - ranked_scores: scores des 3 premiers (debug / transparence)
    - executive_summary: synthèse LLM (ou None si repli)
    - final_recommendation: dict par_quoi_commencer / pourquoi (ou None)
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
            "executive_summary": None,
            "final_recommendation": None,
        }

    title_to_score = {str(uc.get("title")): float(s) for s, uc in ranked}
    base_recos: list[dict[str, Any]] = []
    for pri, uc in enumerate(top3, start=1):
        sc = title_to_score.get(str(uc.get("title")))
        base_recos.append(_recommendation_from_use_case(uc, score=sc, priority=pri))

    def _attach_scores(recs: list[dict[str, Any]]) -> None:
        for i in range(min(3, len(recs))):
            if i < len(base_recos) and base_recos[i].get("score") is not None:
                recs[i]["score"] = base_recos[i]["score"]

    llm_error: str | None = None
    try:
        provider = get_llm_provider(cfg)
        prompt = _build_llm_prompt(company_data, top3)
        raw = provider.generate(prompt)
        bundle = _parse_llm_response_bundle(raw)
        if bundle and bundle.get("recommendations"):
            parsed = bundle["recommendations"]
            exec_s = bundle.get("executive_summary")
            fin = bundle.get("final_recommendation")
            n = len(parsed)
            if n >= 3:
                _attach_scores(parsed)
                return {
                    "recommendations": parsed[:3],
                    "used_llm": True,
                    "llm_error": None,
                    "ranked_scores": scores_preview,
                    "executive_summary": exec_s,
                    "final_recommendation": fin,
                }
            merged = parsed + base_recos[n:]
            merged = merged[:3]
            _attach_scores(merged)
            return {
                "recommendations": merged,
                "used_llm": True,
                "llm_error": "Réponse LLM partielle ; complétion par scoring.",
                "ranked_scores": scores_preview,
                "executive_summary": exec_s,
                "final_recommendation": fin,
            }
        llm_error = "Réponse LLM non interprétable (JSON). Repli sur le scoring."
    except Exception as exc:  # noqa: BLE001 — repli explicite pour démo
        llm_error = f"LLM indisponible ou erreur : {exc}"

    return {
        "recommendations": base_recos,
        "used_llm": False,
        "llm_error": llm_error,
        "ranked_scores": scores_preview,
        "executive_summary": None,
        "final_recommendation": None,
    }
