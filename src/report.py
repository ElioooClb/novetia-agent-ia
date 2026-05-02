"""Génération de rapports Markdown pour le diagnostic."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "outputs"


def _slug(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    s = re.sub(r"[-\s]+", "-", s, flags=re.UNICODE)
    return s[:60] or "rapport"


def build_report_markdown(company_data: dict[str, Any], recommendations: list[dict[str, Any]]) -> str:
    """Construit le texte Markdown du rapport (sans écrire de fichier)."""
    lines: list[str] = []
    entreprise = str(company_data.get("entreprise", company_data.get("company_name", "")))
    lines.append(f"# Rapport diagnostic IA — {entreprise or 'Entreprise'}\n")
    lines.append(f"*Généré le {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*\n")

    lines.append("## Contexte entreprise\n")
    mapping = [
        ("Entreprise", "entreprise", "company_name"),
        ("Secteur", "secteur", "sector"),
        ("Taille", "taille", "size"),
        ("Problèmes rencontrés", "problemes", "problems"),
        ("Tâches répétitives", "taches_repetitives", "repetitive_tasks"),
        ("Outils actuels", "outils", "tools"),
        ("Objectif prioritaire", "objectif", "priority_goal"),
        ("Maturité numérique", "maturite", "digital_maturity"),
    ]
    for row in mapping:
        label = row[0]
        val = ""
        for k in row[1:]:
            v = company_data.get(k)
            if v is not None and str(v).strip():
                val = str(v).strip()
                break
        lines.append(f"- **{label}** : {val or '—'}\n")

    lines.append("\n## Synthèse du diagnostic\n")
    lines.append(
        "Ce rapport propose trois cas d'usage IA prioritaires, issus d'une base métiers "
        "et d'un scoring sur vos réponses, puis enrichis par un modèle de langage lorsque l'API est disponible. "
        "Les ordres de grandeur (temps, ROI) sont indicatifs et doivent être affinés en atelier.\n"
    )

    lines.append("\n## Cas d'usage IA prioritaires\n")
    for i, rec in enumerate(recommendations[:3], start=1):
        lines.append(f"### {i}. {rec.get('title', 'Cas')}\n")
        lines.append(f"{rec.get('summary', '')}\n")
        lines.append("\n| Critère | Détail |\n")
        lines.append("|---------|--------|\n")
        lines.append(f"| Gain de temps (estim.) | {rec.get('time_saved', rec.get('impact', '—'))} |\n")
        lines.append(f"| Difficulté | {rec.get('difficulty', '—')} |\n")
        lines.append(f"| Impact métier | {rec.get('impact', '—')} |\n")
        lines.append(f"| ROI approximatif | {rec.get('roi', '—')} |\n")
        if rec.get("typical_tasks"):
            lines.append(f"| Tâches typiques | {rec.get('typical_tasks')} |\n")
        lines.append(f"\n**Prochaines étapes** : {rec.get('next_steps', '—')}\n")

    lines.append("\n## Limites du diagnostic\n")
    lines.append(
        "- Données limitées au formulaire : pas d'audit technique ni d'accès aux systèmes.\n"
        "- ROI et gains de temps sont des **ordres de grandeur** à valider sur le terrain.\n"
        "- L'enrichissement LLM peut introduire des formulations génériques ; croiser avec votre contexte réel.\n"
    )

    lines.append("\n## Prochaines étapes recommandées\n")
    lines.append(
        "1. Prioriser un pilote unique sur 4 à 8 semaines avec un périmètre réduit.\n"
        "2. Identifier les données et intégrations nécessaires (RGPD, hébergement).\n"
        "3. Mesurer une baseline (temps passé, taux d'erreur, satisfaction) avant déploiement.\n"
        "4. Envisager un **modèle local (Ollama)** pour les données sensibles, en réutilisant la même abstraction `LLMProvider`.\n"
    )

    return "".join(lines)


def generate_markdown_report(company_data: dict[str, Any], recommendations: list[dict[str, Any]]) -> Path:
    """
    Construit un rapport Markdown et l'enregistre dans outputs/.
    Retourne le chemin du fichier créé.
    """
    _OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    name = company_data.get("entreprise") or company_data.get("company_name") or "entreprise"
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = _OUTPUTS_DIR / f"diagnostic_{_slug(str(name))}_{ts}.md"
    text = build_report_markdown(company_data, recommendations)
    path.write_text(text, encoding="utf-8")
    return path
