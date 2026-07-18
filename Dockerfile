# ---- builder: install deps into an isolated venv ----
FROM python:3.12-slim AS builder

WORKDIR /build

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ---- runtime: lean image, no build tools ----
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/venv/bin:$PATH"

WORKDIR /app

# Fonts for caption/title rendering (Latin via DejaVu/Noto, Indic via Noto).
# Without these, Pillow falls back to a tiny bitmap font and captions look broken.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

# Pull the pre-built venv from builder — no pip in this stage
COPY --from=builder /venv /venv

RUN addgroup --system app && adduser --system --ingroup app app

COPY app ./app

# Copy local data directory (background music, transition sounds, etc.)
COPY data /data
RUN mkdir -p /data \
    && chown -R app:app /data \
    && chmod -R 775 /data

# Symlink so relative data/... paths in code resolve correctly
RUN rm -rf /app/data || true \
    && ln -s /data /app/data

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

