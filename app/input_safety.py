from __future__ import annotations

import os
import re
import unicodedata


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_inbound_text(text: str | None) -> str:
    """Normaliza texto inbound preservando emojis e limitando tamanho."""
    if text is None:
        return ""
    value = unicodedata.normalize("NFC", str(text))
    value = _CONTROL_CHARS.sub("", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    max_chars = int(os.environ.get("INBOUND_TEXT_MAX_CHARS", "2000"))
    if len(value) > max_chars:
        value = value[:max_chars].rstrip() + "\n[Mensagem truncada por limite de tamanho]"
    return value
