"""Settings for the agent. Secrets come only from .env; nothing is hard-coded here."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Views the agent may read. agent_ro is also limited to these schemas by PostgreSQL itself.
ALLOWED_RELATIONS: dict[str, str] = {
    # marts
    "category_pareto": "marts",
    "kpi_summary": "marts",
    "monthly_sales": "marts",
    "payment_mix": "marts",
    "state_delivery": "marts",
    "target_vs_actual": "marts",
    "target_vs_actual_monthly": "marts",
    "v_sales_items": "marts",
    "v_sales_orders": "marts",
    "customer_rfm": "marts",
    "cohort_retention": "marts",
    "seller_scorecard": "marts",
    # ref
    "business_rules": "ref",
    "data_dictionary": "ref",
    "sales_targets": "ref",
}
ALLOWED_SCHEMAS = {"marts", "ref"}

# Columns marked restricted in the data dictionary: the agent never selects them.
RESTRICTED_COLUMNS = {"customer_unique_id", "customer_id", "zip_prefix", "lat", "lng"}

MAX_ROWS = 200            # hard row limit forced onto every query
MAX_ROWS_TO_MODEL = 50    # rows shown to the model per tool call
MAX_SQL_CHARS = 4000


@dataclass(frozen=True)
class Config:
    api_key: str
    model: str
    max_steps: int
    max_tokens_per_run: int
    cost_per_m_input: float
    cost_per_m_output: float


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:  # python-dotenv is in requirements.txt; this keeps imports cheap in tests
        pass


def get_config() -> Config:
    _load_env()
    return Config(
        api_key=os.environ.get("GEMINI_API_KEY", ""),
        model=os.environ.get("GEMINI_MODEL", ""),
        max_steps=int(os.environ.get("AGENT_MAX_STEPS", "6")),
        max_tokens_per_run=int(os.environ.get("AGENT_MAX_TOKENS", "60000")),
        # Prices are optional. Leave at 0 if unknown: cost_usd is then logged as 0, not invented.
        cost_per_m_input=float(os.environ.get("AGENT_COST_PER_M_INPUT", "0")),
        cost_per_m_output=float(os.environ.get("AGENT_COST_PER_M_OUTPUT", "0")),
    )


def build_url(role: str):
    """Database URL for a given role (agent_ro or agent_rw), password taken from .env."""
    from sqlalchemy.engine import make_url

    _load_env()
    password = os.environ[f"{role.upper()}_PASSWORD"]
    return make_url(os.environ["DATABASE_URL"]).set(username=role, password=password)