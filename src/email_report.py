"""
Envoi du rapport PDF par email (SMTP).

TODO configuration production :
  - Définir dans l'environnement : SMTP_HOST, SMTP_PORT (défaut 587),
    SMTP_USER, SMTP_PASSWORD, SMTP_FROM (adresse expéditeur autorisée).
  - Adapter TLS / port selon le fournisseur (ex. 465 SSL vs 587 STARTTLS).
"""

from __future__ import annotations

import os
import re
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def is_valid_email(address: str) -> bool:
    """Vérifie que l'adresse n'est pas vide et correspond à un format email plausible."""
    s = (address or "").strip()
    return bool(_EMAIL_RE.fullmatch(s))


def send_report_by_email(
    to_email: str,
    pdf_path: str | Path,
    *,
    subject: str | None = None,
) -> None:
    """
    Envoie le PDF en pièce jointe via SMTP.

    Lève RuntimeError si SMTP n'est pas configuré (variables d'environnement).
    Lève les exceptions réseau / SMTP en cas d'échec d'envoi.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF introuvable : {pdf_path}")

    host = os.environ.get("SMTP_HOST", "").strip()
    port_raw = os.environ.get("SMTP_PORT", "587").strip()
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    from_addr = os.environ.get("SMTP_FROM", "").strip()

    if not host or not from_addr:
        raise RuntimeError(
            "SMTP non configuré : définissez au minimum SMTP_HOST et SMTP_FROM "
            "(optionnellement SMTP_PORT, SMTP_USER, SMTP_PASSWORD). "
            "Voir TODO dans src/email_report.py."
        )

    port = int(port_raw)
    subject = subject or "Rapport diagnostic IA"

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email
    msg.attach(
        MIMEText(
            "Veuillez trouver ci-joint votre rapport de diagnostic IA.",
            "plain",
            "utf-8",
        )
    )

    with pdf_path.open("rb") as f:
        part = MIMEBase("application", "pdf")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        "attachment",
        filename="rapport_diagnostic_ia.pdf",
    )
    msg.attach(part)

    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls()
        if user and password:
            server.login(user, password)
        server.sendmail(from_addr, [to_email], msg.as_string())
