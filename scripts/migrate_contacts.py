"""
Importa os contatos históricos do PostgreSQL da Evolution API
para o novo banco do agente Ana.

Executar UMA VEZ antes do go-live.
"""
import hashlib
import os
import sys
from datetime import datetime, UTC

import psycopg2
from dotenv import load_dotenv

load_dotenv()

EVOLUTION_DB = os.environ.get(
    "EVOLUTION_DATABASE_URL",
    "postgresql://evolution:evolution123@localhost:5432/evolution"
)
NEW_DB = os.environ.get("DATABASE_URL", "")


def migrate():
    from app.database import SessionLocal, engine, Base
    from app.models import Contact

    Base.metadata.create_all(bind=engine)

    # Conectar ao banco da Evolution
    evo_conn = psycopg2.connect(EVOLUTION_DB)
    evo_cursor = evo_conn.cursor()

    # Buscar contatos (tabela Contact da Evolution API)
    evo_cursor.execute("""
        SELECT "remoteJid", "pushName", "updatedAt"
        FROM "Contact"
        WHERE "instanceId" = (SELECT id FROM "Instance" WHERE name = 'thay' LIMIT 1)
        AND "remoteJid" LIKE '%@s.whatsapp.net'
        ORDER BY "updatedAt" DESC
    """)
    rows = evo_cursor.fetchall()
    print(f"Contatos encontrados na Evolution: {len(rows)}")

    imported = 0
    with SessionLocal() as db:
        for jid, push_name, updated_at in rows:
            phone_hash = hashlib.sha256(jid.encode()).hexdigest()[:64]
            existing = db.query(Contact).filter_by(phone_hash=phone_hash).first()
            if not existing:
                contact = Contact(
                    phone_hash=phone_hash,
                    push_name=push_name,
                    stage="cold_lead",  # Contatos históricos são leads potenciais
                    last_message_at=updated_at,
                    created_at=datetime.now(UTC),
                )
                db.add(contact)
                imported += 1
        db.commit()

    print(f"Contatos importados: {imported}")
    evo_conn.close()


if __name__ == "__main__":
    migrate()
