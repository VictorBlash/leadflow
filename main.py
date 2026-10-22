from dotenv import load_dotenv

load_dotenv()

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from auth import require_api_key
from orchestrator import run_workflow
from database import Base, SessionLocal, engine
from models import Lead, WorkflowRun
from schemas import LeadIn, LeadOut, WorkflowRunOut


load_dotenv()

Base.metadata.create_all(bind=engine)

app = FastAPI()

# Every route except /health requires X-API-Key. The docs routes (/docs,
# /redoc, /openapi.json) are not router routes, so they stay public.
protected = APIRouter(dependencies=[Depends(require_api_key)])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        
        
@protected.get("/")
def root():
    return {
        "service": "leadflow",
        "status": "ok",
        "docs": "/docs",
    }
    
    
@app.get("/health")
def health():
    return {"status": "ok"}


@protected.post("/leads", response_model=LeadOut, status_code=201)
def create_lead(payload: LeadIn, db: Session = Depends(get_db)):
    lead = Lead(name=payload.name, email=payload.email, company=payload.company)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    run_workflow(lead, db)
    return lead


@protected.get("/leads", response_model=list[LeadOut])
def list_leads(db: Session = Depends(get_db)):
    return db.query(Lead).all()


@protected.get("/workflow_runs", response_model=list[WorkflowRunOut])
def list_workflow_runs(db: Session = Depends(get_db)):
    return db.query(WorkflowRun).all()


app.include_router(protected)


 
