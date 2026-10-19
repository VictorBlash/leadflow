import os

import requests

from datetime import datetime, timezone

from anthropic import Anthropic

from sqlalchemy.orm import Session

from models import Draft, Lead, WorkflowRun

PROMPT_VERSION = "v1"
DRAFT_MODEL = "claude-haiku-4-5-20251001"

OUTREACH_PROMPT = """You are writing a short cold outreach email on behalf of a B2B software company.

Lead details:
- Name: {name}
- Company: {company}
- Priority: {status}

Write a 3-4 sentence email to this person. Rules:
- Reference their company by name once, naturally
- No buzzwords, no "I hope this finds you well", no exclamation marks
- End with one specific, low-commitment question
- Output ONLY the email body. No subject line, no signature, no preamble."""


def log_lead(lead: Lead, db: Session) -> None:
    print(f"[log_lead] Lead {lead.id}: {lead.name} from {lead.company}")


# Free-mail providers. Someone writing from one of these may still be a buyer,
# but for a B2B team a company address is the stronger first signal.
FREE_MAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "ymail.com",
    "outlook.com", "hotmail.com", "hotmail.co.uk", "live.com", "msn.com",
    "aol.com", "icloud.com", "me.com", "mac.com", "proton.me", "protonmail.com",
    "gmx.com", "mail.com", "zoho.com", "yandex.com",
})


def tag_priority(lead: Lead, db: Session) -> None:
    """Tag the lead hot when it comes from a company address, warm from free mail."""
    domain = lead.email.rsplit("@", 1)[-1].lower()
    lead.status = "warm" if domain in FREE_MAIL_DOMAINS else "hot"
    db.commit()


def notify_slack(lead: Lead, db: Session ) -> None:
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        raise ValueError("SLACK_WEBHOOK_URL is not set")

    message = f"New {lead.status} lead: {lead.name} from {lead.company} ({lead.email})"
    response = requests.post(webhook_url, json={"text":message}, timeout=10)
    response.raise_for_status()    
    

def draft_outreach(lead: Lead, db: Session) -> None:
    client = Anthropic()
    
    prompt = OUTREACH_PROMPT.format(
        name=lead.name,
        company=lead.company,
        status=lead.status,
    )

    response = client.messages.create(
        model=DRAFT_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    
    )
    email_text = response.content[0].text
    
    draft = Draft(
        lead_id=lead.id,
        content=email_text,
        model=DRAFT_MODEL,
        prompt_version=PROMPT_VERSION,
    )
    db.add(draft)
    db.commit()
    
WORKFLOW_STEPS = [
    ("log_lead", log_lead),
    ("tag_priority", tag_priority),
    ("draft_outreach", draft_outreach),
    ("notify_slack", notify_slack),
]

    

def run_workflow(lead: Lead, db: Session) -> WorkflowRun:
    run = WorkflowRun(lead_id=lead.id, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        for step_name, step_function in WORKFLOW_STEPS:
            run.current_step = step_name
            db.commit()
            step_function(lead, db)

        run.status = "completed"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(run)

    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(run)

    return run