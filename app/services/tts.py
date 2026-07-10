import base64
import re
from sarvamai import SarvamAI
from app.core.config import settings

def clean_text_for_tts(text: str) -> str:
    # Remove [attraction: ...] markers first
    text = re.sub(r'\[attraction:\s*[^\]]*\]', '', text, flags=re.IGNORECASE)
    # Remove remaining text in square brackets: [...] (multiline support)
    text = re.sub(r'\[.*?\]', '', text, flags=re.DOTALL)
    # Remove text in parentheses: (...) (multiline support)
    text = re.sub(r'\(.*?\)', '', text, flags=re.DOTALL)
    # Remove quotation marks
    text = text.replace('"', '').replace('“', '').replace('”', '').replace("'", "").replace("‘", "").replace("’", "")
    # Normalize whitespace and newlines
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def generate_tts(text: str) -> bytes:
    if not settings.sarvam_api_key or settings.sarvam_api_key == "YOUR_SARVAM_API_KEY":
        raise ValueError("SARVAM_API_KEY is not configured in .env.")

    cleaned_text = clean_text_for_tts(text)
    if not cleaned_text:
        cleaned_text = text

    client = SarvamAI(api_subscription_key=settings.sarvam_api_key)
    
    audio_response = client.text_to_speech.convert(
        text=cleaned_text,
        model=settings.sarvam_model,
        target_language_code=settings.sarvam_lang,
        speaker=settings.sarvam_speaker,
        pace=settings.sarvam_pace,
        speech_sample_rate=settings.sarvam_sample_rate,
    )
    
    combined_audio = "".join(audio_response.audios)
    return base64.b64decode(combined_audio)
