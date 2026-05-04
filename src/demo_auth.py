"""Authentification démo : identifiants lus via os.getenv (.env), jamais journalisés."""

from __future__ import annotations

import os
from typing import TypedDict


class DemoUserRow(TypedDict):
    password: str
    role: str


def _get_str(key: str, default: str = "") -> str:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default.strip()
    return raw.strip()


def _client_password() -> str:
    return _get_str("CLIENT_PASSWORD", "") or "Client_demo_2026!"


def _admin_password() -> str:
    return _get_str("ADMIN_PASSWORD", "") or "Admin_demo_2026!"


def get_demo_users() -> dict[str, DemoUserRow]:
    """Carte email (minuscules) → mot de passe et rôle (user | admin)."""
    client_email = _get_str("CLIENT_EMAIL", "client@demo.fr").lower()
    admin_email = _get_str("ADMIN_EMAIL", "admin@demo.fr").lower()
    return {
        client_email: {"password": _client_password(), "role": "user"},
        admin_email: {"password": _admin_password(), "role": "admin"},
    }


def validate_login(email: str, password: str) -> tuple[bool, str | None]:
    """
    Vérifie email / mot de passe contre la configuration (.env + repli démo).
    Retourne (True, rôle) si succès, (False, None) sinon. Ne logue jamais le secret.
    """
    key = email.strip().lower()
    row = get_demo_users().get(key)
    if row is None or row["password"] != password:
        return False, None
    return True, row["role"]
