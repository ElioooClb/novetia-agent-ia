"""
Abstraction des fournisseurs LLM : OpenAI, Mistral, Ollama.
Remplacer le provider se fait via la variable d'environnement LLM_PROVIDER.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

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


def _ollama_post_json(url: str, payload: dict[str, Any], model: str, *, timeout: int = 120) -> dict[str, Any]:
    """POST JSON vers Ollama. Lève RuntimeError avec un message exploitable dans l'UI Streamlit."""
    try:
        r = requests.post(url, json=payload, timeout=timeout)
    except requests.exceptions.ConnectionError as exc:
        raise RuntimeError(
            "Impossible de joindre Ollama. Vérifiez que l'application Ollama est lancée "
            "et que OLLAMA_BASE_URL pointe vers le bon hôte (ex. http://localhost:11434)."
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise RuntimeError(
            "Délai dépassé en appelant Ollama. Réessayez ou vérifiez la charge du modèle local."
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Erreur réseau vers Ollama : {exc}") from exc

    try:
        data: dict[str, Any] = r.json()
    except ValueError:
        if not r.ok:
            raise RuntimeError(
                f"Ollama a répondu HTTP {r.status_code} avec un corps non JSON. "
                f"Détail : {(r.text or '')[:240]}"
            ) from None
        raise RuntimeError(
            "Réponse inattendue d'Ollama (JSON invalide). Vérifiez OLLAMA_BASE_URL."
        ) from None

    if not r.ok:
        err = ""
        if isinstance(data, dict):
            err = str(data.get("error", ""))
        if not err:
            err = (r.text or "")[:240]
        raise RuntimeError(
            f"Ollama a répondu HTTP {r.status_code} : {err}. "
            f"Si le modèle n'est pas installé : `ollama pull {model}`"
        )

    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(
            f"Ollama signale une erreur : {data.get('error')}. "
            f"Vérifiez le nom du modèle (`OLLAMA_MODEL`, actuellement « {model} »)."
        )

    return data


def ollama_chat_completion(
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.3,
    num_predict: int = 180,
    num_ctx: int = 2048,
    timeout: int = 90,
) -> str:
    """
    Appel Ollama /api/chat (assistant conversationnel local).

    Les options (température, num_predict, num_ctx) ne s'appliquent pas au diagnostic,
    qui utilise :class:`OllamaProvider` et l'endpoint /api/generate.
    """
    url = f"{base_url.rstrip('/')}/api/chat"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
            "num_ctx": num_ctx,
        },
    }
    data = _ollama_post_json(url, payload, model, timeout=timeout)
    msg = data.get("message") or {}
    content = msg.get("content")
    if content is None or str(content).strip() == "":
        raise RuntimeError(
            f"Réponse vide depuis Ollama (chat). Essayez : ollama pull {model}"
        )
    return str(content)


class OllamaProvider(LLMProvider):
    """Client HTTP vers l'API locale Ollama — un prompt par appel (/api/generate)."""

    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    def generate(self, prompt: str) -> str:
        url = f"{self._base_url}/api/generate"
        payload: dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
        }
        data = _ollama_post_json(url, payload, self._model)
        text = data.get("response")
        if text is None or str(text).strip() == "":
            raise RuntimeError(
                f"Réponse vide depuis Ollama (génération). Essayez : ollama pull {self._model}"
            )
        return str(text)


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
