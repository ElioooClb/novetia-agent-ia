"""
Scoring déterministe des cas d'usage : fonctionne sans LLM.
"""

import re
from typing import Any


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    raw = _normalize_text(text)
    parts = re.split(r"[^\wàâäéèêëïîôùûüç]+", raw, flags=re.IGNORECASE)
    # Filtre tokens trop courts (sauf quelques mots-clés métiers)
    keep_short = {"sav", "crm", "kpi", "pdf", "ia", "bi", "rh"}
    out: set[str] = set()
    for p in parts:
        if len(p) >= 3 or p in keep_short:
            out.add(p)
    return out


def _flatten_typical_tasks(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(x) for x in value)
    return str(value or "")


def _company_bag(
    sector: str,
    problems: str,
    repetitive_tasks: str,
    priority_goal: str,
    tools: str = "",
) -> set[str]:
    blob = " ".join([sector, problems, repetitive_tasks, priority_goal, tools])
    return _tokens(blob)


def _use_case_bag(uc: dict[str, Any]) -> set[str]:
    parts = [
        str(uc.get("title", "")),
        str(uc.get("description", "")),
        _flatten_typical_tasks(uc.get("typical_tasks")),
        str(uc.get("example_tool", "")),
        str(uc.get("required_data", "")),
    ]
    return _tokens(" ".join(parts))


def score_use_case(
    uc: dict[str, Any],
    sector: str,
    problems: str,
    repetitive_tasks: str,
    priority_goal: str,
    tools: str = "",
) -> float:
    """
    Score simple : intersection de tokens + bonus secteur.
    """
    company = _company_bag(sector, problems, repetitive_tasks, priority_goal, tools)
    uc_tokens = _use_case_bag(uc)
    if not company or not uc_tokens:
        overlap = 0.0
    else:
        inter = company & uc_tokens
        overlap = len(inter) * 2.0 + min(len(inter), 8) * 0.5

    bonus = 0.0
    sec = _normalize_text(sector)
    sectors = uc.get("sectors") or []
    if isinstance(sectors, list):
        lowered = {str(s).lower() for s in sectors}
        if "tous" in lowered:
            bonus += 3.0
        elif sec and sec in lowered:
            bonus += 5.0

    # Léger bonus si objectifs métiers typiques dans le titre
    title_l = str(uc.get("title", "")).lower()
    goal_l = _normalize_text(priority_goal)
    if goal_l and goal_l in title_l:
        bonus += 2.0

    return overlap + bonus


def rank_use_cases(
    use_cases: list[dict[str, Any]],
    sector: str,
    problems: str,
    repetitive_tasks: str,
    priority_goal: str,
    tools: str = "",
) -> list[tuple[float, dict[str, Any]]]:
    """Retourne la liste (score, cas) triée par score décroissant."""
    scored: list[tuple[float, dict[str, Any]]] = []
    for uc in use_cases:
        s = score_use_case(uc, sector, problems, repetitive_tasks, priority_goal, tools)
        scored.append((s, uc))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def top_n_use_cases(
    use_cases: list[dict[str, Any]],
    sector: str,
    problems: str,
    repetitive_tasks: str,
    priority_goal: str,
    tools: str = "",
    n: int = 3,
) -> list[dict[str, Any]]:
    """Les n meilleurs cas d'usage selon le scoring déterministe."""
    ranked = rank_use_cases(use_cases, sector, problems, repetitive_tasks, priority_goal, tools)
    return [uc for _, uc in ranked[:n]]
