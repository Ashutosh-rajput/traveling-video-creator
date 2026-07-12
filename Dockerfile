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
# This ensures the container has those directories available at runtime.
COPY data /data
RUN chown -R app:app /data \
    && chmod -R 775 /data

# Expose data as a volume so it can be mounted at runtime if desired
VOLUME ["/data"]

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

