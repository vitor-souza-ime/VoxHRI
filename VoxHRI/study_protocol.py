"""Fixed 30-turn English study instrument; never submits prompts automatically."""
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QUESTIONS = ROOT / "protocol" / "questions.csv"


def load_questions():
    with QUESTIONS.open(newline="", encoding="utf-8-sig") as handle:
        result = list(csv.DictReader(handle))
    if len(result) != 30 or len({row["id"] for row in result}) != 30:
        raise ValueError("Study protocol must contain exactly 30 unique prompts")
    return result


def _tokens(text):
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", text.lower())


def transcript_discrepancy(reference, recognized):
    """Word edit distance / reference length; includes speaker deviations as well as ASR errors."""
    a, b = _tokens(reference), _tokens(recognized)
    if not a:
        return None
    d = list(range(len(b) + 1))
    for i, word in enumerate(a, 1):
        nxt = [i]
        for j, other in enumerate(b, 1):
            nxt.append(min(nxt[j-1]+1, d[j]+1, d[j-1]+(word != other)))
        d = nxt
    return round(d[-1]/len(a), 6)
