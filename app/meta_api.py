from __future__ import annotations

import hashlib
import hmac
import httpx
import os

META_API_BASE = "https://graph.facebook.com/v19.0"


def verify_signature(body: bytes, signature: str, app_secret: str) -> bool:
    """Valida X-Hub-Signature-256 da Meta."""
    if not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class MetaAPIClient:
    def __init__(
        self,
        phone_number_id: str | None = None,
        access_token: str | None = None,
    ):
        self._phone_id = phone_number_id or os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
        token = access_token or os.environ.get("WHATSAPP_TOKEN", "")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def send_text(self, to: str, text: str) -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        return await self._post(payload)

    async def send_contact(self, to: str, nome: str, telefone: str) -> dict:
        """Envia VCard de contato via WhatsApp (D-05)."""
        partes = nome.split(" ", 1)
        first_name = partes[0]
        last_name = partes[1] if len(partes) > 1 else ""
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "contacts",
            "contacts": [{
                "name": {
                    "formatted_name": nome,
                    "first_name": first_name,
                    "last_name": last_name,
                },
                "phones": [{
                    "phone": telefone,
                    "type": "CELL",
                }],
            }],
        }
        return await self._post(payload)

    async def send_template(self, to: str, template_name: str, language: str = "pt_BR",
                            components: list | None = None) -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
                **({"components": components} if components else {}),
            },
        }
        return await self._post(payload)

    async def upload_media(self, file_bytes: bytes, mime_type: str, filename: str) -> str:
        """Faz upload de arquivo para Meta e retorna media_id."""
        url = f"{META_API_BASE}/{self._phone_id}/media"
        auth_header = {"Authorization": self._headers["Authorization"]}
        async with httpx.AsyncClient(headers=auth_header, timeout=30) as client:
            files = {"file": (filename, file_bytes, mime_type)}
            data = {"messaging_product": "whatsapp", "type": mime_type}
            resp = await client.post(url, files=files, data=data)
            resp.raise_for_status()
            return resp.json()["id"]

    async def send_document(
        self,
        to: str,
        media_id: str,
        filename: str,
        caption: str = "",
    ) -> dict:
        """Envia documento (PDF, etc.) via WhatsApp."""
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "document",
            "document": {
                "id": media_id,
                "filename": filename,
                **({"caption": caption} if caption else {}),
            },
        }
        return await self._post(payload)

    async def send_image(self, to: str, media_id: str, caption: str = "") -> dict:
        """Envia imagem via WhatsApp."""
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": {
                "id": media_id,
                **({"caption": caption} if caption else {}),
            },
        }
        return await self._post(payload)

    async def _post(self, payload: dict) -> dict:
        url = f"{META_API_BASE}/{self._phone_id}/messages"
        async with httpx.AsyncClient(headers=self._headers, timeout=10) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
