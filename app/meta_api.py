import hashlib
import hmac
import httpx

META_API_BASE = "https://graph.facebook.com/v19.0"


def verify_signature(body: bytes, signature: str, app_secret: str) -> bool:
    """Valida X-Hub-Signature-256 da Meta."""
    if not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class MetaAPIClient:
    def __init__(self, phone_number_id: str, access_token: str):
        self._phone_id = phone_number_id
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    def send_text(self, to: str, text: str) -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        return self._post(payload)

    def send_template(self, to: str, template_name: str, language: str = "pt_BR",
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
        return self._post(payload)

    def _post(self, payload: dict) -> dict:
        url = f"{META_API_BASE}/{self._phone_id}/messages"
        with httpx.Client(headers=self._headers, timeout=10) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
