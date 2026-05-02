"""
Abstraction des fournisseurs LLM : OpenAI, Mistral, Ollama.
Remplacer le provider se fait via la variable d'environnement LLM_PROVIDER.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import requests

from .config import Settings


class LLMProvider(ABC):
    """Interface commune pour générer du texte à partir d'un prompt."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        raise NotImplementedError


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    def generate(self, prompt: str) -> str:
        from openai import OpenAI

        if not self._api_key:
            raise ValueError("OPENAI_API_KEY manquant pour le provider OpenAI.")

        client = OpenAI(api_key=self._api_key)
        resp = client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
        )
        choice = resp.choices[0].message.content
        if not choice:
            raise RuntimeError("Réponse OpenAI vide.")
        return choice


class MistralProvider(LLMProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    def generate(self, prompt: str) -> str:
        from mistralai import Mistral

        if not self._api_key:
            raise ValueError("MISTRAL_API_KEY manquant pour le provider Mistral.")

        client = Mistral(api_key=self._api_key)
        resp = client.chat.complete(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
        )
        choice = resp.choices[0].message.content
        if not choice:
            raise RuntimeError("Réponse Mistral vide.")
        return choice


class OllamaProvider(LLMProvider):
    """Client HTTP vers l'API locale Ollama (compatible remplacement cloud)."""

    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    def generate(self, prompt: str) -> str:
        url = f"{self._base_url}/api/chat"
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        r = requests.post(url, json=payload, timeout=120)
        r.raise_for_status()
        data = r.json()
        msg = data.get("message") or {}
        content = msg.get("content")
        if not content:
            raise RuntimeError("Réponse Ollama vide ou format inattendu.")
        return str(content)


def get_llm_provider(settings: "Settings") -> LLMProvider:
    """Instancie le provider selon LLM_PROVIDER."""
    p = settings.llm_provider
    if p == "openai":
        return OpenAIProvider(settings.openai_api_key, settings.openai_model)
    if p == "mistral":
        return MistralProvider(settings.mistral_api_key, settings.mistral_model)
    if p == "ollama":
        return OllamaProvider(settings.ollama_base_url, settings.ollama_model)
    raise ValueError(f"LLM_PROVIDER inconnu: {p}. Utiliser openai, mistral ou ollama.")
