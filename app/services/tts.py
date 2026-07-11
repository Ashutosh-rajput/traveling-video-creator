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

def transliterate_hinglish_to_devanagari(text: str) -> str:
    """Use Gemini to transliterate Hinglish text (Hindi in English letters) into Devanagari Hindi characters."""
    from langchain_google_genai import ChatGoogleGenerativeAI
    import logging
    
    logger = logging.getLogger(__name__)
    logger.info(f"[Transliterate] Transliterating Hinglish to Devanagari: '{text}'")
    try:
        llm = ChatGoogleGenerativeAI(
            model=settings.gemma_model,
            google_api_key=settings.google_api_key,
            temperature=0.0,
            timeout=30,
        )
        prompt = (
            "You are an expert translator and transliterator.\n"
            "Your task is to convert Hinglish text (Hindi written in the English/Latin alphabet, e.g. 'namaskar dosto, swagat hai') "
            "directly into Devanagari Hindi script (e.g. 'नमस्कार दोस्तों, स्वागत है').\n"
            "CRITICAL RULES:\n"
            "1. Output ONLY the Devanagari script transliteration. Do NOT add any explanations, notes, metadata, or extra words.\n"
            "2. Keep the exact meaning, tone, and spoken narration words identical. Only convert the characters to Hindi script.\n"
            "3. Do NOT translate English names of attractions/places if they appear. Transliterate them into Hindi phonetics (e.g. 'Bangalore Palace' to 'बैंगलोर पैलेस').\n"
            "Text to transliterate:\n"
            f"{text}"
        )
        res = llm.invoke(prompt)
        content_val = res.content
        if isinstance(content_val, list):
            parts = []
            for chunk in content_val:
                if isinstance(chunk, dict) and "text" in chunk:
                    parts.append(chunk["text"])
                elif isinstance(chunk, str):
                    parts.append(chunk)
            transliterated = "".join(parts).strip()
        else:
            transliterated = str(content_val).strip()
        logger.info(f"[Transliterate] Result: '{transliterated}'")
        return transliterated
    except Exception as e:
        logger.error(f"[Transliterate] Error using Gemini for transliteration: {e}. Falling back to original text.")
        return text

def generate_tts(text: str, speaker: str | None = None, language_code: str | None = None) -> bytes:
    if not settings.sarvam_api_key or settings.sarvam_api_key == "YOUR_SARVAM_API_KEY":
        raise ValueError("SARVAM_API_KEY is not configured in .env.")

    # Use overrides if provided, otherwise default to config settings
    target_speaker = speaker.lower() if speaker else settings.sarvam_speaker
    target_lang = language_code if language_code else settings.sarvam_lang

    # Handle Hinglish translation/transliteration for audio generation
    if target_lang == "hi-Latn":
        text = transliterate_hinglish_to_devanagari(text)
        target_lang = "hi-IN" # Sarvam AI speaks in Hindi for the audio

    cleaned_text = clean_text_for_tts(text)
    if not cleaned_text:
        cleaned_text = text

    client = SarvamAI(api_subscription_key=settings.sarvam_api_key)
    
    audio_response = client.text_to_speech.convert(
        text=cleaned_text,
        model=settings.sarvam_model,
        target_language_code=target_lang,
        speaker=target_speaker,
        pace=settings.sarvam_pace,
        speech_sample_rate=settings.sarvam_sample_rate,
    )
    
    combined_audio = "".join(audio_response.audios)
    return base64.b64decode(combined_audio)
