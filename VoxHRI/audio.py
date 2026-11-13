"""English recognition using microphone, and Windows-compatible pyttsx3 voice."""
import sys
import time
import config


def listen_english():
    """Returns (transcript, seconds, error). Captures recording AND online STT time."""
    t0 = time.perf_counter()
    try:
        import speech_recognition as sr
        rec = sr.Recognizer()
        rec.dynamic_energy_threshold = True
        rec.pause_threshold = 0.8
        with sr.Microphone() as mic:
            rec.adjust_for_ambient_noise(mic, duration=0.35)
            audio = rec.listen(mic, timeout=config.STT_LISTEN_TIMEOUT_S,
                               phrase_time_limit=config.STT_PHRASE_LIMIT_S)
        text = rec.recognize_google(audio, language=config.STT_LANGUAGE)
        return text.strip(), time.perf_counter()-t0, ""
    except Exception as exc:
        return "", time.perf_counter()-t0, f"{type(exc).__name__}: {str(exc)[:150]}"


def speak_english(text, on_start=None, on_end=None):
    """Returns (seconds, error). Duration includes engine setup + full playback."""
    t0 = time.perf_counter()
    com = None
    if sys.platform == "win32":
        try:
            import pythoncom
            pythoncom.CoInitialize()
            com = pythoncom
        except ImportError:
            pass
    if on_start:
        on_start()
    try:
        import pyttsx3
        engine = pyttsx3.init()
        for voice in engine.getProperty("voices") or []:
            text_voice = (voice.name + " " + voice.id).lower()
            if any(part in text_voice for part in config.TTS_PREFERRED_VOICES):
                engine.setProperty("voice", voice.id)
                break
        engine.setProperty("rate", config.TTS_RATE)
        engine.say(text)
        engine.runAndWait()
        engine.stop()
        return time.perf_counter()-t0, ""
    except Exception as exc:
        return time.perf_counter()-t0, f"{type(exc).__name__}: {str(exc)[:150]}"
    finally:
        if on_end:
            on_end()
        if com is not None:
            com.CoUninitialize()
