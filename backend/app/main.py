"""
app/main.py — FastAPI application entry point

Registers all routers and middleware.
Served by Gunicorn + UvicornWorker in production (see Dockerfile).
"""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.auth import jwt_middleware
from app.endpoints import substations, fleet, metrics, photo, chat, health

app = FastAPI(
    title="Asset Explorer — Substation Health API",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url=None,
)

# CORS — allow React frontend origin
CORS_ORIGIN = os.getenv("CORS_ORIGIN", "http://localhost:5173")  # Vite default port
app.add_middleware(
    CORSMiddleware,
    allow_origins=[CORS_ORIGIN],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# JWT auth middleware — validates Bearer token on all /api/* routes except /health and /saml/*
app.middleware("http")(jwt_middleware)

# Routers
app.include_router(health.router)                          # GET /health
app.include_router(substations.router, prefix="/api")     # GET /api/substations
app.include_router(fleet.router, prefix="/api")           # GET /api/fleet
app.include_router(metrics.router, prefix="/api")         # GET /api/metrics/*
app.include_router(photo.router, prefix="/api")           # GET /api/photo
app.include_router(chat.router, prefix="/api")            # POST /api/chat
