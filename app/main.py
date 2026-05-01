import logging
import os
import subprocess
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import redis.asyncio as aioredis
from sqlalchemy import func, text

from app.webhook import router as webhook_router
from app.test_chat import router as test_chat_router
from app.remarketing import create_scheduler
from app.retry import _retry_failed_messages
from app.database import engine, Base, SessionLocal
from app.config import validate_required_env
from app.metrics import read_recent_errors
from app.models import Contact

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    validate_required_env()
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
    return await _health_payload()


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(key: str = Query(default="")):
    expected_key = os.environ.get("DASHBOARD_KEY", "")
    if not expected_key or key != expected_key:
        raise HTTPException(status_code=403, detail="dashboard protegido")

    health_payload = await _health_payload()
    since = datetime.now(UTC) - timedelta(hours=24)
    with SessionLocal() as db:
        active_24h = db.query(func.count(Contact.id)).filter(Contact.last_message_at >= since).scalar() or 0
        scheduled_24h = (
            db.query(func.count(Contact.id))
            .filter(Contact.last_message_at >= since, Contact.stage.in_(["agendado", "concluido"]))
            .scalar()
            or 0
        )

    success_rate = (scheduled_24h / active_24h * 100) if active_24h else 0.0
    errors = read_recent_errors(limit=10)
    errors_html = "\n".join(
        "<li><code>{ts}</code> hash={phone} action={action} error={error}</li>".format(
            ts=escape(str(e.get("ts", ""))),
            phone=escape(str(e.get("phone_hash", ""))[-12:]),
            action=escape(str(e.get("action", ""))),
            error=escape(str(e.get("error", ""))),
        )
        for e in errors
    ) or "<li>Nenhum erro recente.</li>"

    redis_status = escape(str(health_payload["services"]["redis"]["status"]))
    postgres_status = escape(str(health_payload["services"]["postgres"]["status"]))
    version = escape(str(health_payload["version"]))
    timestamp = escape(str(health_payload["timestamp"]))

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Ana Dashboard</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px auto; max-width: 920px; color: #1f2933; line-height: 1.5; }}
    h1 {{ margin-bottom: 8px; }}
    section {{ border-top: 1px solid #d7dde3; padding: 18px 0; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
    .metric {{ border: 1px solid #d7dde3; border-radius: 6px; padding: 14px; }}
    .label {{ color: #64748b; font-size: 13px; }}
    .value {{ font-size: 28px; font-weight: 700; margin-top: 4px; }}
    code {{ background: #eef2f7; padding: 2px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>Ana Dashboard</h1>
  <p>Versão <code>{version}</code> · {timestamp}</p>
  <section class="grid">
    <div class="metric"><div class="label">Conversas ativas 24h</div><div class="value">{active_24h}</div></div>
    <div class="metric"><div class="label">Agendamentos/conclusões 24h</div><div class="value">{scheduled_24h}</div></div>
    <div class="metric"><div class="label">Taxa de sucesso</div><div class="value">{success_rate:.1f}%</div></div>
  </section>
  <section>
    <h2>Serviços</h2>
    <p>Redis: <strong>{redis_status}</strong> · PostgreSQL: <strong>{postgres_status}</strong></p>
  </section>
  <section>
    <h2>Erros recentes</h2>
    <ul>{errors_html}</ul>
  </section>
</body>
</html>"""


async def _health_payload() -> dict:
    redis_status = {"status": "ok"}
    postgres_status = {"status": "ok"}

    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    redis_client = None
    try:
        redis_client = aioredis.Redis.from_url(redis_url, decode_responses=True)
        await redis_client.ping()
    except Exception as e:
        redis_status = {"status": "error", "error": str(e)}
    finally:
        if redis_client:
            await redis_client.aclose()

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        postgres_status = {"status": "error", "error": str(e)}

    overall = "ok" if redis_status["status"] == "ok" and postgres_status["status"] == "ok" else "degraded"
    return {
        "status": overall,
        "services": {
            "redis": redis_status,
            "postgres": postgres_status,
        },
        "version": _app_version(),
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _app_version() -> str:
    for name in ("APP_VERSION", "GIT_SHA", "RELEASE_SHA"):
        value = os.environ.get(name)
        if value:
            return value
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        ).strip()
    except Exception:
        return "unknown"


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    return """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Política de Privacidade — Ana (Assistente Virtual)</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #333; line-height: 1.7; }
    h1 { color: #2e7d32; }
    h2 { color: #388e3c; margin-top: 30px; }
    p { margin: 10px 0; }
    footer { margin-top: 40px; font-size: 0.85em; color: #888; }
  </style>
</head>
<body>
  <h1>Política de Privacidade</h1>
  <p><strong>Assistente Virtual Ana</strong> — Serviço de agendamento da nutricionista Thaynara Teixeira (CRN9 31020)</p>
  <p><em>Última atualização: abril de 2026</em></p>

  <h2>1. Quem somos</h2>
  <p>Este serviço é operado por Thaynara Teixeira, nutricionista registrada no CRN9 sob o número 31020, com atuação em Belo Horizonte/MG. O assistente virtual "Ana" é utilizado exclusivamente para agendamento de consultas nutricionais via WhatsApp.</p>

  <h2>2. Dados coletados</h2>
  <p>Coletamos apenas os dados necessários para agendamento e atendimento:</p>
  <ul>
    <li>Nome completo</li>
    <li>Número de telefone (WhatsApp)</li>
    <li>Preferências de horário e modalidade de consulta</li>
    <li>Histórico de mensagens trocadas no atendimento</li>
  </ul>

  <h2>3. Finalidade do uso</h2>
  <p>Os dados são utilizados exclusivamente para:</p>
  <ul>
    <li>Agendamento, remarcação e cancelamento de consultas</li>
    <li>Envio de lembretes e confirmações de agendamento</li>
    <li>Suporte ao atendimento da nutricionista</li>
  </ul>

  <h2>4. Compartilhamento de dados</h2>
  <p>Os dados não são vendidos nem compartilhados com terceiros para fins comerciais. O sistema utiliza a plataforma <strong>Dietbox</strong> para gestão de agendamentos e a API do <strong>WhatsApp Business (Meta)</strong> para comunicação. Ambas possuem suas próprias políticas de privacidade.</p>

  <h2>5. Armazenamento e segurança</h2>
  <p>Os dados são armazenados em servidor privado com acesso restrito. Adotamos medidas técnicas para proteger as informações contra acesso não autorizado.</p>

  <h2>6. Direitos do titular (LGPD)</h2>
  <p>Em conformidade com a Lei Geral de Proteção de Dados (Lei 13.709/2018), você pode solicitar a qualquer momento:</p>
  <ul>
    <li>Acesso aos seus dados</li>
    <li>Correção de dados incorretos</li>
    <li>Exclusão dos seus dados</li>
    <li>Revogação do consentimento</li>
  </ul>
  <p>Para exercer esses direitos, entre em contato diretamente com a nutricionista via WhatsApp.</p>

  <h2>7. Retenção de dados</h2>
  <p>Os dados são mantidos pelo período necessário à prestação do serviço. Após o encerramento do relacionamento, os dados podem ser anonimizados ou excluídos mediante solicitação.</p>

  <h2>8. Contato</h2>
  <p>Dúvidas sobre esta política? Entre em contato com a nutricionista Thaynara Teixeira pelo WhatsApp.</p>

  <footer>
    <p>Este documento foi elaborado em conformidade com a LGPD (Lei 13.709/2018) e os termos da API do WhatsApp Business da Meta.</p>
  </footer>
</body>
</html>"""
