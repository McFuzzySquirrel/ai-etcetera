"""Local Ollama client used by curation and origin tracing.

The client is intentionally small and deterministic:
- temperature=0
- strict JSON output contract
- explicit timeout handling
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


@dataclass
class OllamaSuggestion:
    accept: bool
    confidence: float
    rationale: str
    supporting_signals: list[str]


@dataclass
class OllamaMotivation:
    summary: str
    confidence: float


class OllamaClient:
    def __init__(self, *, base_url: str, model: str, timeout_sec: int = 45):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_sec = timeout_sec

    def health(self) -> tuple[bool, str]:
        try:
            tags = self._get_json("/api/tags")
        except Exception as exc:
            return False, f"ollama unavailable: {exc}"

        models = tags.get("models") if isinstance(tags, dict) else None
        if not isinstance(models, list):
            return False, "invalid /api/tags response"

        names = {str(m.get("name", "")) for m in models if isinstance(m, dict)}
        if self.model not in names:
            return False, f"model '{self.model}' not found (ollama pull {self.model})"
        return True, "ok"

    def enrich_motivation(
        self,
        *,
        repo: str,
        excerpt: str,
    ) -> OllamaMotivation | None:
        system = (
            "You are a strict JSON API. Given a README excerpt for a software repository, "
            "summarise in a single sentence (max 200 characters) why the repository was built. "
            "Respond ONLY valid JSON with keys: "
            "summary (string, ≤200 chars), confidence (0..1 float)."
        )
        user = {
            "repo": repo,
            "excerpt": excerpt[:400],
            "instruction": "Focus on purpose and motivation, not features.",
        }
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, sort_keys=True)},
            ],
        }
        response = self._post_json("/api/chat", payload)
        if not isinstance(response, dict):
            return None
        message = response.get("message")
        if not isinstance(message, dict):
            return None
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            return None

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None

        summary = parsed.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            return None
        summary = summary.strip()[:200]

        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        return OllamaMotivation(summary=summary, confidence=confidence)

    def curate_pair(
        self,
        *,
        repo_a: str,
        repo_b: str,
        signals: dict[str, Any],
    ) -> OllamaSuggestion | None:
        system = (
            "You are a strict JSON API. Judge whether two repositories should have a "
            "COULD_COMPOSE_WITH relationship. Respond ONLY valid JSON with keys: "
            "accept (bool), confidence (0..1 float), rationale (short string), "
            "supporting_signals (array of short strings)."
        )
        user = {
            "repo_a": repo_a,
            "repo_b": repo_b,
            "signals": signals,
            "instruction": (
                "Prefer precision over recall. Reject weak/noisy links. "
                "If accepted, rationale should be 1-2 sentences max."
            ),
        }
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, sort_keys=True)},
            ],
        }
        response = self._post_json("/api/chat", payload)
        if not isinstance(response, dict):
            return None
        message = response.get("message")
        if not isinstance(message, dict):
            return None
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            return None

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None

        accept = bool(parsed.get("accept", False))
        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        rationale = parsed.get("rationale")
        rationale_text = str(rationale).strip() if rationale is not None else ""

        raw_signals = parsed.get("supporting_signals")
        supporting_signals: list[str] = []
        if isinstance(raw_signals, list):
            for item in raw_signals[:8]:
                text = str(item).strip()
                if text:
                    supporting_signals.append(text)

        return OllamaSuggestion(
            accept=accept,
            confidence=confidence,
            rationale=rationale_text,
            supporting_signals=supporting_signals,
        )

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        req = Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=self.timeout_sec) as resp:
                body = resp.read().decode("utf-8")
        except URLError as exc:  # pragma: no cover - network/runtime failures
            raise RuntimeError(str(exc)) from exc
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("invalid JSON response from Ollama") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("unexpected Ollama response shape")
        return parsed

    def _get_json(self, path: str) -> dict[str, Any]:
        req = Request(
            f"{self.base_url}{path}",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(req, timeout=self.timeout_sec) as resp:
                body = resp.read().decode("utf-8")
        except URLError as exc:  # pragma: no cover - network/runtime failures
            raise RuntimeError(str(exc)) from exc
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("invalid JSON response from Ollama") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("unexpected Ollama response shape")
        return parsed
