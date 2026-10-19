# Asset Explorer — System Architecture

## Overview

Asset Explorer is a production web platform for monitoring the health of **987 power transformers** across **436 substations**. It provides a real-time risk dashboard, asset drill-down with trend analysis, AI-assisted inspection scoring, and a RAG-powered diagnostic chatbot.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         USER'S BROWSER                                  │
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │  React (Vite + TypeScript) SPA                                  │  │
│   │                                                                 │  │
│   │  Tab 1: Fleet Overview          Tab 2: Asset List → Drill-down  │  │
│   │  ├─ KPI cards (GREEN/AMBER/RED) ├─ Searchable/sortable table    │  │
│   │  ├─ Metric filter buttons       └─ Per-asset panels:            │  │
│   │  ├─ 14-week trend chart            ├─ 5 metric trend charts     │  │
│   │  └─ Top 5 critical cards          ├─ Work order timeline        │  │
│   │                                   ├─ Inspection photo           │  │
│   │                                   └─ RAG chatbot                │  │
│   └────────────────────┬────────────────────────────────────────────┘  │
│                         │  JWT Bearer token (8h, HS256)                │
│                         │  HTTPS                                        │
└─────────────────────────┼───────────────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────────────────┐
│                    ENTERPRISE NETWORK                                   │
│                                                                         │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │  SAML/SSO Authentication Flow                                  │   │
│   │                                                                │   │
│   │  Browser → /api/saml/login → IdP (ADFS/Entra) ────────────►  │   │
│   │  IdP validates credentials                                     │   │
│   │  IdP → POST /api/saml/acs (SAML Response XML)                 │   │
│   │  FastAPI validates signature → issues JWT → redirect ?token=  │   │
│   │  frontend consumeTokenFromUrl() stores JWT, cleans URL         │   │
│   └────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│                   OCI (Oracle Cloud Infrastructure)                    │
│                                                                        │
│   OCI Load Balancer                                                    │
│        │                                                               │
│        ├──► OCI Container Instance: Backend                           │
│        │    ┌──────────────────────────────────────────────────┐      │
│        │    │  entrypoint.sh (fail-fast startup)               │      │
│        │    │   1. OCI Resource Principal auth                 │      │
│        │    │   2. Fetch wallet parts from OCI Vault           │      │
│        │    │   3. Write wallet files to /app/wallet/          │      │
│        │    │   4. python load_data.py (Oracle preflight)      │      │
│        │    │   5. exec gunicorn (Uvicorn workers)             │      │
│        │    │                                                   │      │
│        │    │  FastAPI Application                             │      │
│        │    │   ├─ JWT middleware (all routes)                 │      │
│        │    │   ├─ GET /api/fleet (ThreadPoolExecutor×3)      │      │
│        │    │   ├─ GET /api/substations                       │      │
│        │    │   ├─ GET /api/metrics/{id}/*                    │      │
│        │    │   ├─ GET /api/photo (Fulcrum BFF proxy)         │      │
│        │    │   └─ POST /api/chat (RAG pipeline)              │      │
│        │    └──────────────────────────────────────────────────┘      │
│        │                                                               │
│        └──► OCI Container Instance: Frontend (Nginx)                 │
│             ┌──────────────────────────────────────────────────┐      │
│             │  Nginx serving Vite build                         │      │
│             │   - /health.txt → 200 (health check)             │      │
│             │   - /assets/* → immutable cache (1 year)         │      │
│             │   - /* → index.html (SPA fallback)               │      │
│             └──────────────────────────────────────────────────┘      │
│                                                                        │
│   OCI Vault                Oracle Autonomous DB          OCIR          │
│   ┌───────────────┐       ┌──────────────────────┐    ┌────────────┐  │
│   │ ewallet.pem   │       │ SUBSTATION_HEALTH_VW  │    │ Backend    │  │
│   │ tnsnames.ora  │       │ WORK_ORDER_SUMMARY_VW │    │ Frontend   │  │
│   │ sqlnet.ora    │       │ (read-only views)     │    │  images    │  │
│   └───────────────┘       └──────────────────────┘    └────────────┘  │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│                  AZURE COGNITIVE SERVICES                              │
│                                                                        │
│   Azure OpenAI                Azure AI Search        Azure AI Vision   │
│   ┌──────────────┐           ┌──────────────────┐   ┌──────────────┐  │
│   │ GPT-4        │           │ HNSW vector index│   │ Defect       │  │
│   │ ada-002      │◄──────────│ similarity ≥0.45 │   │ detection    │  │
│   │ embeddings   │  chunks   │ TOP_K = 5        │   │ Laplacian    │  │
│   └──────────────┘           └──────────────────┘   │ pre-filter   │  │
│                                                       └──────────────┘  │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│              AZURE DEVOPS CI/CD (main branch)                          │
│                                                                        │
│   Stage 1: Build & Check                                               │
│   ├─ tsc -b --noEmit (TypeScript strict)                               │
│   ├─ ESLint                                                            │
│   ├─ mypy (Python type check)                                          │
│   ├─ pytest                                                            │
│   └─ SonarCloud SAST                                                   │
│                                                                        │
│   Stage 2: Container Build                                             │
│   ├─ docker build (BuildKit --secret for pip feed)                    │
│   ├─ push to OCIR by tag (SHA + Build ID)                             │
│   └─ capture digest (immutable) for deploy                            │
│                                                                        │
│   Stage 3: Deploy (manual gate)                                        │
│   ├─ Create new OCI Container Instance (by digest)                    │
│   ├─ Wait ACTIVE + health check (/health)                             │
│   ├─ Update LB backend set (route traffic to new)                     │
│   ├─ Drain in-flight requests (30s)                                   │
│   └─ Delete old container                                             │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

### 1. SAML/SSO with JWT (not session cookies)

The backend issues a short-lived JWT (8 hours, HS256) after validating the SAML Response from the enterprise IdP. The JWT is passed to the frontend via a `?token=` URL query parameter, which `consumeTokenFromUrl()` immediately stores in `localStorage` and removes from the URL via `history.replaceState` — preventing the token from appearing in browser history or server access logs.

All subsequent API calls include `Authorization: Bearer <jwt>` in the header, validated by the `jwt_middleware` on every request (except `/health`, `/api/saml/*`, and `/api/docs`).

### 2. BFF (Backend-for-Frontend) Pattern

All third-party credentials (Azure OpenAI, Azure AI Search, Fulcrum API key) live **exclusively on the server**. The browser never sees them. This is the BFF pattern: the FastAPI backend acts as a trusted proxy, enriching responses with data from Fulcrum, Azure, and Oracle before sending to the client.

### 3. OCI Resource Principal (no hardcoded credentials)

The container instance **IS** the credential. `entrypoint.sh` calls the OCI Instance Metadata Service (IMDS) to obtain a Resource Principal token, which is then used to fetch wallet secrets from OCI Vault. No service account keys, no password files — the only credential is the container's assigned OCI dynamic group + policy.

### 4. Fail-fast `entrypoint.sh`

`set -euo pipefail` means any failure (Vault fetch, empty file, Oracle preflight) exits the process before Gunicorn starts. The OCI Load Balancer health check sees the container as unhealthy and never routes traffic to it. This prevents a degraded container from silently serving bad data.

### 5. ThreadPoolExecutor for parallel Oracle queries

`GET /api/fleet` requires three Oracle queries (band counts, top critical, trend). Running them sequentially would take ~3s. Using `ThreadPoolExecutor` with `concurrent.futures.as_completed`, all three run in parallel (~1s wall time). The executor is a module-level singleton — not created per request — to avoid thread pool overhead.

### 6. Blue-Green Deployment

A new container is fully started, health-checked (polling `/health` → `SELECT 1 FROM DUAL`) and confirmed active **before** the load balancer backend set is updated. Old in-flight requests are drained for 30 seconds before the old container is deleted. This gives zero-downtime deployments and an easy rollback path (keep old container OCID until new one passes smoke test).

### 7. RAG Similarity Threshold (0.45)

The chatbot only answers questions where retrieved chunks have cosine similarity ≥ 0.45. Below this threshold, the system returns "I couldn't find reliable information" rather than hallucinating. This is a safety-critical design choice: the transformers being monitored feed hospitals, airports, and industrial sites.

---

## Health Metric Scoring

| Metric | Standard | Weight |
|--------|----------|--------|
| FAA Thermal Aging | IEC 60076-7, eq. 3 | 30% |
| Hotspot Temperature | IEEE C57.91 | 25% |
| Overload Severity | MVA ratio | 20% |
| Winding Resistance Δ | % from factory | 10% |
| Tap Changer Ops/Day | TPOSC count | 10% |
| Load-Temp Sensitivity | Pearson r (30-day) | 5% |

**Risk bands:** GREEN > 70 · AMBER 40–70 · RED < 40

---

## Production Incident Record (Post-Mortem)

**Date:** November 2024  
**Symptom:** Blank white screen post-deploy, strongest in incognito mode  
**Initial diagnosis (wrong):** SAML authentication loop  
**Actual cause:** JS bundle 404 — old Nginx container drained before new one served static files  

**Diagnosis steps:**
1. `curl /health` → 200 (FastAPI healthy)
2. `curl /` → 200 with HTML (index.html served correctly)
3. `curl /assets/index-abc123.js` → **404** (bundle missing)
4. Incognito → no cached JS → cold-start reveals timing issue
5. Timeline cross-check: load balancer cutover timestamp vs. new container startup time → 45-second gap

**Key insight:** SAML (handles auth redirect, returns HTML) and bundle delivery (Nginx serves JS files) are **separate systems**. The blank screen was not an auth failure — it was a CDN/static-file timing race.

**Resolution:** Platform team updated the deployment script to health-check the frontend Nginx (via `/health.txt`) before cutting over the load balancer backend, ensuring the new container serves static assets before any browser requests reach it.

**Prevention:** The Azure DevOps pipeline now includes an explicit frontend health check step in Stage 3 before the LB cutover (see `.azure-devops/pipeline.yml`, "Health-check new container").
