"""Chargement de la configuration depuis l'environnement (.env)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Charge .env à la racine du projet (parent de src/)
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


def _get_str(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _get_lower(key: str, default: str) -> str:
    return _get_str(key, default).lower()


_ALLOWED_LLM_PROVIDERS = frozenset({"openai", "mistral", "ollama"})


@dataclass
class Settings:
    """Paramètres runtime pour les providers LLM."""

    llm_provider: str
    openai_api_key: str
    openai_model: str
    mistral_api_key: str
    mistral_model: str
    ollama_base_url: str
    ollama_model: str

    @classmethod
    def load(cls) -> "Settings":
        prov = _get_lower("LLM_PROVIDER", "openai")
        if prov not in _ALLOWED_LLM_PROVIDERS:
            raise ValueError(
                f"LLM_PROVIDER={prov!r} n'est pas reconnu. "
                f"Valeurs possibles : {', '.join(sorted(_ALLOWED_LLM_PROVIDERS))}."
            )
        return cls(
            llm_provider=prov,
            openai_api_key=_get_str("OPENAI_API_KEY"),
            openai_model=_get_str("OPENAI_MODEL", "gpt-4o-mini"),
            mistral_api_key=_get_str("MISTRAL_API_KEY"),
            mistral_model=_get_str("MISTRAL_MODEL", "mistral-small-latest"),
            ollama_base_url=_get_str("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
            ollama_model=_get_str("OLLAMA_MODEL", "llama3.2:3b"),
        )


def get_settings() -> Settings:
    """Instance unique de configuration (recalculée à chaque appel, pratique pour les tests)."""
    return Settings.load()
