"""
Catalogo de arquivos estaticos para envio via Meta Cloud API.

Cada entrada mapeia uma chave semantica para o arquivo fisico em docs/.
Usado por router.py para resolver media_key -> file_bytes + mime + filename.
"""
from __future__ import annotations

MEDIA_STATIC: dict[str, dict[str, str]] = {
    "pdf_thaynara": {
        "path": "docs/Thaynara - Nutricionista.pdf",
        "mime": "application/pdf",
        "filename": "Thaynara - Nutricionista.pdf",
    },
    "img_preparo_online": {
        "path": "docs/COMO-SE-PREPARAR---ONLINE.jpg",
        "mime": "image/jpeg",
        "filename": "preparo-online.jpg",
    },
    "img_preparo_presencial": {
        "path": "docs/COMO-SE-PREPARAR---presencial.jpg",
        "mime": "image/jpeg",
        "filename": "preparo-presencial.jpg",
    },
    "pdf_guia_circunf_mulher": {
        "path": "docs/Guia - Circunferencias Corporais - Mulheres.pdf",
        "mime": "application/pdf",
        "filename": "Guia-Circunferencias-Mulheres.pdf",
    },
    "pdf_guia_circunf_homem": {
        "path": "docs/Guia - Circunferencias Corporais - Homens.pdf",
        "mime": "application/pdf",
        "filename": "Guia-Circunferencias-Homens.pdf",
    },
}
