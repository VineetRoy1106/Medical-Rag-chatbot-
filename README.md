# Curalink — AI Medical Research Assistant

Full-stack MERN + Python FastAPI application with:
- HyDE query expansion
- Parallel retrieval (PubMed + OpenAlex + ClinicalTrials.gov)
- Sentence transformer semantic ranking
- Multi-signal scoring (human/animal weighting, dynamic recency)
- Self-RAG + Corrective RAG
- Personalized synthesis via Groq LLaMA 3.1 70B
- Full user profile + personalization stored in MongoDB
- LangSmith observability

---

## Prerequisites

- Python 3.11+
- Node.js 18+
- [uv](https://github.com/astral-sh/uv) — fast Python package manager
- MongoDB Atlas account (free tier works)
- Groq API key — https://console.groq.com
- LangSmith API key — https://smith.langchain.com (optional but recommended)

---

## Quick Start

### 1. Clone and set up environment

```bash
git clone <repo>
cd curalink
cp .env.example .env
# Edit .env and fill in your keys
```

### 2. Install Python dependencies (using uv)

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment and install
cd server
uv venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
uv pip install -r requirements.txt
```

> First run downloads the sentence-transformers model (~80MB). Takes ~30s once, then cached.

### 3. Install Node dependencies

```bash
# Express server
cd ../express-server
npm install

# React client
cd ../client
npm install
```

### 4. Start all services

Open **3 terminals**:

**Terminal 1 — FastAPI (Python AI pipeline)**
```bash
cd server
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 — Express (MERN gateway)**
```bash
cd express-server
npm run dev
```

**Terminal 3 — React (frontend)**
```bash
cd client
npm start
```

### 5. Open the app

| Service | URL |
|---|---|
| React UI | http://localhost:3000 |
| Swagger UI (API docs) | http://localhost:8000/docs |
| Express gateway | http://localhost:5000 |

---

## Environment Variables

```env
# Required
GROQ_API_KEY=gsk_...          # From console.groq.com
MONGODB_URI=mongodb+srv://...  # From MongoDB Atlas

# Optional but recommended
LANGSMITH_API_KEY=ls__...      # From smith.langchain.com
LANGSMITH_PROJECT=curalink
LANGCHAIN_TRACING_V2=true

PUBMED_API_KEY=...             # From NCBI — increases rate limits

# Ports
FASTAPI_PORT=8000
EXPRESS_PORT=5000
FASTAPI_URL=http://localhost:8000
```

---

## MongoDB Collections

Curalink automatically creates and indexes these collections:

| Collection | Purpose | TTL |
|---|---|---|
| `sessions` | Conversation history + context summaries | None |
| `query_cache` | Cached pipeline results | 24 hours |
| `users` | Full user profiles + preferences + behavior | None |
| `query_history` | Per-user query history + pipeline metadata | 90 days |
| `bookmarks` | Saved papers and trials per user | None |

---

## User Profile — Personalization

Create a user profile before querying for full personalization:

```bash
curl -X POST http://localhost:8000/api/users \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_john_001",
    "name": "John Smith",
    "age": 62,
    "gender": "male",
    "location": "Toronto, Canada",
    "conditions": [
      {"name": "Parkinson'\''s disease", "severity": "moderate"}
    ],
    "medications": [
      {"name": "Levodopa", "dose": "100mg", "frequency": "3x daily"}
    ],
    "preferences": {
      "preferred_study_types": ["human_rct", "human_systematic_review"],
      "language_complexity": "intermediate",
      "show_animal_studies": false,
      "location_bias_trials": true
    }
  }'
```

Then include `user_id` in queries:

```bash
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Deep Brain Stimulation outcomes",
    "disease": "Parkinson'\''s disease",
    "user_id": "user_john_001"
  }'
```

---

## What Gets Personalized

| Signal | Source | Effect |
|---|---|---|
| Preferred study types | User preferences | Animal studies hidden, RCTs boosted |
| Location | User profile | Trial location scoring boosted |
| Language complexity | Preferences + query count | Groq explains simply or technically |
| Medications | User profile | Synthesis notes drug interactions |
| Conditions | User profile | Insights framed as personally relevant |
| Bookmarks | Behavior | Previously saved papers get slight boost |
| Query history | Behavior | Session context injected into HyDE |

---

## Pipeline Stages

```
Query + user_id
    ↓
Load user profile from MongoDB (personalization context)
    ↓
Session lookup / create (follow-up detection)
    ↓
Cache check (24h TTL) — skip for follow-ups
    ↓
Call 1: Groq HyDE expansion (~0.3s)
    ↓
Parallel API retrieval: PubMed + OpenAlex + ClinicalTrials (~1s)
    ↓
Deduplicate + pre-filter (hard rules + user study type prefs)
    ↓
Sentence transformer embedding + cosine ranking (~1.5s batched)
    ↓
Multi-signal scoring (semantic 40%, human/animal 25%, recency dynamic, citations 10%)
    ↓
Personalization scoring layer (preferred types, location bias, bookmarks)
    ↓
Call 2: Groq rerank + Self-RAG + Corrective RAG verdict (~0.5s)
    ↓
[Conditional] Corrective RAG re-retrieval (~1s, ~30% of queries)
    ↓
Call 3: Groq personalized synthesis + grounding check (~0.8s)
    ↓
Save query history + update behavior signals in MongoDB
    ↓
Return structured JSON response
```

**Total latency: ~4–6s** (happy path, no corrective RAG)

---

## Deployment

### Render.com (recommended for hackathon)

**FastAPI service:**
- Build: `cd server && pip install -r requirements.txt`
- Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`

**Express + React:**
- Build: `cd client && npm install && npm run build`
- Start: `cd express-server && npm install && node index.js`

Add all `.env` variables in Render's environment settings.

---

## API Reference

Full interactive docs at **http://localhost:8000/docs** (Swagger UI)

| Endpoint | Method | Description |
|---|---|---|
| `/api/query` | POST | Main research query |
| `/api/users` | POST | Create user profile |
| `/api/users/{id}` | GET | Get user profile |
| `/api/users/{id}/preferences` | PUT | Update preferences |
| `/api/users/{id}/history` | GET | Query history |
| `/api/users/{id}/bookmarks` | POST | Add bookmark |
| `/api/users/{id}/bookmarks` | GET | List bookmarks |
| `/api/users/{id}/bookmarks/{item_id}` | DELETE | Remove bookmark |
| `/health` | GET | Health check |
| `/docs` | GET | Swagger UI |
