import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from app.webhook import router as webhook_router
from app.test_chat import router as test_chat_router
from app.remarketing import create_scheduler
from app.retry import _retry_failed_messages
from app.database import engine, Base
from app.config import validate_required_env

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
    return {"status": "ok"}


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
