import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.webhook import router as webhook_router
from app.test_chat import router as test_chat_router
from app.remarketing import create_scheduler
from app.retry import _retry_failed_messages
from app.database import engine, Base

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Base.metadata.create_all(bind=engine)  # Fallback se Alembic não rodou

    # Inicializa persistência de estado de conversa no Redis
    from app.router import init_state_manager
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379")
    init_state_manager(redis_url)

    scheduler = create_scheduler()
    # Adicionar job de retry (async)
    scheduler.add_job(
        _retry_failed_messages, "interval", minutes=5,
        id="retry_processor", replace_existing=True,
    )
    scheduler.start()
    app.state.scheduler = scheduler
    yield
    # Shutdown
    scheduler.shutdown(wait=False)


app = FastAPI(title="Agente Ana — Nutri Thaynara", lifespan=lifespan)
app.include_router(webhook_router)
app.include_router(test_chat_router)

# Serve arquivos de mídia (PDF, imagens) para o chat de teste
_docs_path = Path("/app/docs")
if _docs_path.exists():
    app.mount("/media", StaticFiles(directory=str(_docs_path)), name="media")


@app.get("/health")
async def health():
    return {"status": "ok"}
