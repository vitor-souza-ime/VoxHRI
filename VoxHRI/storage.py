"""Incremental, isolated session CSV output; completed output is never overwritten."""
from datetime import datetime, timezone
from pathlib import Path
import csv
import statistics

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

FIELDS = [
    "timestamp_utc", "session_id", "turn", "avatar", "input_mode",
    "study_repeat", "prompt_id", "prompt_block", "prompt_category",
    "reference_prompt", "transcript_discrepancy", "model",
    "model_reported", "provider", "input_text", "output_text", "input_words",
    "output_words", "history_turns", "stt_s", "llm_s", "ttft_s", "tts_s",
    "interaction_s", "input_tokens", "output_tokens", "total_tokens", "cost_usd",
    "metadata_s", "success", "http_status", "error", "tts_error",
    "generation_id", "is_demo",
]

STT_FIELDS = ["timestamp_utc", "session_id", "prompt_id", "error", "stt_s"]

def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

def create_csv(path, fields=FIELDS):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=fields).writeheader()
    return path

def append_csv_at(path, row, fields=FIELDS):
    """Create if needed and append one fully committed CSV record immediately."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    first = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8-sig" if first else "utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if first:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in fields})
        f.flush()
    return path

def read_csv(path):
    path=Path(path)
    if not path.exists(): return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def session_summary(rows):
    valid = [r for r in rows if r.get("success") is True or str(r.get("success", "")).lower() == "true"]
    def med(key):
        vals = [float(r[key]) for r in valid if r.get(key) not in (None, "")]
        return round(statistics.median(vals), 3) if vals else None
    costs = [float(r["cost_usd"]) for r in rows if r.get("cost_usd") not in (None, "")]
    return {"attempts": len(rows), "successful": len(valid),
            "median_stt_s": med("stt_s"), "median_llm_s": med("llm_s"),
            "median_ttft_s": med("ttft_s"), "median_tts_s": med("tts_s"),
            "median_interaction_s": med("interaction_s"),
            "known_cost_usd": round(sum(costs), 8) if costs else None,
            "cost_observations": len(costs)}
