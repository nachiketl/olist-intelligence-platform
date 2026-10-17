import os
import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()


@pytest.fixture(scope="session")
def engine():
    return create_engine(os.environ["DATABASE_URL"])


@pytest.fixture(scope="session")
def scalar(engine):
    """Run a query and return its single value."""
    def run(sql):
        with engine.connect() as conn:
            return conn.execute(text(sql)).scalar()
    return run