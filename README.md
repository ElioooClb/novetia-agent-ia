# NovetIA — Agent diagnostic IA (TPE/PME)

Projet Python de démonstration : **agent conversationnel métier** qui interroge un dirigeant (via formulaire), analyse les réponses, croise une base de cas d’usage IA et propose **trois recommandations prioritaires** avec ordres de grandeur (impact, difficulté, gain de temps, ROI approximatif).

## Objectif du test

Rendre compte d’une chaîne complète **données → outil (JSON) → règles (scoring) → LLM → livrable (Markdown)** dans un format **simple, lisible et démontrable en ~5 minutes**, pour un entretien d’alternance **IA & Innovation** chez NovetIA.

## Fonctionnalités

- Formulaire dirigeant (entreprise, secteur, taille, irritants, tâches répétitives, outils, objectif, maturité numérique).
- Chargement d’une base de cas d’usage depuis `data/use_cases_ai.json`.
- **Scoring déterministe** : les trois meilleurs cas sont identifiés même si le LLM est indisponible.
- **Enrichissement LLM** (OpenAI, Mistral ou Ollama) via une abstraction `LLMProvider`.
- **Repli automatique** sur le scoring si l’API échoue ou si la réponse n’est pas du JSON valide.
- Génération d’un **rapport Markdown** (aperçu, téléchargement, enregistrement dans `outputs/`).

## Architecture

```
novetia-agent-ia/
├── app.py                 # Interface Streamlit
├── requirements.txt
├── .env.example
├── README.md
├── data/use_cases_ai.json   # Base métier (outil externe)
├── outputs/                 # Rapports générés (.md)
└── src/
    ├── config.py          # Variables d’environnement (python-dotenv)
    ├── llm_provider.py    # OpenAI, Mistral, Ollama — même interface
    ├── tools.py           # Lecture / filtrage JSON
    ├── scoring.py         # Score déterministe → top 3
    ├── agent.py           # Orchestration + prompt + repli
    └── report.py          # Export Markdown
```

Le choix du fournisseur se fait avec **`LLM_PROVIDER`** (`openai`, `mistral`, `ollama`). Pour passer du cloud au **local**, il suffit de basculer vers `ollama` et de lancer un modèle sur `OLLAMA_BASE_URL` (par défaut `http://localhost:11434`), sans changer le reste de l’application.

## Installation

```bash
cd novetia-agent-ia
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Copier `.env.example` vers `.env` et renseigner les clés **sans les commiter**.

## Configuration (.env)

| Variable | Rôle |
|----------|------|
| `LLM_PROVIDER` | `openai`, `mistral` ou `ollama` |
| `OPENAI_API_KEY` | Clé API OpenAI |
| `OPENAI_MODEL` | Ex. `gpt-4o-mini` |
| `MISTRAL_API_KEY` | Clé API Mistral |
| `MISTRAL_MODEL` | Ex. `mistral-small-latest` |
| `OLLAMA_BASE_URL` | Ex. `http://localhost:11434` |
| `OLLAMA_MODEL` | Ex. `llama3.2` |

Aucune clé ne doit figurer dans le code : tout passe par l’environnement / `.env`.

## Lancement Streamlit

```bash
streamlit run app.py
```

Ouvrir l’URL indiquée dans le terminal (souvent `http://localhost:8501`).

## Choix techniques (résumé)

- **Streamlit** : mise en page rapide pour une démo oral / jury.
- **Scoring non ML** : garantit un résultat cohérent et **explicable** sans dépendre du réseau.
- **Abstraction `LLMProvider`** : un seul point d’extension pour brancher **OpenAI**, **Mistral** ou **Ollama** (HTTP local).
- **JSON métier** : simule un référentiel ou un outil métier versionnable hors code.

## Limites connues

- Pas d’authentification ni de multi-utilisateurs.
- Le scoring par mots-clés est volontairement naïf (démo, pas un moteur de recommandation production).
- Les estimations ROI / temps sont **indicatives** ; elles doivent être validées en atelier avec des données réelles.
- La qualité du JSON renvoyé par le LLM peut varier selon le modèle ; un repli sur le scoring est prévu.

## Pistes d’amélioration

- Embeddings / RAG sur une base documentaire interne.
- Historique des diagnostics et export PDF.
- Métriques d’usage et journalisation structurée.
- Tests unitaires sur `scoring` et parsing JSON LLM.

---

*Architecture compatible **API cloud** (OpenAI / Mistral) et **modèle local** via **Ollama** (`OLLAMA_BASE_URL`), en conservant la même interface `generate(prompt) -> str`.*
