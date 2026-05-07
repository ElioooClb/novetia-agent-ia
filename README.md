# NovetIA — Diagnostic IA TPE/PME

Application **Streamlit** de démonstration : aide les dirigeants de petites structures à **prioriser des usages de l’IA** adaptés à leur contexte, avec un parcours structuré (formulaire → scoring → enrichissement LLM → rapport).

---

## Objectif

- Proposer une **expérience claire** : conversation légère d’un côté, **diagnostic guidé** de l’autre.
- Montrer une chaîne **données → règles métier (scoring) → LLM → livrable** (Markdown / PDF), exploitable en présentation ou en atelier.
- Rester **pédagogique** : résultats compréhensibles même sans culture technique approfondie.

---

## Fonctionnalités

| Zone | Description |
|------|-------------|
| **Connexion démo** | Comptes de démonstration (identifiants via `.env`, voir `.env.example`). |
| **Assistant IA local** | Chat avec **Ollama** sur la machine : réponses courtes, orientation générale ; ne remplace pas le diagnostic structuré. |
| **Diagnostic IA de l’entreprise** | Formulaire (secteur, taille, irritants, objectifs, etc.), **top 3** cas d’usage issus d’une base JSON, enrichissement par **LLM** (OpenAI, Mistral ou Ollama). |
| **Repli scoring** | Si le LLM est indisponible ou renvoie un format inattendu, les trois recommandations restent cohérentes grâce au moteur de score déterministe. |
| **Rapports** | Synthèse, fiches par cas, export **Markdown** et **PDF** (polices Unicode pour le français). |
| **Historique de session** | Liste des diagnostics de la session courante (vue diagnostic). |

---

## Architecture

```
novetia-agent-ia/
├── app.py                    # Interface Streamlit (navigation, pages, sidebar)
├── requirements.txt
├── .env.example
├── assets/fonts/             # Polices PDF (Noto Sans, etc.)
├── data/use_cases_ai.json    # Base métier des cas d’usage IA
├── outputs/                  # Rapports .md exportés
└── src/
    ├── config.py             # Chargement .env (LLM, Ollama, options chat)
    ├── demo_auth.py          # Authentification démo (CLIENT_*, ADMIN_*)
    ├── local_chat.py         # Prompt + options dédiées au chat Ollama (/api/chat)
    ├── llm_provider.py       # OpenAI, Mistral, Ollama — diagnostic (/api/generate ou APIs cloud)
    ├── tools.py              # Lecture / filtrage de la base JSON
    ├── scoring.py            # Score déterministe → top 3
    ├── agent.py              # Orchestration diagnostic, prompt structuré, parsing JSON
    └── report.py             # Markdown + PDF
```

**Flux simplifié**

1. L’utilisateur remplit le **formulaire diagnostic** (ou discute dans le **chat**).
2. Le **scoring** classe les cas d’usage à partir de `data/use_cases_ai.json`.
3. Un **appel LLM** enrichit les trois premiers cas (selon `LLM_PROVIDER`).
4. Le moteur de scoring déterministe garantit un fonctionnement cohérent même si le LLM est indisponible.
5. `report.py` assemble le Markdown puis le PDF.

---

## Installation

### Prérequis

- Python **3.10+** recommandé  
- Testé sous **Python 3.11** et **Debian 12**
- Un compte / clé si vous utilisez **OpenAI** ou **Mistral** ; **Ollama** pour un mode entièrement local  

### Étapes

```bash
cd novetia-agent-ia
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux / macOS
pip install -r requirements.txt
```

Copier **`.env.example`** vers **`.env`** et renseigner les variables (sans commiter `.env`).

### Lancer l’application

```bash
streamlit run app.py
```

Ouvrir l’URL affichée dans le terminal (souvent `http://localhost:8501`).

---

## Déploiement serveur (Debian / OVH)

Le projet peut également être déployé sur un serveur Linux distant afin de proposer une démonstration accessible en réseau.

### Exemple de déploiement

```bash
git clone https://github.com/ElioooClb/novetia-agent-ia.git
cd novetia-agent-ia

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

### Lancement Streamlit

```bash
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

### Exécution comme service systemd

Le projet peut être exécuté comme service Linux afin d’assurer :

* le redémarrage automatique
* la persistance après reboot
* une supervision simplifiée

Exemple :

```bash
sudo systemctl start novetia
sudo systemctl status novetia
```

### Infrastructure utilisée

Le serveur Debian OVH héberge :

* l’application Streamlit
* le modèle Ollama local
* les exports de rapports

Le diagnostic peut fonctionner :

* soit entièrement en local via Ollama
* soit via des APIs cloud (OpenAI / Mistral)

---

## Stratégie LLM

### Choix du fournisseur (`LLM_PROVIDER`)

| Valeur | Usage principal | Remarque |
|--------|-----------------|----------|
| `openai` | Diagnostic via API OpenAI | `OPENAI_API_KEY`, `OPENAI_MODEL` |
| `mistral` | Diagnostic via API Mistral | `MISTRAL_API_KEY`, `MISTRAL_MODEL` |
| `ollama` | Diagnostic via modèle **local** | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` |

Le **chat** « Assistant IA local » utilise **toujours Ollama** (`OLLAMA_BASE_URL` / `OLLAMA_MODEL`) pour rester sur la machine, quel que soit `LLM_PROVIDER` utilisé pour le **diagnostic**.

### Options dédiées au chat (réponses plus courtes)

Variables optionnelles (voir `.env.example`) :

- `OLLAMA_CHAT_TEMPERATURE` — température du chat (ex. `0.3`)
- `OLLAMA_CHAT_MAX_TOKENS` — borne de génération (`num_predict`, ex. `180`)
- `OLLAMA_CHAT_NUM_CTX` — taille de contexte (ex. `2048`)

Le **diagnostic** conserve un prompt **long et structuré** (JSON) et n’applique pas ces limites du chat.

### Ollama : installation rapide

1. Installer [Ollama](https://ollama.com/).
2. Télécharger un modèle, par exemple : `ollama pull llama3.2:3b`
3. Dans `.env` : `LLM_PROVIDER=ollama`, `OLLAMA_BASE_URL=http://localhost:11434`, `OLLAMA_MODEL=llama3.2:3b`

---

## Configuration (.env) — rappel

Les secrets et URLs ne doivent **pas** être codés en dur : tout passe par **`.env`** (voir **`.env.example`** pour la liste des variables : LLM, Ollama, chat, comptes démo).

---

## Limites connues (démo)

- Authentification **démo** uniquement, non adaptée à la production.
- Scoring volontairement simple (mots-clés / règles), pas un moteur de recommandation avancé.
- Estimations de temps / ROI **indicatives** — à valider en atelier avec des données réelles.

---

## Pistes d’évolution

- RAG / embeddings sur documentation interne  
- Persistance des diagnostics et multi-utilisateurs  
- Multi-agents
- Connexion CRM/ERP
- Dasboard analytics

---

*NovetIA — démonstration **cloud** (OpenAI / Mistral) ou **locale** (Ollama), avec une interface unique Streamlit.*
