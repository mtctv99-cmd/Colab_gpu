# ── Stage 1: Build Next.js frontend ────────────────────────
FROM node:22-alpine AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# ── Stage 2: Python backend + bundled frontend ─────────────
FROM python:3.12-slim

WORKDIR /app

# Install system deps + cloudflared
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared \
    && chmod +x /usr/local/bin/cloudflared

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY colab/ colab/
COPY run.py .

# Copy frontend standalone build
COPY --from=frontend-builder /build/.next/standalone /app/frontend/.next/standalone
COPY --from=frontend-builder /build/.next/static /app/frontend/.next/standalone/.next/static
COPY --from=frontend-builder /build/public /app/frontend/.next/standalone/public

VOLUME /app/data

ENV HOST=0.0.0.0
ENV PORT=8090
EXPOSE 8090

CMD ["python3", "run.py"]
