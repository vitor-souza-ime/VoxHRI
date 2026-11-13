"""Produce 10 figures using recorded (never simulated) conversational data.

Usage:
    py charts.py --csv results/sessions/SESSION/interactions.csv --out results/sessions/SESSION/figures
"""
import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parent


def read_rows(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def num(row, key):
    try:
        s = row.get(key, "")
        value = float(s)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def is_true(value):
    return str(value).strip().lower() in ("true", "1", "yes")


def qtile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    i = (len(ordered) - 1) * p
    bottom = int(i)
    upper = min(bottom+1, len(ordered)-1)
    return ordered[bottom]*(1-(i-bottom)) + ordered[upper]*(i-bottom)


def describe(values):
    if not values:
        return {"n": 0, "mean": None, "median": None,
                "p90": None, "p95": None, "minimum": None, "maximum": None}
    return {"n": len(values), "mean": mean(values), "median": median(values),
            "p90": qtile(values, .9), "p95": qtile(values, .95),
            "minimum": min(values), "maximum": max(values)}


def measure(rows, field):
    return [n for row in rows if (n := num(row, field)) is not None]


def paired(rows, x, y):
    return [(a,b) for row in rows if (a := num(row, x)) is not None
            and (b := num(row, y)) is not None]


def generate(csv_path, out, study_only=False):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    raw_rows = read_rows(csv_path)
    raw_rows = [r for r in raw_rows if not is_true(r.get("is_demo"))]

    if not raw_rows:
        raise SystemExit("No matching REAL observations. Complete a robot conversation first.")

    rows = [r for r in raw_rows if is_true(r.get("success"))]
    out.mkdir(parents=True, exist_ok=True)
    stt_err_path = csv_path.parent / "stt_errors.csv"
    stt_errors = read_rows(stt_err_path)

    stats = {
        "source_csv": str(csv_path),
        "filter": "single recorded experimental session",
        "n_attempts": len(raw_rows), "n_successful_llm": len(rows),
        "n_llm_failures": len(raw_rows)-len(rows),
        "n_stt_failures_recorded_separately": len(stt_errors),
        "llm_request_success_rate": len(rows)/len(raw_rows),
        "unique_sessions": len(set(r.get("session_id", "") for r in raw_rows)),
        "model_ids": sorted(set(r.get("model", "") for r in raw_rows)),
        "providers": dict(Counter(r.get("provider", "") or "unknown" for r in rows)),
        "cautions": [
            "STT time includes waiting for speech, capturing utterance and online recognition.",
            "TTS time includes initialization and the complete spoken playback.",
            "TTFT is first nonempty text chunk, not first streaming event.",
            "Conversation time excludes any subsequent metadata request.",
            "Known cumulative cost ignores unknown-cost rows; do not treat as total charge.",
            "Transcript discrepancy includes speaker deviations, so it is not a pure ASR WER.",
            "Repeated turns within a session are not independent observations.",
        ],
    }
    fields = ["stt_s","llm_s","ttft_s","tts_s","interaction_s",
              "input_tokens","output_tokens","total_tokens","cost_usd","history_turns",
              "transcript_discrepancy"]
    stats["descriptive"] = {key: describe(measure(rows,key)) for key in fields}
    known_cost = measure(rows,"cost_usd")
    stats["known_cost_sum_usd"] = sum(known_cost) if known_cost else None
    stats["missing_cost_rows"] = len(rows)-len(known_cost)
    stats["successful_study_questions_per_repeat"] = dict(sorted(Counter(
        str(r.get("study_repeat", "")) for r in rows if r.get("study_repeat", "")
    ).items()))
    stats["successful_study_questions_per_category"] = dict(sorted(Counter(
        str(r.get("prompt_category", "")) for r in rows if r.get("prompt_category", "")
    ).items()))

    figure_info = []
    def init(title, ylabel=""):
        fig, ax = plt.subplots(figsize=(9, 5.3))
        ax.set_title(title)
        if ylabel:
            ax.set_ylabel(ylabel)
        ax.grid(alpha=0.18, axis="y")
        return fig, ax

    def save(fig, ax, filename, title, count, explanation, has_data):
        if not has_data:
            ax.clear()
            ax.axis("off")
            ax.text(.5, .5, "Data unavailable for this figure.\n"
                    "No missing measurements were estimated.",
                    ha="center", va="center", fontsize=13, transform=ax.transAxes)
            ax.set_title(title)
        fig.tight_layout()
        fig.savefig(out/filename, dpi=210)
        plt.close(fig)
        figure_info.append((filename, title, count, explanation,
                            "observed" if has_data else "missing_data"))

    # 01. Component duration distributions.
    title = "01. Measured conversational stage durations"
    fig, ax = init(title, "Elapsed time (s)")
    labels, values = [], []
    for name,key in (("Speech intake + STT", "stt_s"),
                     ("OpenRouter LLM", "llm_s"),
                     ("TTS + playback", "tts_s")):
        vals = measure(rows,key)
        if vals:
            labels.append(f"{name}\n(n={len(vals)})")
            values.append(vals)
    if values:
        ax.boxplot(values, tick_labels=labels, showfliers=True)
    save(fig,ax,"01_stage_durations.png",title,len(rows),
         "Component times are not processing-only; STT includes recording and TTS includes playback.",bool(values))

    # 02. LLM latency over real turn order.
    title = "02. Cloud LLM latency across successive requests"
    fig, ax = init(title, "OpenRouter roundtrip time (s)")
    points=[(i,num(row,"llm_s")) for i,row in enumerate(rows,1) if num(row,"llm_s") is not None]
    if points:
        ax.plot([x for x,y in points],[y for x,y in points], marker=".",linewidth=1)
        ax.set_xlabel("Successful request number (chronological)")
    save(fig,ax,"02_llm_latency_by_turn.png",title,len(points),
         "Chronological latency; sessions may differ in network and provider conditions.",bool(points))

    # 03. TTFT vs complete request.
    title="03. First visible token and complete response"
    fig,ax=init(title,"Elapsed time (s)")
    fig3pairs=[]
    for i,row in enumerate(rows,1):
        t1=num(row,"ttft_s"); t2=num(row,"llm_s")
        if t1 is not None and t2 is not None:
            fig3pairs.append((i,t1,t2))
    if fig3pairs:
        ax.plot([x[0] for x in fig3pairs],[x[1] for x in fig3pairs],
                marker=".",linewidth=1,label="TTFT (visible content)")
        ax.plot([x[0] for x in fig3pairs],[x[2] for x in fig3pairs],
                marker=".",linewidth=1,label="Complete LLM request")
        ax.legend()
        ax.set_xlabel("Successful request number")
    save(fig,ax,"03_ttft_vs_complete.png",title,len(fig3pairs),
         "TTFT and full request duration measured via streaming.",bool(fig3pairs))

    # 04. P50/P90/P95.
    title="04. Latency percentiles by component"
    fig,ax=init(title,"Seconds")
    series=[]
    for name,key in (("STT*","stt_s"),("LLM","llm_s"),("TTS*","tts_s")):
        vals=measure(rows,key)
        if vals:
            series.append((name, [qtile(vals,p) for p in (.5,.9,.95)]))
    if series:
        w=.22
        for i,perc in enumerate(("P50","P90","P95")):
            ax.bar([j+(i-1)*w for j in range(len(series))],
                   [v[i] for _,v in series],width=w,label=perc)
        ax.set_xticks(range(len(series)),[name for name,_ in series]);ax.legend()
        ax.text(.01,.98,"* STT includes listening; TTS includes playback",transform=ax.transAxes,
                va="top",fontsize=9)
    save(fig,ax,"04_latency_percentiles.png",title,len(rows),
         "P50 P90 P95 are descriptive empirical percentiles; * stages include audio I/O.",bool(series))

    # 05. Input output token use.
    title="05. OpenRouter token usage per conversational turn"
    fig,ax=init(title,"Tokens per request")
    present=False
    for key,label in (("input_tokens","Input (context included)"),
                      ("output_tokens","Output")):
        points=[(i,num(row,key)) for i,row in enumerate(rows,1) if num(row,key) is not None]
        if points:
            ax.plot([x for x,y in points],[y for x,y in points],marker=".",linewidth=1,label=label)
            present=True
    if present:
        ax.legend();ax.set_xlabel("Successful request number")
    save(fig,ax,"05_tokens_by_turn.png",title,len(rows),
         "Input tokens include system prompt and the retained conversation window.",present)

    # 06. Output tokens vs latency.
    title="06. Generated tokens versus cloud response time"
    fig,ax=init(title,"OpenRouter request time (s)")
    pairs=paired(rows,"output_tokens","llm_s")
    if pairs:
        ax.scatter([x for x,y in pairs],[y for x,y in pairs],alpha=.7)
        ax.set_xlabel("Output tokens")
    save(fig,ax,"06_output_tokens_vs_llm_time.png",title,len(pairs),
         "Association, not a causal result: provider, load and network also affect time.",bool(pairs))

    # 07. History size and prompt tokens.
    title="07. Retained dialogue turns versus prompt tokens"
    fig,ax=init(title,"Input tokens")
    pairs=paired(rows,"history_turns","input_tokens")
    if pairs:
        ax.scatter([x for x,y in pairs],[y for x,y in pairs],alpha=.48)
        ax.set_xlabel("Prior conversation turns retained")
        ax.set_xticks(sorted(set(int(x) for x,y in pairs)))
    save(fig,ax,"07_context_vs_input_tokens.png",title,len(pairs),
         "Context is capped by HISTORY_PAIRS; token count also depends on content length.",bool(pairs))

    # 08. Spoken reply length and TTS playback time.
    title="08. Spoken response length versus playback duration"
    fig,ax=init(title,"TTS initialization + playback (s)")
    pairs=paired(rows,"output_words","tts_s")
    if pairs:
        ax.scatter([x for x,y in pairs],[y for x,y in pairs],alpha=.7)
        ax.set_xlabel("Response length (words)")
    save(fig,ax,"08_words_vs_tts_time.png",title,len(pairs),
         "Applies to voice runs; typing-only CLI requests may have missing TTS.",bool(pairs))

    # 09. Cost accounting without filling missing values.
    title="09. Accumulated reported API cost (known entries only)"
    fig,ax=init(title,"Known cumulative USD")
    current=0.0; known=[]
    for i,row in enumerate(rows,1):
        value=num(row,"cost_usd")
        if value is not None:
            current+=value;known.append((i,current))
    if known:
        ax.step([x for x,y in known],[y for x,y in known],where="post")
        ax.set_xlabel("Successful request number")
        ax.text(.01,.96,f"Missing price records: {len(rows)-len(known)}",
                va="top",transform=ax.transAxes,fontsize=9)
    save(fig,ax,"09_known_cumulative_cost.png",title,len(known),
         "A subtotal of records with reported prices, not a statement of actual total bill.",bool(known))

    # 10. Different failure types are *counts*, not one rate denominator.
    title="10. Reliability: observed successful requests and failures"
    fig,ax=init(title,"Count of events")
    vals=[len(rows),len(raw_rows)-len(rows),len(stt_errors)]
    labels=["LLM success","LLM failure","STT error* (separate)"]
    ax.bar(labels,vals)
    for i,v in enumerate(vals):
        ax.text(i,v+max(vals+[1])*.02,str(v),ha="center",fontsize=11)
    ax.set_ylim(0,max(vals+[1])*1.15+1)
    ax.tick_params(axis="x",labelsize=9)
    ax.text(.01,.97,"* STT errors are not API attempts; denominators differ",
            transform=ax.transAxes,va="top",fontsize=9)
    save(fig,ax,"10_reliability_event_counts.png",title,len(raw_rows),
         "Successful API attempts, unsuccessful API attempts, and separate ASR failures.",True)

    # Output transparent figure catalogue, usable as starting point for paper captions.
    with (out/"figure_index.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.writer(f);w.writerow(("figure_filename","title","n","interpretation","status"));w.writerows(figure_info)
    with (out/"descriptive_statistics.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.writer(f)
        w.writerow(("metric","n","mean","median","p90","p95","minimum","maximum"))
        for metric,des in stats["descriptive"].items():
            w.writerow((metric,des["n"],des["mean"],des["median"],des["p90"],
                        des["p95"],des["minimum"],des["maximum"]))
    (out/"summary.json").write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding="utf-8")
    print(f"Created {len(figure_info)} figures in: {out.resolve()}")
    print(f"Real API attempts: {len(raw_rows)} | successful: {len(rows)} | STT errors: {len(stt_errors)}")
    print(f"Known cost rows: {len(known)} / {len(rows)}")
    if len(rows) < 30:
        print("NOTICE: Less than 30 successful scripted turns; mark session as incomplete.")
    return stats


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--csv",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)

    args=ap.parse_args()
    return generate(args.csv,args.out)


if __name__=="__main__":
    main()
