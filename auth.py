import os
import secrets

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

# auto_error=False so a missing header gets the same 401 as a wrong one.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(provided: str | None = Security(api_key_header)) -> None:
    # Read on every request, and fail closed: an unset or empty
    # LEADFLOW_API_KEY rejects everything rather than allowing it.
    expected = os.environ.get("LEADFLOW_API_KEY")
    # Compare bytes: compare_digest raises TypeError on non-ASCII str.
    if not expected or not provided or not secrets.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "APIKey"},
        )
