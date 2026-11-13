"""Create a human scoring form for a single recorded experimental session."""
import argparse
import csv
from pathlib import Path
from charts import read_rows, is_true
FIELDS = ["session_id", "turn", "prompt_id", "prompt_category", "input_text", "output_text",
          "relevance_1_5", "factual_accuracy_1_5", "context_consistency_1_5",
          "english_fluency_1_5", "unsupported_claim_0_1", "reviewer_notes"]

def generate(source, destination):
    observations=[r for r in read_rows(source) if is_true(r.get("success")) and not is_true(r.get("is_demo"))]
    destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader()
        for row in observations:
            w.writerow({key:row.get(key,"") for key in FIELDS})
    print(f"Human evaluation sheet: {destination} ({len(observations)} rows).")
    return len(observations)

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--csv",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args()
    generate(args.csv,args.out)
