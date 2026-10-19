# ──────────────────────────────────────────────────────────────────────
# Frontend Dockerfile — Node/Nginx multi-stage build
# ──────────────────────────────────────────────────────────────────────
#
# Stage 1 (build): Node 20 Alpine
#   npm ci → tsc -b (TypeScript type-check) → Vite production build
#   Replaces __DYNATRACE_URL__ placeholder in built index.html
#   (Dynatrace RUM injection configured at CI time, not runtime)
#
# Stage 2 (serve): Nginx Alpine
#   Minimal image — only Nginx + built /dist
#   SPA fallback: try_files $uri $uri/ /index.html
#   Dotfile access disabled
#   Exposes port 80
#
# Build:
#   docker build -t asset-explorer-web:latest .
#
# Run (mock mode):
#   docker run -e REACT_APP_MOCK_MODE=true -p 80:80 asset-explorer-web:latest
# ──────────────────────────────────────────────────────────────────────

# ── Stage 1: Build ──────────────────────────────────────────────────
FROM node:20-alpine AS build

WORKDIR /app

# Copy package files first (cache layer — only invalidated if package.json changes)
COPY package.json package-lock.json ./

# npm ci: clean install from lock file — reproducible, fails on lock mismatch
RUN npm ci --prefer-offline

# Copy source and build
COPY . .

# TypeScript type check (fails build on type errors — catches issues pre-deploy)
RUN npx tsc -b --noEmit

# Production Vite build (tree-shaking, minification, chunking)
RUN npm run build

# Replace Dynatrace placeholder in built index.html (injected at CI time via env var)
ARG DYNATRACE_URL=""
RUN if [ -n "$DYNATRACE_URL" ]; then \
        sed -i "s|__DYNATRACE_URL__|$DYNATRACE_URL|g" /app/dist/index.html; \
    fi


# ── Stage 2: Serve ──────────────────────────────────────────────────
FROM nginx:1.27-alpine

# Remove default Nginx site
RUN rm -rf /usr/share/nginx/html/*

# Copy built React app
COPY --from=build /app/dist /usr/share/nginx/html

# Nginx config: SPA routing + security headers
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost/health.txt || exit 1
