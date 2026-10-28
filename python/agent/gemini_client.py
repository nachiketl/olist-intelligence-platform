"""Gemini adapter. The only file that talks to the Google API, so the rest can be tested with a stub."""
from __future__ import annotations

import time

from .orchestrator import ModelReply, ToolCall

_TRANSIENT = ("getaddrinfo", "ConnectError", "ConnectTimeout", "ReadTimeout", "503", "429")


class GeminiClient:
    def __init__(self, api_key: str, model: str):
        if not api_key or not model:
            raise RuntimeError("Set GEMINI_API_KEY and GEMINI_MODEL in .env")
        from google import genai

        self.client = genai.Client(api_key=api_key)
        self.model = model

    def new_session(self, system: str, tool_specs: list[dict]) -> "GeminiSession":
        return GeminiSession(self.client, self.model, system, tool_specs)


class GeminiSession:
    def __init__(self, client, model: str, system: str, tool_specs: list[dict]):
        from google.genai import types

        self.types = types
        self.client = client
        self.model = model
        declarations = [
            types.FunctionDeclaration(name=t["name"], description=t["description"], parameters=t["parameters"])
            for t in tool_specs
        ]
        self.config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=declarations)],
            temperature=0.0,
        )
        self.contents: list = []

    def send_user(self, text: str) -> ModelReply:
        self.contents.append(self.types.Content(role="user", parts=[self.types.Part(text=text)]))
        return self._call()

    def send_tool_results(self, results: list[tuple[str, dict]]) -> ModelReply:
        parts = [self.types.Part.from_function_response(name=name, response={"result": out}) for name, out in results]
        self.contents.append(self.types.Content(role="user", parts=parts))
        return self._call()

    def _generate(self):
        """Call the model, retrying a few times on network blips, quota and temporary Google errors."""
        for attempt in range(4):
            try:
                return self.client.models.generate_content(
                    model=self.model, contents=self.contents, config=self.config
                )
            except Exception as exc:
                transient = any(s in f"{type(exc).__name__} {exc}" for s in _TRANSIENT)
                if not transient or attempt == 3:
                    raise
                time.sleep(2 * (attempt + 1))  # wait 2, 4, 6 seconds

    def _call(self) -> ModelReply:
        resp = self._generate()
        content = resp.candidates[0].content
        self.contents.append(content)  # keep the model turn exactly as returned
        calls = [ToolCall(fc.name, dict(fc.args or {})) for fc in (resp.function_calls or [])]
        text = "".join(
            p.text for p in (content.parts or []) if getattr(p, "text", None) and not getattr(p, "thought", False)
        )
        usage = resp.usage_metadata
        return ModelReply(
            text=text.strip(),
            tool_calls=calls,
            tokens_in=int(getattr(usage, "prompt_token_count", 0) or 0),
            tokens_out=int(getattr(usage, "candidates_token_count", 0) or 0),
        )