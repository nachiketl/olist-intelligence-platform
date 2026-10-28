"""Ask the agent one question:  python python\\agent\\ask.py "What was revenue in March 2018?" """
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.config import get_config  # noqa: E402
from agent.db import AgentDB, RunLogger  # noqa: E402
from agent.gemini_client import GeminiClient  # noqa: E402
from agent.orchestrator import Agent  # noqa: E402
from agent.schema_context import load_schema  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: python python\\agent\\ask.py "your question"')
        return 2
    question = " ".join(sys.argv[1:])
    cfg = get_config()
    db = AgentDB()
    agent = Agent(GeminiClient(cfg.api_key, cfg.model), db, RunLogger(), load_schema(db), cfg)
    result = agent.ask(question)

    print(f"\nQuestion: {result.question}")
    print(f"Answer:   {result.answer}\n")
    for i, sql in enumerate(result.sql, 1):
        print(f"SQL {i}: {sql}")
    print(f"\nStatus: {result.status} | tokens in/out: {result.tokens_in}/{result.tokens_out} "
          f"| {result.duration_ms} ms | run_id {result.run_id}")
    if result.error:
        print(f"Error: {result.error}")
    return 0 if result.status in {"ok", "blocked"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
