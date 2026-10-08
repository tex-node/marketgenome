from fastapi import Depends, FastAPI, HTTPException
from market_genome_domain.database import get_session
from market_genome_shared.config import get_settings
from market_genome_shared.logging import configure_logging
from sqlalchemy import text
from sqlalchemy.orm import Session

from market_genome_api.routes import router as api_v1_router

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(
    title="Market Genome API",
    version="0.1.0",
    description="Research API for market-pattern analogue retrieval.",
)
SessionDependency = Depends(get_session)
app.include_router(api_v1_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "market-genome-api", "environment": settings.environment}


@app.get("/ready")
def ready(session: Session = SessionDependency) -> dict[str, str]:
    try:
        session.execute(text("select 1"))
    except Exception as exc:  # pragma: no cover - exact DB driver exceptions vary
        raise HTTPException(status_code=503, detail="database_unavailable") from exc
    return {"status": "ready"}
