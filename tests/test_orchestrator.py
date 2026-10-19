"""
Tests for the workflow: the priority rule, failure isolation, and what the
AI step receives. Runs against an in-memory SQLite database with Claude and
Slack stubbed, so no network or API key is needed.

Why these matter: the priority tag decides which leads the team looks at
first, and it is passed to Claude, so a rule that never fires changes every
draft. The orchestrator's promise is that a failing step never loses the
lead and always says which step broke.

Run with: pytest
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import orchestrator
from database import Base
from models import Draft, Lead
from orchestrator import run_workflow, tag_priority


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def add_lead(db, email="priya@northwind.io"):
    lead = Lead(name="Priya Raman", email=email, company="Northwind Systems")
    db.add(lead)
    db.commit()
    return lead


class FakeAnthropic:
    """Records the prompt and returns a fixed email."""

    prompts: list[str] = []

    def __init__(self):
        self.messages = self

    def create(self, model, max_tokens, messages):
        FakeAnthropic.prompts.append(messages[0]["content"])
        return SimpleNamespace(content=[SimpleNamespace(text="Hi Priya, a short note.")])


@pytest.fixture
def fake_claude(monkeypatch):
    FakeAnthropic.prompts = []
    monkeypatch.setattr(orchestrator, "Anthropic", FakeAnthropic)
    return FakeAnthropic


@pytest.mark.parametrize("email, expected", [
    ("priya@northwind.io", "hot"),
    ("ceo@acme-industrial.com", "hot"),
    ("priya.raman@gmail.com", "warm"),
    ("Priya@Outlook.COM", "warm"),
])
def test_company_addresses_are_hot_and_free_mail_is_warm(db, email, expected):
    lead = add_lead(db, email)
    tag_priority(lead, db)
    assert lead.status == expected


def test_a_failing_step_keeps_the_lead_and_records_where_it_stopped(db, monkeypatch):
    def broken(lead, db):
        raise RuntimeError("simulated failure")

    def never(lead, db):
        raise AssertionError("steps after a failure must not run")

    monkeypatch.setattr(orchestrator, "WORKFLOW_STEPS", [
        ("tag_priority", tag_priority), ("broken", broken), ("never", never),
    ])
    lead = add_lead(db)

    run = run_workflow(lead, db)

    assert run.status == "failed"
    assert run.current_step == "broken"
    assert run.error_message == "simulated failure"
    assert run.finished_at is not None
    assert db.get(Lead, lead.id).status == "hot"


def test_the_draft_is_written_with_the_priority_and_survives_a_slack_failure(db, fake_claude, monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    lead = add_lead(db)

    run = run_workflow(lead, db)

    # Slack isn't configured, so the last step fails, after the draft is saved.
    assert run.status == "failed"
    assert run.current_step == "notify_slack"
    assert "Priority: hot" in fake_claude.prompts[0]
    draft = db.query(Draft).filter_by(lead_id=lead.id).one()
    assert draft.content == "Hi Priya, a short note."
    assert (draft.model, draft.prompt_version) == (orchestrator.DRAFT_MODEL, orchestrator.PROMPT_VERSION)


def test_a_full_run_completes_when_every_step_succeeds(db, fake_claude, monkeypatch):
    posted = []
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/test")
    monkeypatch.setattr(orchestrator.requests, "post",
                        lambda url, json, timeout: posted.append(json) or SimpleNamespace(raise_for_status=lambda: None))
    lead = add_lead(db, "priya.raman@gmail.com")

    run = run_workflow(lead, db)

    assert run.status == "completed"
    assert posted == [{"text": "New warm lead: Priya Raman from Northwind Systems (priya.raman@gmail.com)"}]
