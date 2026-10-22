"""
Shared test setup. Runs before any test module is imported.

Importing main runs Base.metadata.create_all and load_dotenv at import time.
Pointing DATABASE_URL at in-memory SQLite here, before database.py builds its
engine, keeps the tests from creating or modifying ./leadflow.db (or reaching
a Postgres URL from the shell). load_dotenv does not override variables that
are already set, so .env cannot redirect it either.
"""

import os

import pytest

os.environ["DATABASE_URL"] = "sqlite://"


@pytest.fixture(autouse=True)
def no_api_key_from_environment(monkeypatch):
    # A LEADFLOW_API_KEY from the shell or from .env (loaded when main is
    # imported) must not decide any test. Tests that need one set it.
    monkeypatch.delenv("LEADFLOW_API_KEY", raising=False)
