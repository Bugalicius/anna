import logging

logger = logging.getLogger(__name__)

FLOWS: dict[str, str | None] = {
    "new": (
        "Olá! Que bom ter você por aqui 💚\n\n"
        "Sou a Ana, responsável pelos agendamentos da nutricionista Thaynara Teixeira.\n\n"
        "Pra começar, você poderia me informar:\n"
        " • Qual seu nome e sobrenome?\n"
        " • É sua primeira consulta ou você já é paciente?"
    ),
    "awaiting_payment": (
        "Para confirmar seu agendamento, é necessário realizar o pagamento antecipado:\n\n"
        "• *PIX*: sinal de 50% do valor\n"
        "• *Cartão*: pagamento integral (parcelamento disponível)\n\n"
        "Me informe qual opção prefere para eu providenciar o necessário. 👇"
    ),
    "scheduling": (
        "Para seguirmos com o agendamento, qual horário atende melhor à sua rotina?\n\n"
        "*Segunda a Sexta-feira:*\n"
        "Manhã: 08h, 09h e 10h\n"
        "Tarde: 15h, 16h e 17h\n"
        "Noite: 18h e 19h _(exceto sexta à noite)_"
    ),
    "confirmed": (
        "✅ Agendamento confirmado!\n\n"
        "Em breve a Thaynara entrará em contato com as orientações para sua consulta.\n"
        "Qualquer dúvida, pode me chamar aqui! 💚"
    ),
    "archived": None,  # Não responde
}


def get_flow_response(stage: str, text: str) -> str | None:
    return FLOWS.get(stage)


async def handle_flow(phone: str, phone_hash: str, stage: str, text: str):
    """Envia resposta do fluxo fixo e atualiza stage se necessário."""
    from app.meta_api import MetaAPIClient
    from app.database import SessionLocal
    from app.models import Contact

    response_text = get_flow_response(stage, text)
    if response_text is None:
        return

    meta = MetaAPIClient()
    meta.send_text(to=phone, text=response_text)

    # Avançar stage após boas-vindas
    if stage == "new":
        with SessionLocal() as db:
            contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
            if contact:
                contact.stage = "collecting_info"
                db.commit()
