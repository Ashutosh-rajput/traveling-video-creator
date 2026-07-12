FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Copy local data directory into image (background music, transition_sounds, etc.)
# Place it under /app/data so application relative paths (data/...) work.
COPY data /data
# ensure /data exists and is writable by the app user
RUN mkdir -p /data \
    && chown -R app:app /data \
    && chmod -R 775 /data

# Make a symlink so code using relative `data/...` paths continues to work
RUN rm -rf /app/data || true \
    && ln -s /data /app/data



USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

