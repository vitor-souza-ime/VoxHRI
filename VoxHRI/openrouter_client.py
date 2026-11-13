"""Small OpenRouter streaming client with real TTFT, token usage, and cost fields."""
from dataclasses import dataclass, asdict
import json
import time
from typing import Optional

import requests
import config


@dataclass
class Response:
    success: bool = False
    reply: str = ""
    model_requested: str = ""
    model_reported: str = ""
    provider: str = ""
    generation_id: str = ""
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    llm_s: Optional[float] = None
    ttft_s: Optional[float] = None
    metadata_s: Optional[float] = None
    http_status: Optional[int] = None
    error: str = ""
    demo: bool = False

    def to_dict(self):
        return asdict(self)


def _str_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(part.get("text", "")) for part in content
                       if isinstance(part, dict) and part.get("type") == "text")
    return ""


def _usage(r, obj):
    if not isinstance(obj, dict):
        return
    r.input_tokens = obj.get("prompt_tokens", r.input_tokens)
    r.output_tokens = obj.get("completion_tokens", r.output_tokens)
    r.total_tokens = obj.get("total_tokens", r.total_tokens)
    cost = obj.get("cost")
    if isinstance(cost, dict):
        cost = cost.get("total")
    if cost is not None:
        try:
            r.cost_usd = float(cost)
        except (TypeError, ValueError):
            pass


class OpenRouterClient:
    def __init__(self, api_key=None, session=None):
        self.api_key = config.OPENROUTER_API_KEY if api_key is None else api_key.strip()
        self.session = session or requests.Session()

    def ask(self, prompt, history=()):
        r = Response(model_requested=config.MODEL)
        if not self.api_key:
            r.error = "No API key. Open config.py and fill in API_KEY."
            return r
        messages = [{"role": "system", "content": config.SYSTEM_PROMPT}]
        messages.extend(history)
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": config.MODEL,
            "messages": messages,
            "temperature": config.TEMPERATURE,
            "max_tokens": config.MAX_OUTPUT_TOKENS,
            "stream": True,
            "reasoning": {"enabled": False},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/vitor-souza-ime/roboSLM",
            "X-Title": "roboOpenRouter-Conversational",
        }
        start = time.perf_counter()
        try:
            with self.session.post(
                f"{config.OPENROUTER_URL}/chat/completions", headers=headers,
                json=payload, timeout=(15, config.REQUEST_TIMEOUT_S), stream=True,
            ) as resp:
                r.http_status = resp.status_code
                if not resp.ok:
                    r.error = f"HTTP {resp.status_code}: {resp.text[:320]}"
                else:
                    text_parts = []
                    for line in resp.iter_lines(decode_unicode=True):
                        if not line:
                            continue
                        if isinstance(line, bytes):
                            line = line.decode("utf-8", "replace")
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if data.get("error"):
                            r.error = str(data["error"])[:320]
                            break
                        r.generation_id = data.get("id") or r.generation_id
                        r.model_reported = data.get("model") or r.model_reported
                        for choice in data.get("choices") or []:
                            fragment = _str_content((choice.get("delta") or {}).get("content"))
                            if fragment:
                                if r.ttft_s is None:
                                    r.ttft_s = time.perf_counter() - start
                                text_parts.append(fragment)
                        _usage(r, data.get("usage"))
                    r.reply = "".join(text_parts).strip()
        except requests.Timeout:
            r.error = "OpenRouter request timed out."
        except requests.RequestException as exc:
            r.error = f"Network error: {exc}"[:320]
        except (TypeError, ValueError, KeyError) as exc:
            r.error = f"Response format error: {exc}"[:320]
        finally:
            r.llm_s = time.perf_counter() - start
        r.success = bool(r.reply) and not r.error
        if not r.success and not r.error:
            r.error = "Empty response from model."
        return r

    def enrich_metadata(self, result):
        """Separate metadata GET; invoked AFTER voice playback (excluded from E2E)."""
        if not self.api_key or not result.generation_id or result.demo:
            return
        start = time.perf_counter()
        try:
            resp = self.session.get(
                f"{config.OPENROUTER_URL}/generation",
                params={"id": result.generation_id},
                headers={"Authorization": f"Bearer {self.api_key}"}, timeout=10)
            if resp.ok:
                data = resp.json().get("data") or {}
                result.provider = data.get("provider_name") or result.provider
                if result.cost_usd is None and data.get("total_cost") is not None:
                    result.cost_usd = float(data["total_cost"])
                if result.input_tokens is None:
                    result.input_tokens = data.get("tokens_prompt")
                if result.output_tokens is None:
                    result.output_tokens = data.get("tokens_completion")
                if result.total_tokens is None and result.input_tokens is not None and result.output_tokens is not None:
                    result.total_tokens = result.input_tokens + result.output_tokens
        except (requests.RequestException, ValueError, TypeError):
            pass  # Not a conversation failure; leave unknown metrics blank.
        finally:
            result.metadata_s = time.perf_counter() - start


def demo_reply(prompt):
    """Offline interface check, never substitute for a real experimental observation."""
    return Response(success=True, reply="Hello! This is a simulated demo, not a real LLM answer.",
                    model_requested=config.MODEL, model_reported="OFFLINE-DEMO",
                    llm_s=0.0, demo=True)
