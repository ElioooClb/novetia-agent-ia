"""Outils externes : lecture de la base de cas d'usage IA."""

import json
from pathlib import Path
from typing import Any

# Chemin vers data/use_cases_ai.json (racine projet)
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_USE_CASES_PATH = _DATA_DIR / "use_cases_ai.json"


def load_ai_use_cases() -> list[dict[str, Any]]:
    """
    Charge tous les cas d'usage depuis le fichier JSON.
    Retourne une liste vide si le fichier est absent ou invalide.
    """
    if not _USE_CASES_PATH.is_file():
        return []
    try:
        with open(_USE_CASES_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        return []


def filter_use_cases_by_sector(sector: str, use_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Filtre les cas dont le champ 'sectors' contient le secteur (insensible à la casse)
    ou inclut la valeur générique 'tous'.
    Si aucun match, retourne la liste complète pour ne pas bloquer le diagnostic.
    """
    if not sector or not use_cases:
        return use_cases

    s = sector.strip().lower()
    out: list[dict[str, Any]] = []
    for uc in use_cases:
        sectors = uc.get("sectors") or []
        if not isinstance(sectors, list):
            continue
        lowered = [str(x).lower() for x in sectors]
        if "tous" in lowered or s in lowered:
            out.append(uc)

    return out if out else use_cases
