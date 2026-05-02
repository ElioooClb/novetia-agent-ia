"""Génération de rapports Markdown et PDF pour le diagnostic."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "outputs"


def _slug(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    s = re.sub(r"[-\s]+", "-", s, flags=re.UNICODE)
    return s[:60] or "rapport"


def _strip_inline_markdown(text: str) -> str:
    """Retire le gras, italique et code inline pour le rendu PDF texte."""
    s = text
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"__(.+?)__", r"\1", s)
    s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    return s.strip()


def _normalize_pdf_text(text: str) -> str:
    """Normalise Unicode ; remplace les glyphes problématiques par des équivalents ASCII si besoin."""
    s = unicodedata.normalize("NFC", text)
    # Guillemets / apostrophes typographiques courants
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    s = s.replace("\u00a0", " ")
    return s


def _text_for_core_font(text: str) -> str:
    """
    Texte compatible avec les polices PDF standard (Helvetica).
    Accents français : suppression des signes diacritiques (café -> cafe).
    Caractères non représentables : remplacés par '?' de façon déterministe.
    """
    s = _normalize_pdf_text(text)
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s.encode("latin-1", errors="replace").decode("latin-1")


def _split_md_table_cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_table_separator_line(line: str) -> bool:
    cells = _split_md_table_cells(line)
    if len(cells) < 2:
        return False
    for c in cells:
        if not c:
            return False
        compact = c.replace(" ", "")
        if not re.fullmatch(r":?-{3,}:?", compact):
            return False
    return True


def _parse_table_row(line: str) -> str | None:
    """Transforme une ligne de tableau Markdown en texte lisible, ou None si séparateur."""
    s = line.strip()
    if not s.startswith("|"):
        return None
    if _is_table_separator_line(s):
        return None
    cells = _split_md_table_cells(s)
    if not cells:
        return None
    return " - ".join(_strip_inline_markdown(c) for c in cells if c)


def _emit_paragraph(pdf: Any, text: str, *, size: float = 10, style: str = "", indent_mm: float = 0) -> None:
    text = _text_for_core_font(_strip_inline_markdown(text))
    if not text.strip():
        pdf.ln(2)
        return
    usable_w = pdf.w - pdf.l_margin - pdf.r_margin - indent_mm
    pdf.set_x(pdf.l_margin + indent_mm)
    pdf.set_font("helvetica", style, size)
    line_h = max(4.5, size * 0.48)
    pdf.multi_cell(usable_w, line_h, text)
    pdf.ln(1)


def _emit_heading(pdf: Any, text: str, level: int) -> None:
    text = _text_for_core_font(_strip_inline_markdown(text))
    if level == 1:
        pdf.ln(2)
        pdf.set_font("helvetica", "B", 16)
        pdf.multi_cell(0, 8, text)
        pdf.ln(3)
    elif level == 2:
        pdf.ln(3)
        pdf.set_font("helvetica", "B", 13)
        pdf.multi_cell(0, 6.5, text)
        pdf.ln(2)
    else:
        pdf.ln(2)
        pdf.set_font("helvetica", "B", 11)
        pdf.multi_cell(0, 5.8, text)
        pdf.ln(1.2)


def _emit_bullet(pdf: Any, text: str) -> None:
    full = "- " + _text_for_core_font(_strip_inline_markdown(text))
    usable_w = pdf.w - pdf.l_margin - pdf.r_margin - 6
    pdf.set_x(pdf.l_margin + 6)
    pdf.set_font("helvetica", "", 10)
    pdf.multi_cell(usable_w, 5.2, full)
    pdf.ln(0.5)


def _markdown_to_pdf(pdf: Any, markdown_content: str) -> None:
    """Interprète un sous-ensemble Markdown (# ## ###, paragraphes, listes '- ', tableaux simples)."""
    lines = markdown_content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    para_buf: list[str] = []

    def flush_paragraph() -> None:
        nonlocal para_buf
        if not para_buf:
            return
        body = " ".join(p.strip() for p in para_buf if p.strip())
        para_buf = []
        if body:
            _emit_paragraph(pdf, body)

    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()

        if not stripped:
            flush_paragraph()
            pdf.ln(1.5)
            i += 1
            continue

        if stripped.startswith("|"):
            flush_paragraph()
            row_txt = _parse_table_row(stripped)
            if row_txt:
                _emit_paragraph(pdf, row_txt, size=9.5)
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush_paragraph()
            level = len(m.group(1))
            title = m.group(2).strip()
            if level == 1:
                _emit_heading(pdf, title, 1)
            elif level == 2:
                _emit_heading(pdf, title, 2)
            else:
                _emit_heading(pdf, title, 3)
            i += 1
            continue

        if re.match(r"^[-*]\s+", stripped):
            flush_paragraph()
            item = re.sub(r"^[-*]\s+", "", stripped)
            _emit_bullet(pdf, item)
            i += 1
            continue

        if re.match(r"^\d+\.\s+", stripped):
            flush_paragraph()
            item = re.sub(r"^\d+\.\s+", "", stripped)
            _emit_paragraph(pdf, item, indent_mm=5)
            i += 1
            continue

        para_buf.append(stripped)
        i += 1

    flush_paragraph()


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


def generate_pdf_report(markdown_content: str, output_path: str) -> str:
    """
    Génère un fichier PDF simple à partir du contenu Markdown (fpdf2, police Helvetica).

    Éléments pris en charge : titres # / ## / ###, paragraphes, listes à puces "- ",
    listes numérotées, lignes de tableau "| ... |" (séparateurs ignorés).

    Les accents sont translittérés en ASCII (suppression des diacritiques) pour une
    compatibilité maximale avec les polices standard ; les glyphes non encodables en
    Latin-1 sont remplacés par "?".

    Args:
        markdown_content: texte Markdown complet du rapport.
        output_path: chemin du fichier PDF à créer (répertoire parent créé si besoin).

    Returns:
        Chemin absolu du PDF généré (chaîne).

    Raises:
        ImportError: package fpdf2 manquant.
        RuntimeError: police ou écriture PDF impossible.
        OSError: erreur disque.
    """
    try:
        from fpdf import FPDF
    except ImportError as exc:
        raise RuntimeError(
            "Le package fpdf2 est requis pour l'export PDF. Installez-le : pip install fpdf2"
        ) from exc

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(18, 18, 18)
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()

    try:
        _markdown_to_pdf(pdf, markdown_content)
        pdf.output(str(out.resolve()))
    except Exception as exc:
        raise RuntimeError(f"Échec de la génération PDF : {exc}") from exc

    resolved = out.resolve()
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise RuntimeError("Le fichier PDF n'a pas été créé correctement.")

    return str(resolved)
