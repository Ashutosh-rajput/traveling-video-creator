# Voyageur AI Studio - Professional Travel Vlog Engine

Voyageur AI Studio is a premium web application and backend engine that dynamically generates rich travel guide videos. Driven by **Gemma-4 Agents** on the backend and styled with a state-of-the-art **glassmorphism web UI** on the frontend, it integrates script generation, travel media curation (from Pexels, Pixabay, Unsplash), custom Sarvam AI Bulbul v3 TTS voiceover generation, and high-fidelity video rendering with transitions and custom subtitles.

---

## 🚀 Key Features

* **Gemma-4 Powered Planner**: Formulates high-quality script segments and curates local travel assets dynamically.
* **Sarvam AI Bulbul v3 TTS Voiceover**: High-performance text-to-speech engine supporting local language accents and voice speakers (e.g. Shubh).
* **Multi-Source Curation**: Automatically searches and gathers high-resolution images/videos from Pexels, Pixabay, and Unsplash.
* **Premium Video Rendering**: Smooth transitions (fade, slide, zoom), high-fidelity background music mood compilation, and audio-synchronization.
* **Custom Animated Subtitles**: Subtitle overlay system featuring dynamic proper noun/keyword highlighting, custom fonts, sizes, strokes, and drop-shadows.
* **Interactive Media Gallery Board**: Fully interactive frontend showcase supporting visual hover transitions, immediate lightbox triggers, and single-click source download options.

---

## 📂 Project Structure

```text
├── app/                      # Backend API & Engines
│   ├── api/routes/           # HTTP route modules (chat, status endpoints)
│   ├── core/                 # App lifecycle configurations, logging, setting schemas
│   ├── schemas/              # Pydantic request and response models
│   └── services/             # Core engines: video rendering, TTS audio, agent tools
├── frontend/                 # React UI Client
│   ├── src/                  # React source components and styles
│   └── vite.config.js        # Vite build configuration
├── tests/                    # Backend smoke/unit tests
├── data/                     # Local data (music, temporary outputs, transition sounds)
├── requirements.txt          # Python dependencies
└── .env                      # Environment variable configurations
```

---

## 🛠️ Environment Configuration (`.env`)

Create a `.env` file in the root directory (based on `.env.example`):

```env
APP_NAME="Gemma LangChain FastAPI"
APP_ENV=local
DEBUG=true
API_V1_PREFIX=/api/v1

# Gemini API Key (Google AI Studio)
GOOGLE_API_KEY=your_google_ai_studio_api_key
GEMMA_MODEL=gemma-4-31b-it

# Media Provider API keys (optional but recommended for curation tools)
PEXELS_API_KEY=your_pexels_api_key
PIXABAY_API_KEY=your_pixabay_api_key
UNSPLASH_ACCESS_KEY=your_unsplash_access_key

# TTS Voice Settings (Sarvam AI)
SARVAM_API_KEY=your_sarvam_api_key
SARVAM_LANG=en-IN
SARVAM_SPEAKER=shubh
SARVAM_PACE=1.2
SARVAM_SAMPLE_RATE=24000
SARVAM_MODEL=bulbul:v3

# Active Caption Subtitle Theme Selection:
# Option choices: "Neon Yellow (Default)", "Cyberpunk Pink", "Emerald Green", "Simple White", "Royal Gold", "Retro Orange"
ACTIVE_CAPTION_THEME="Neon Yellow (Default)"
```

---

## 🎨 Subtitle Font & Theme Styles

You can customize the appearance of the subtitles in the video. The settings are parsed dynamically from the `.env` variable `ACTIVE_CAPTION_THEME`. 

To configure/modify individual themes, edit the `CAPTION_THEMES` dictionary inside [app/services/video.py](file:///c:/Users/ASHUTOSH/OneDrive/Documents/traveling%20vedio/app/services/video.py):
* **`font_family`**: Choose from `"Segoe UI"`, `"Arial"`, `"Trebuchet MS"`, `"Georgia"`, `"Impact"`, or `"Comic Sans"`.
* **`font_size`**: Change the text size.
* **`base_color` / `highlight_color`**: Configure text colors using RGBA tuples.
* **`stroke_width` / `stroke_color`**: Configure outline thickness and color.
* **`shadow_offset` / `shadow_color`**: Customize drop shadow to ensure maximum readability over video footage.

---

## 💻 Local Setup & Development

### 1. Backend Service
Make sure you have python 3.12+ installed.

```powershell
# Create & Activate Virtual Environment
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install Dependencies
pip install -r requirements-dev.txt

# Run Dev Server
uvicorn app.main:app --reload
```

* API Docs: http://127.0.0.1:8000/docs
* Health Check: http://127.0.0.1:8000/health

### 2. Frontend client

```powershell
cd frontend
npm install

# Run Development Server
npm run dev

# Build Production Client
npm run build
```

### Connect your personal Google Drive

1. In Google Cloud Console, create an OAuth 2.0 Web application client and add `http://localhost:8000/api/v1/login/google/callback` as an authorized redirect URI.
2. Set `GDRIVE_CLIENT_ID` and `GDRIVE_CLIENT_SECRET` in `.env`.
3. Start the backend, then select **Connect Drive** in the video controls (or visit `http://localhost:8000/api/v1/login/google`). Approve access with your personal Google account.

The callback saves `GDRIVE_REFRESH_TOKEN` to the local `.env`; subsequent uploads use it automatically. Keep `.env` private.

---

## 🧪 Testing

Run python tests using `pytest`:

```powershell
pytest
```

---

## 🐋 Production Deployment (Docker)

To run the full stack containerized:

```powershell
docker compose up --build
```
