"""Single 30-turn live English speech session; S starts collection, F finalizes CSV and figures.

Running without S does NOT call the API and does NOT record research data.
"""
import argparse
import json
import queue
import random
import shutil
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import config
from audio import listen_english, speak_english
from openrouter_client import OpenRouterClient, demo_reply
from storage import (RESULTS, FIELDS, STT_FIELDS, append_csv_at, create_csv,
                     session_summary, timestamp)
from study_protocol import load_questions, transcript_discrepancy

ROOT = Path(__file__).resolve().parent
AVATARS = ("atlas", "nova", "orbit")
AVATAR_MARKER = ROOT / ".last_avatar.json"


def rotate_avatar():
    try:
        previous = json.loads(AVATAR_MARKER.read_text(encoding="utf-8"))["avatar"]
        nxt = AVATARS[(AVATARS.index(previous) + 1) % len(AVATARS)]
    except (OSError, ValueError, KeyError, TypeError):
        nxt = random.choice(AVATARS)
    save_avatar(nxt)
    return nxt


def save_avatar(name):
    if name not in AVATARS:
        raise ValueError("Invalid avatar")
    try:
        AVATAR_MARKER.write_text(json.dumps({"avatar": name}), encoding="utf-8")
    except OSError:
        pass


class Robot:
    def __init__(self, demo=False, microphone=True, tts=True):
        self.demo = demo
        self.mic_requested = microphone
        self.mic = False  # OFF until the user explicitly starts data collection.
        self.tts = tts
        self.running = True
        self.busy = False
        self.speaking = False
        self.active = False
        self.finalizing = False
        self.finish_requested = False
        self.completed = False
        self.avatar = rotate_avatar() if config.AUTO_ROTATE_AVATAR else AVATARS[0]
        self.client = OpenRouterClient()
        self.study_questions = load_questions()
        self.study_index = 0
        self.history = []
        self.rows = []
        self.turn = 0
        self.stt_errors = 0
        self.queue = queue.Queue()
        self.question = "Press S to start the 30-question study."
        self.answer = "Hello! I'm ready to speak with you in English."
        self.state = "Waiting to start (S)"
        self.last_error = ""
        self.latest = None
        self.session_id = ""
        self.folder = None
        self.csv_path = None
        self.stt_path = None
        self.completed_at = ""
        self.finish_reason = ""
        self.worker = threading.Thread(target=self.worker_loop, daemon=True)

    def start(self):
        self.worker.start()

    def current_study_item(self):
        if not self.active or self.study_index >= len(self.study_questions):
            return None
        return self.study_questions[self.study_index]

    def show_next_question(self):
        item = self.current_study_item()
        if item:
            print(f"\nQUESTION {self.study_index+1}/30 [{item['id']}]\nSAY: {item['prompt']}\n")

    def select_avatar(self, name):
        self.avatar = name
        save_avatar(name)

    def next_avatar(self):
        self.select_avatar(AVATARS[(AVATARS.index(self.avatar)+1) % len(AVATARS)])

    def begin_session(self):
        """Explicit collection start; creates a NEW, never-overwritten data folder."""
        if self.active or self.finalizing or self.busy:
            return False
        self.completed = False
        self.finish_requested = False
        self.finish_reason = ""
        self.completed_at = ""
        self.session_id = uuid.uuid4().hex[:10]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        parent = RESULTS / ("demos" if self.demo else "sessions")
        self.folder = parent / f"{stamp}_{self.session_id}"
        self.folder.mkdir(parents=True, exist_ok=False)
        self.csv_path = create_csv(self.folder / "interactions.csv", FIELDS)
        self.stt_path = create_csv(self.folder / "stt_errors.csv", STT_FIELDS)
        shutil.copy2(ROOT / "protocol" / "questions.csv", self.folder / "questions.csv")
        self.history, self.rows = [], []
        self.queue = queue.Queue()
        self.study_index = self.turn = self.stt_errors = 0
        self.latest = None
        self.question = "Read the displayed question in English."
        self.answer = "The recording has started."
        self.last_error = ""
        self.active = True
        self.mic = self.mic_requested
        self.state = "Recording: please ask question 1"
        self.save_manifest("running")
        print(f"\n=== SESSION STARTED ===\nCSV: {self.csv_path}\n")
        self.show_next_question()
        return True

    def save_manifest(self, status):
        if not self.folder:
            return
        data = {
            "session_id": self.session_id, "status": status,
            "is_demo": self.demo, "model": config.MODEL,
            "api_key": "NOT EXPORTED", "temperature": config.TEMPERATURE,
            "max_output_tokens": config.MAX_OUTPUT_TOKENS,
            "history_pairs": config.HISTORY_PAIRS,
            "tts_rate": config.TTS_RATE,
            "stt_language": config.STT_LANGUAGE,
            "microphone_enabled_at_start": self.mic_requested,
            "tts_enabled": self.tts,
            "avatar_at_end_or_start": self.avatar,
            "python_version": sys.version.split()[0],
            "os_platform": sys.platform,
            "expected_questions": len(self.study_questions),
            "successful_questions": self.study_index,
            "api_attempts": len(self.rows),
            "recorded_stt_failures": self.stt_errors,
            "last_update_utc": timestamp(),
            "end_reason": self.finish_reason,
            "completed_at_utc": self.completed_at,
            "notes": [
                "Single 30-turn dialogue, not 30 independent experimental replicates.",
                "STT duration includes waiting/audio capture; TTS duration includes playback.",
                "Avatar is a screen animation and does not indicate a physical robot.",
                "Any quality scores must be assigned by human evaluators.",
            ],
        }
        (self.folder / "session_config.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def request_finish(self, reason="manual"):
        if not self.active or self.finalizing:
            return False
        self.finish_requested = True
        self.finish_reason = reason
        self.mic = False
        self.state = "Finishing: saving CSV and figures..."
        return True

    def finish_session(self):
        """Runs on the worker after the active request completes. Does not overwrite other sessions."""
        if not self.active or self.finalizing:
            return False
        self.finalizing = True
        self.mic = False
        self.state = "Finalizing data and creating graphs..."
        self.completed_at = timestamp()
        complete = self.study_index == len(self.study_questions)
        self.completed = complete
        self.active = False
        self.finish_reason = self.finish_reason or ("completed_30" if complete else "manual")
        status = "complete" if complete else "incomplete"
        self.save_manifest(status)
        summary = session_summary(self.rows)
        summary.update({"session_id": self.session_id, "status": status,
                        "expected_successful": 30, "recorded_stt_errors": self.stt_errors,
                        "model": config.MODEL, "csv_file": str(self.csv_path)})
        (self.folder / "session_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        if not self.demo:
            try:
                from human_evaluation import generate as create_human_review
                create_human_review(self.csv_path, self.folder / "human_evaluation.csv")
            except Exception as exc:
                print("Human review CSV could not be generated:", exc)
            if self.rows:
                try:
                    from charts import generate
                    generate(self.csv_path, self.folder / "figures")
                except (Exception, SystemExit) as exc:
                    print("Graphs not generated; the CSV was saved. Cause:", repr(exc))
                    (self.folder / "CHART_GENERATION_ERROR.txt").write_text(
                        repr(exc) + "\nUse py charts.py --csv ... --out ...\n", encoding="utf-8")
        self.finalizing = False
        self.finish_requested = False
        self.state = f"Session {status.upper()} — {self.study_index}/30 questions saved"
        self.answer = f"Session finished. Saved {self.study_index} successful answers."
        print(f"\n=== SESSION {status.upper()} ===\nSuccesses: {self.study_index}/30"
              f"\nFolder: {self.folder}\nCSV: {self.csv_path}\n")
        return True

    def submit(self, text):
        if not self.active or self.finish_requested or self.busy:
            self.state = "Start a study (S), or wait for the current answer."
            return False
        text = text.strip()
        if not text:
            return False
        self.mic = False  # Avoid competing typed questions with an in-flight microphone capture.
        self.queue.put(("typed", text, None))
        self.state = "Typed question queued"
        return True

    def worker_loop(self):
        while self.running:
            if self.active and (self.finish_requested or self.study_index >= 30) and not self.busy:
                self.finish_session()
                continue
            if not self.active or self.finalizing:
                time.sleep(.1)
                continue
            try:
                mode, question, stt_s = self.queue.get_nowait()
            except queue.Empty:
                if not self.mic:
                    time.sleep(.1)
                    continue
                self.state = "Listening in English..."
                question, stt_s, error = listen_english()
                if not self.mic or self.finish_requested:
                    continue
                if error:
                    if not error.startswith("WaitTimeoutError"):
                        self.stt_errors += 1
                        self.last_error = "Speech: " + error
                        append_csv_at(self.stt_path, {
                            "timestamp_utc": timestamp(), "session_id": self.session_id,
                            "prompt_id": self.current_study_item()["id"] if self.current_study_item() else "",
                            "error": error, "stt_s": stt_s,
                        }, STT_FIELDS)
                        if error.startswith(("ModuleNotFoundError", "OSError", "AttributeError")):
                            self.mic = False
                            self.state = "Microphone unavailable. Press T to type."
                        else:
                            self.state = "Speech not recognized; repeat question."
                    continue
                mode = "microphone"
            if self.finish_requested or not self.active or not question:
                continue
            if question.strip().lower() in ("exit", "quit", "report"):
                self.state = "Use F to end, R for report; scripted questions only."
                continue
            self.process(mode, question, stt_s)

    def process(self, mode, question, stt_s=None):
        """Processes one live or simulated attempt, and commits it directly to CSV."""
        if not self.active or self.finalizing or self.finish_requested:
            return None
        self.busy = True
        try:
            self.state = "Contacting OpenRouter..." if not self.demo else "Simulated (not scientific data)"
            self.question = question
            self.last_error = ""
            self.turn += 1
            used_history = len(self.history) // 2
            item = self.current_study_item()
            avatar = self.avatar
            start = time.perf_counter()
            response = demo_reply(question) if self.demo else self.client.ask(question, self.history)
            if response.success:
                self.answer = response.reply
                # Simulated answer is NEVER reused as conversation history for scientific trials.
                if not self.demo:
                    self.history.extend((
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": response.reply},
                    ))
                    self.history = self.history[-2 * config.HISTORY_PAIRS:]
            else:
                self.answer = "I'm sorry. I could not contact the language model."
                self.last_error = response.error
            tts_s, tts_error = None, ""
            if self.tts:
                self.state = "Robot speaking..."
                tts_s, tts_error = speak_english(
                    self.answer, on_start=lambda: setattr(self, "speaking", True),
                    on_end=lambda: setattr(self, "speaking", False))
            interaction_s = time.perf_counter()-start+(stt_s or 0)
            if tts_error:
                self.last_error = "TTS: " + tts_error
            if not self.demo and config.ENABLE_METADATA_LOOKUP and response.success:
                self.client.enrich_metadata(response)
            row = {
                "timestamp_utc": timestamp(), "session_id": self.session_id,
                "turn": self.turn, "avatar": avatar, "input_mode": mode,
                "study_repeat": 1, "prompt_id": item["id"] if item else "",
                "prompt_block": item["block"] if item else "",
                "prompt_category": item["category"] if item else "",
                "reference_prompt": item["prompt"] if item else "",
                "transcript_discrepancy": (transcript_discrepancy(item["prompt"], question)
                                           if item and mode == "microphone" else None),
                "model": config.MODEL, "model_reported": response.model_reported,
                "provider": response.provider, "input_text": question,
                "output_text": response.reply, "input_words": len(question.split()),
                "output_words": len(response.reply.split()), "history_turns": used_history,
                "stt_s": stt_s, "llm_s": response.llm_s, "ttft_s": response.ttft_s,
                "tts_s": tts_s, "interaction_s": interaction_s,
                "input_tokens": response.input_tokens, "output_tokens": response.output_tokens,
                "total_tokens": response.total_tokens, "cost_usd": response.cost_usd,
                "metadata_s": response.metadata_s, "success": response.success,
                "http_status": response.http_status, "error": response.error,
                "tts_error": tts_error, "generation_id": response.generation_id,
                "is_demo": self.demo,
            }
            append_csv_at(self.csv_path, row)
            self.rows.append(row)
            self.latest = row
            if response.success:
                self.study_index += 1
                self.show_next_question()
            if self.study_index >= 30:
                self.request_finish(reason="completed_30")
            else:
                self.state = "Recording: next question" if response.success else "API failure: retry current question"
            self.save_manifest("running")
            print(f"\n[{self.study_index}/30; API attempt {self.turn}] User: {question}"
                  f"\nRobot: {self.answer}\nLLM={response.llm_s:.3f}s | "
                  f"TTFT={response.ttft_s} | STT={stt_s} | TTS={tts_s} | "
                  f"E2E={interaction_s:.3f}s | tokens={response.total_tokens} | "
                  f"cost={response.cost_usd}\nCSV: {self.csv_path}")
            return row
        finally:
            self.busy = False

    def report(self):
        print("\n=== CURRENT SESSION REPORT ===")
        for name, value in session_summary(self.rows).items():
            print(f"{name}: {value}")
        print("Prompts finished:", self.study_index, "/ 30")
        print("Recorded STT errors:", self.stt_errors)
        print("CSV:", self.csv_path or "Not started")
        print("================================\n")


def show_gui(robot):
    try:
        import pygame
    except ImportError:
        print("Pygame missing: py -m pip install -r requirements.txt")
        return 1
    pygame.init()
    W, H = 1150, 760
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("VoxHRI | Nemotron 120B")
    clock = pygame.time.Clock()
    font = {
        "title": pygame.font.SysFont("Segoe UI", 38, bold=True),
        "head": pygame.font.SysFont("Segoe UI", 22, bold=True),
        "body": pygame.font.SysFont("Segoe UI", 19),
        "small": pygame.font.SysFont("Segoe UI", 16),
        "tiny": pygame.font.SysFont("Consolas", 15),
    }
    images = {}
    for avatar in AVATARS:
        for mouth in ("open", "closed"):
            image_path = ROOT / "assets" / f"{avatar}_{mouth}.png"
            image = pygame.image.load(str(image_path)).convert_alpha()
            images[(avatar, mouth)] = pygame.transform.smoothscale(image, (585, 684))

    bg = pygame.Surface((W, H))
    c0, c1 = (9, 23, 47), (16, 39, 68)
    for y in range(H):
        p = y / (H-1)
        c = tuple(round(c0[i]*(1-p) + c1[i]*p) for i in range(3))
        pygame.draw.line(bg, c, (0, y), (W, y))
    for x in range(0, W, 42):
        pygame.draw.line(bg, (19, 45, 70), (x, 0), (x, H))
    for y in range(0, H, 42):
        pygame.draw.line(bg, (19, 45, 70), (0, y), (W, y))

    def print_at(value, x, y, style="body", color=(219, 237, 253)):
        screen.blit(font[style].render(str(value), True, color), (x, y))

    def panel(x, y, w, h):
        pygame.draw.rect(screen, (15, 37, 64), (x, y, w, h), border_radius=17)
        pygame.draw.rect(screen, (44, 90, 123), (x, y, w, h), 2, border_radius=17)

    def wrap(value, x, y, max_width, typ="body", max_lines=5, color=(234, 246, 255)):
        words = str(value).split()
        lines, line = [], ""
        for word in words:
            candidate = word if not line else line + " " + word
            if font[typ].size(candidate)[0] > max_width and line:
                lines.append(line); line = word
            else:
                line = candidate
        if line:
            lines.append(line)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            while lines[-1] and font[typ].size(lines[-1]+"...")[0] > max_width:
                lines[-1] = lines[-1][:-1]
            lines[-1] += "..."
        for i, line in enumerate(lines):
            print_at(line, x, y+i*(font[typ].get_linesize()+3), typ, color)

    robot.start()
    writing = False
    typed = ""
    exit_after_finish = False
    while robot.running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                exit_after_finish = True
                if robot.active:
                    robot.request_finish("window_closed")
                elif not robot.finalizing:
                    robot.running = False
                break
            if event.type != pygame.KEYDOWN:
                continue
            if event.key == pygame.K_ESCAPE:
                if writing:
                    writing, typed = False, ""
                else:
                    exit_after_finish = True
                    if robot.active:
                        robot.request_finish("exit_requested")
                    elif not robot.finalizing:
                        robot.running = False
            elif writing:
                if event.key == pygame.K_RETURN:
                    robot.submit(typed)
                    writing, typed = False, ""
                elif event.key == pygame.K_BACKSPACE:
                    typed = typed[:-1]
                elif event.unicode and event.unicode.isprintable() and len(typed)<450:
                    typed += event.unicode
            elif event.key == pygame.K_s:
                robot.begin_session()
            elif event.key == pygame.K_f:
                robot.request_finish()
            elif event.key == pygame.K_t:
                if robot.active and not robot.finish_requested:
                    robot.mic = False
                    writing = True
                    item = robot.current_study_item()
                    typed = item["prompt"] if item else ""
            elif event.key == pygame.K_v:
                if robot.active and not robot.finish_requested:
                    robot.mic = not robot.mic
                    robot.state = "Microphone ON" if robot.mic else "Microphone OFF"
            elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                robot.select_avatar(AVATARS[event.key-pygame.K_1])
            elif event.key == pygame.K_SPACE:
                robot.next_avatar()
            elif event.key == pygame.K_r:
                robot.report()
        if exit_after_finish and not robot.active and not robot.finalizing:
            robot.running = False
        screen.blit(bg, (0, 0))
        print_at("VoxHRI", 38, 24, "title", (117, 228, 255))
        print_at("", 159, 24, "title")
        print_at("VoxHRI  /  30 Recorded Interactions", 40, 78,
                 "small", (139, 177, 202))
        panel(32, 120, 555, 600)
        pygame.draw.ellipse(screen, (24, 58, 78), (97, 637, 418, 52))
        mouth = "open" if robot.speaking and int(time.monotonic()*6)%2==0 else "closed"
        screen.blit(images[(robot.avatar, mouth)], (16, 62))
        pygame.draw.rect(screen, (32, 88, 116), (53, 643, 512, 54), border_radius=17)
        print_at(f"AVATAR  {robot.avatar.upper()}", 73, 653, "head")
        print_at("SPACE or 1-3 to change", 328, 665, "small", (151, 202, 223))
        panel(611, 122, 506, 100)
        print_at("ONE MODEL", 632, 138, "tiny", (122, 186, 216))
        print_at("Nemotron 3 Ultra 120B ", 632, 164, "head")
        panel(611, 238, 506, 145)
        item = robot.current_study_item()
        if robot.active:
            print_at(f"RECORDING   |   QUESTION {robot.study_index+1}/30   |   "
                     f"API attempts {robot.turn}", 632, 253, "tiny", (133, 217, 237))
            wrap(item["prompt"] if item else "30 questions completed!",
                 632, 284, 457, typ="small", max_lines=4)
        elif robot.completed or robot.folder:
            print_at(f"SESSION FINISHED   |   {robot.study_index}/30 SAVED",632,253,"tiny",(133,217,237))
            wrap(f"Data saved at: {robot.folder}", 632, 284, 457, typ="small", max_lines=4)
        else:
            print_at("READY TO START", 632, 253, "tiny", (133,217,237))
            wrap("Press S to start recording your 30 English questions.",
                 632, 284, 457, typ="small", max_lines=4)
        panel(611, 399, 506, 210)
        print_at("ROBOT ANSWER", 632, 414, "tiny", (133, 217, 237))
        wrap(robot.answer, 632, 449, 455, max_lines=5)
        status_color = (111,240,192) if not (robot.busy or robot.finalizing) else (252,189,124)
        print_at("● " + robot.state[:53], 632, 619, "small", status_color)
        if robot.last_error:
            wrap("Error: " + robot.last_error, 632, 643, 466, "small", 2, (255,147,156))
        panel(611, 684, 506, 53)
        if writing:
            wrap("> " + typed + "_", 627, 700, 470, "small", 1)
        else:
            print_at("S start  ·  F finish  ·  T type  ·  V mic  ·  Esc quit", 627, 699,
                     "small", (160, 208, 228))
        if robot.latest and robot.latest["llm_s"] is not None:
            print_at(f"LLM {robot.latest['llm_s']:.2f}s   |   CSV saved", 615, 95,
                     "small", (171, 222, 225))
        state_text = "DEMO: NOT SCIENTIFIC DATA" if robot.demo else (
            "RECORDING" if robot.active else "NOT RECORDING")
        print_at(state_text, 835, 33, "small", (255,199,128) if robot.demo else (132,224,215))
        pygame.display.flip()
        clock.tick(40)
    pygame.quit()
    robot.report()
    return 0


def main():
    parser = argparse.ArgumentParser(description="Single-Nemotron 3 Super 120B 30-turn interactive English robot.")
    parser.add_argument("--demo", action="store_true", help="Offline GUI test; never scientific data")
    parser.add_argument("--no-mic", action="store_true", help="Enable typed questions with T; STT remains missing")
    parser.add_argument("--no-tts", action="store_true", help="Disable voice output; TTS remains missing")
    args = parser.parse_args()
    if not args.demo and not config.OPENROUTER_API_KEY:
        print('Fill API_KEY in config.py. For offline GUI: py main.py --demo --no-mic --no-tts')
        return 1
    robot = Robot(demo=args.demo, microphone=not args.no_mic, tts=not args.no_tts)
    return show_gui(robot)


if __name__ == "__main__":
    raise SystemExit(main())
