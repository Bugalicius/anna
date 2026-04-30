from __future__ import annotations

import os


class MissingEnvironmentError(RuntimeError):
    pass


_REQUIRED_ENV_GROUPS: dict[str, tuple[str, ...]] = {
    "GEMINI_API_KEY": ("GEMINI_API_KEY",),
    "META_ACCESS_TOKEN": ("META_ACCESS_TOKEN", "WHATSAPP_TOKEN"),
    "META_PHONE_NUMBER_ID": ("META_PHONE_NUMBER_ID", "WHATSAPP_PHONE_NUMBER_ID"),
    "DATABASE_URL": ("DATABASE_URL",),
    "REDIS_URL": ("REDIS_URL",),
}


def validate_required_env() -> None:
    missing: list[str] = []
    for label, aliases in _REQUIRED_ENV_GROUPS.items():
        if not any(os.environ.get(name) for name in aliases):
            if len(aliases) == 1:
                missing.append(label)
            else:
                missing.append(f"{label} (ou {', '.join(aliases[1:])})")

    if missing:
        raise MissingEnvironmentError(
            "Variaveis de ambiente obrigatorias ausentes: " + ", ".join(missing)
        )


def get_meta_access_token() -> str:
    return os.environ.get("META_ACCESS_TOKEN") or os.environ.get("WHATSAPP_TOKEN", "")


def get_meta_phone_number_id() -> str:
    return os.environ.get("META_PHONE_NUMBER_ID") or os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
