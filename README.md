# Gemma LangChain FastAPI

A production-oriented FastAPI service with a dedicated LangChain agent layer backed by Google's hosted Gemma models through the Gemini API.

## Project Structure

```text
app/
  api/routes/        HTTP route modules
  core/              settings, logging, app lifecycle
  schemas/           request and response models
  services/          LangChain agent integration
tests/               API smoke tests
```

## Setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

If your machine only has Python 3.14, install Python 3.12 first. The Dockerfile already uses Python 3.12 for production.

Add your key to `.env`:

```env
GOOGLE_API_KEY=your_google_ai_studio_api_key
PEXELS_API_KEY=your_pexels_api_key
PIXABAY_API_KEY=your_pixabay_api_key
UNSPLASH_ACCESS_KEY=your_unsplash_access_key
```

Run locally:

```powershell
uvicorn app.main:app --reload
```

Open:

- API docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/health

## Chat Endpoint

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/api/v1/chat `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"message":"Plan a 3 day trip to Goa under 15000 INR."}'
```

Ask for destination media:

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/api/v1/chat `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"message":"Find photos and videos of Bali for a travel video."}'
```

The agent has one LangChain tool per provider:

- `search_pexels_place_media`: photos and videos from Pexels.
- `search_pixabay_place_media`: photos and videos from Pixabay.
- `search_unsplash_place_photos`: high-quality photos from Unsplash.

## Production

Docker:

```powershell
docker compose up --build
```

Linux process manager:

```bash
gunicorn app.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 2 \
  --bind 0.0.0.0:8000
```
