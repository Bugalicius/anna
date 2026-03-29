import hashlib


class Pseudonymizer:
    def __init__(self, salt: str = "ana-nutri-2026"):
        self._salt = salt
        self._cache: dict[str, str] = {}

    def get_id(self, jid: str) -> str:
        if jid not in self._cache:
            digest = hashlib.sha256(f"{self._salt}:{jid}".encode()).hexdigest()[:12]
            self._cache[jid] = f"contact_{digest}"
        return self._cache[jid]

    def pseudonymize(self, jid: str, messages: list[dict]) -> dict:
        return {
            "contact_id": self.get_id(jid),
            "messages": [
                {"role": "agent" if m["from_me"] else "patient", "text": m["text"]}
                for m in messages
            ],
        }
