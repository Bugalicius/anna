import httpx


class EvolutionClient:
    def __init__(self, base_url: str, api_key: str, instance: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {"apikey": api_key, "Content-Type": "application/json"}
        self.instance = instance

    def fetch_chats(self, limit: int = 800) -> list[dict]:
        """Returns `limit` most recent chats, excluding groups and broadcasts."""
        with httpx.Client(headers=self.headers, timeout=30) as client:
            resp = client.post(f"{self.base_url}/chat/findChats/{self.instance}", json={})
            resp.raise_for_status()
            chats = resp.json()

        # Filter out groups (@g.us) and broadcasts (@broadcast)
        chats = [c for c in chats if "@s.whatsapp.net" in c.get("remoteJid", "")]

        # Sort by updatedAt descending
        chats.sort(key=lambda c: c.get("updatedAt", ""), reverse=True)

        return chats[:limit]

    def fetch_messages(self, remote_jid: str) -> list[dict]:
        """Returns messages for a conversation in chronological order."""
        with httpx.Client(headers=self.headers, timeout=30) as client:
            resp = client.post(
                f"{self.base_url}/chat/findMessages/{self.instance}",
                json={"where": {"key": {"remoteJid": remote_jid}}, "limit": 200}
            )
            resp.raise_for_status()
            data = resp.json()

        records = data.get("messages", {}).get("records", [])
        messages = []
        for r in records:
            text = (
                r.get("message", {}).get("conversation")
                or r.get("message", {}).get("extendedTextMessage", {}).get("text")
                or "[mídia]"
            )
            messages.append({
                "id": r["key"]["id"],
                "from_me": r["key"].get("fromMe", False),
                "text": text,
                "timestamp": r.get("messageTimestamp", 0),
            })

        messages.sort(key=lambda m: m["timestamp"])
        return messages
