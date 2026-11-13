"""Configuration: paste your OpenRouter key ONLY on the marked line."""
import os

# ============== EDIT THIS SINGLE CONSTANT ==================
API_KEY = ""  # Paste your OpenRouter API key between quotes.
# ===========================================================
OPENROUTER_API_KEY = API_KEY.strip() or os.getenv("OPENROUTER_API_KEY", "").strip()
MODEL = "nvidia/nemotron-3-super-120b-a12b"  # Fixed single LLM: NVIDIA Nemotron 3 Super 120B.
OPENROUTER_URL = "https://openrouter.ai/api/v1"
TEMPERATURE = 0.5
MAX_OUTPUT_TOKENS = 130
HISTORY_PAIRS = 6
REQUEST_TIMEOUT_S = 100
ENABLE_METADATA_LOOKUP = True
STT_LANGUAGE = "en-US"
STT_LISTEN_TIMEOUT_S = 5
STT_PHRASE_LIMIT_S = 12
TTS_RATE = 165
TTS_PREFERRED_VOICES = ("zira", "david", "english", "en-us", "en-gb", "us", "uk")
AUTO_ROTATE_AVATAR = True
SYSTEM_PROMPT = (
    "You are an approachable educational robot having a spoken conversation in English. "
    "Always reply naturally in English, using one to three concise sentences. "
    "Aim for under 45 words when possible, but respond fully when necessary. "
    "Remember relevant context from previous turns. Avoid Markdown, bullet lists, "
    "emoji, citations, and reasoning traces because the response will be spoken aloud. "
    "If you are uncertain, say so. You have no camera; never claim to see the surroundings."
)
