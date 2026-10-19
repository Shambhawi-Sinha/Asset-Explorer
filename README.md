# Asset Explorer — Substation Asset Health Platform

> Real-time transformer health monitoring for **987 assets** across **436 substations**.  
> React (Vite + TypeScript) · FastAPI · Oracle ADB · Azure OpenAI · Azure AI Search · OCI

[![Build Status](https://dev.azure.com/your-org/asset-explorer/_apis/build/status/asset-explorer?branchName=main)](https://dev.azure.com/your-org/asset-explorer/_build)
[![SonarCloud](https://sonarcloud.io/api/project_badges/measure?project=asset-explorer&metric=alert_status)](https://sonarcloud.io/project/overview?id=asset-explorer)

---

## What It Does

Asset Explorer gives operations engineers and asset managers a single view of transformer health across the entire substation fleet, from fleet-level risk trends down to per-asset diagnostic details.

**Fleet Overview tab**
- Live KPI cards: GREEN / AMBER / RED asset counts
- Metric filter buttons — isolate by thermal / overload / tap-changer / winding risk
- 14-week fleet health trend chart with dual Y-axes (average score + RED count)
- Top 5 critical assets (clickable through to drill-down)

**Asset List tab**
- Searchable, sortable table of all 987 transformers with score bars
- Emergency work order highlighting
- Click any row to open the asset drill-down

**Asset Drill-Down**
- Five 90-day metric trend charts: FAA, hotspot, overload, tap-changer, winding
- Warning and critical threshold reference lines (IEC/IEEE standards)
- Colour-coded work order timeline (PREVENTIVE / CORRECTIVE / EMERGENCY)
- Fulcrum inspection photo via BFF proxy (API key stays server-side)
- RAG diagnostic chatbot — GPT-4 grounded on retrieved maintenance documents

---

## Architecture

```
Browser (React SPA)
  │  JWT Bearer (8h, HS256)
  ▼
FastAPI + Gunicorn/Uvicorn          Azure Cognitive Services
  ├─ SAML/SSO middleware            ├─ Azure OpenAI (GPT-4 + ada-002)
  ├─ JWT middleware                 ├─ Azure AI Search (HNSW vector index)
  ├─ GET /api/fleet (3× parallel)  └─ Azure AI Vision (defect scoring)
  ├─ GET /api/substations
  ├─ GET /api/metrics/{id}/*        Fulcrum (field inspections)
  ├─ GET /api/photo (BFF proxy)     └─ Two-step image fetch (API key server-side)
  └─ POST /api/chat (RAG)
        │
        ▼
  Oracle Autonomous DB              OCI Vault
  SUBSTATION_HEALTH_VW              ├─ ewallet.pem
  WORK_ORDER_SUMMARY_VW             ├─ tnsnames.ora
                                    └─ sqlnet.ora (fetched at startup by entrypoint.sh)
```

See [`docs/architecture.md`](docs/architecture.md) for the full diagram, design decisions, and production incident post-mortem.

---

## Quick Start (Mock Mode — no credentials required)

```bash
# Clone the repo
git clone https://github.com/your-org/asset-explorer.git
cd asset-explorer

# Start with Docker Compose (mock mode on by default)
docker compose up --build

# Open the app
open http://localhost:5173
```

All data is served from `sample_data/` — no Oracle, Azure, or Fulcrum credentials needed.

---

## Local Development (without Docker)

**Backend:**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r ../requirements.txt

# Run in mock mode
MOCK_MODE=true uvicorn app.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm ci
VITE_MOCK_MODE=true npm run dev
# Open http://localhost:5173
```

The Vite dev server proxies `/api/*` requests to `localhost:8000` (see `vite.config.ts`).

---

## Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description | Required in mock mode |
|----------|-------------|----------------------|
| `MOCK_MODE` | `true` to use sample data | No (default `true`) |
| `JWT_SECRET` | HS256 signing key (≥32 chars) | Yes (any value) |
| `DB_DSN` | Oracle TNS alias | No |
| `AZURE_OPENAI_KEY` | Azure OpenAI API key | No |
| `AZURE_SEARCH_KEY` | Azure AI Search key | No |
| `FULCRUM_API_KEY` | Fulcrum field app key | No |

See `.env.example` for the full list.

---

## Project Structure

```
asset-explorer/
├── backend/
│   ├── app/
│   │   ├── core/
│   │   │   ├── auth.py          # SAML/SSO + JWT middleware
│   │   │   └── db.py            # Oracle ADB + ThreadPoolExecutor
│   │   ├── endpoints/
│   │   │   ├── fleet.py         # GET /api/fleet (3× parallel queries)
│   │   │   ├── substations.py   # GET /api/substations
│   │   │   ├── metrics.py       # GET /api/metrics/{id}/*
│   │   │   ├── photo.py         # GET /api/photo (Fulcrum BFF proxy)
│   │   │   ├── chat.py          # POST /api/chat (RAG)
│   │   │   └── health.py        # GET /health
│   │   ├── rag/
│   │   │   └── pipeline.py      # ada-002 → AI Search → GPT-4
│   │   └── main.py              # FastAPI app, CORS, middleware
│   ├── scripts/
│   │   ├── entrypoint.sh        # OCI Vault wallet fetch (fail-fast)
│   │   └── load_data.py         # Oracle preflight checks
│   ├── Dockerfile               # Multi-stage Python/Gunicorn
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   └── client.ts        # JWT storage + all API functions
│   │   ├── components/
│   │   │   ├── FleetOverview.tsx
│   │   │   ├── AssetList.tsx
│   │   │   ├── AssetDrillDown.tsx
│   │   │   ├── MetricChart.tsx  # Recharts + threshold reference lines
│   │   │   ├── WorkOrderTimeline.tsx
│   │   │   ├── InspectionPhoto.tsx
│   │   │   └── ChatPanel.tsx
│   │   ├── types/index.ts       # Full TypeScript domain types
│   │   ├── App.tsx              # Two-tab app, parallel data load
│   │   └── main.tsx             # consumeTokenFromUrl() before React mount
│   ├── Dockerfile               # Multi-stage Node/Nginx
│   └── nginx.conf               # SPA fallback, immutable asset cache
│
├── pipeline/
│   ├── health_metrics.py        # FAA, hotspot, overload, tap, sensitivity
│   ├── composite_score.py       # Weighted 0-100 score + GREEN/AMBER/RED
│   ├── vision_scoring.py        # Azure AI Vision + Laplacian pre-filter
│   └── rag_indexing.py          # Chunk → embed → upsert to AI Search
│
├── sample_data/                 # Mock data (MOCK_MODE=true)
│   ├── health_scores.csv
│   ├── work_orders.json
│   ├── health_trend.json
│   ├── transformers.csv
│   └── sensor_readings.csv
│
├── .azure-devops/
│   └── pipeline.yml             # Build & Check → Container Build → Blue-Green Deploy
├── docs/
│   └── architecture.md
├── notebooks/
│   └── health_metrics_demo.ipynb
├── docker-compose.yml
├── .env.example
└── .gitignore
```

---

## CI/CD Pipeline

The Azure DevOps pipeline (`.azure-devops/pipeline.yml`) has three stages:

**Stage 1: Build & Check** — runs on every PR and push to `main`
- TypeScript strict type-check (`tsc -b --noEmit`) — mandatory gate
- ESLint
- Python mypy type check
- pytest unit tests
- SonarCloud SAST (main branch only)

**Stage 2: Container Build** — runs on `main` only
- Multi-stage Docker builds (BuildKit `--secret` for private feeds)
- Images pushed to OCI Container Registry tagged `<git-sha>-<build-id>`
- Immutable digest captured for deployment

**Stage 3: Deploy (manual approval)** — blue-green to OCI
- New container instance created by digest
- Health-checked (polls `/health` until 200)
- Load balancer updated to new container
- Old container drained (30s) then deleted

---

## Health Scoring Methodology

Composite score (0–100, higher = healthier):

| Sub-metric | Standard | Weight |
|-----------|----------|--------|
| FAA Thermal Aging Factor | IEC 60076-7 Eq. 3: `exp(15000/383 - 15000/(273+θH))` | 30% |
| Hotspot Temperature | IEEE C57.91: `θA + ΔθTO × K^2N + ΔθHR × K^2M` | 25% |
| Overload Severity | `MVA_actual / MVA_rated` | 20% |
| Winding Resistance Δ | % from factory acceptance test | 10% |
| Tap Changer Ops/Day | Daily TPOSC count (>30/day = critical) | 10% |
| Load-Temp Sensitivity | Pearson r over 30-day rolling window | 5% |

Risk bands: **GREEN** > 70 · **AMBER** 40–70 · **RED** < 40

---

## RAG Chat Pipeline

1. User question → `text-embedding-ada-002` (1536-dim embedding)
2. Vector search in Azure AI Search (HNSW, cosine similarity)
3. Similarity threshold filter: **≥ 0.45** (below → "insufficient information")
4. Top-K=5 chunks passed to GPT-4 with grounding system prompt
5. GPT-4 returns answer + cited source references

The RAG module is lazily imported inside the `chat()` handler — Azure client objects are not initialised at startup, which prevents credential errors from blocking the health endpoint in MOCK_MODE.

---

## Security Notes

- Wallet files (`*.pem`, `*.ora`) are blocked by `.gitignore` — never in source control
- All third-party API keys are environment variables — never hardcoded
- In production, secrets come from OCI Vault via Resource Principal (no service account keys)
- BuildKit `--secret` prevents private pip feed credentials from appearing in `docker history`
- JWT passed via URL param only momentarily; `consumeTokenFromUrl()` removes it from URL immediately after storage

---

## License

Internal — not for public distribution.  
All client data, credentials, and business logic replaced with synthetic mock data in this repository.
