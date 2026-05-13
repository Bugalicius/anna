"""
Config Loader — carrega YAMLs de configuração com cache em memória.

Uso:
    from app.conversation.config_loader import config

    plano = config.get_plano("ouro")
    print(plano.valores.pix_presencial)  # 690.0

    fluxo = config.get_fluxo("agendamento_paciente_novo")
    print(list(fluxo.estados.keys()))
"""
from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml

from app.conversation.models import Fluxo, GlobalConfig, Plano

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parents[2] / "config"


def _normalize_keys(obj: Any) -> Any:
    """Remove acentos de chaves de dicionários recursivamente.

    Necessário porque global.yaml tem 'regras_invioláveis_globais' (com acento)
    que precisa mapear pro field 'regras_inviolaveis_globais' no Pydantic.
    """
    if isinstance(obj, dict):
        return {
            unicodedata.normalize("NFKD", str(k)).encode("ascii", "ignore").decode("ascii"): _normalize_keys(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_normalize_keys(item) for item in obj]
    return obj


class ConfigLoader:
    """Carrega e cacheia toda a configuração YAML do agente."""

    def __init__(self) -> None:
        self._global: GlobalConfig | None = None
        self._fluxos: dict[str, Fluxo] = {}
        self._fluxo_aliases: dict[str, str] = {}
        self._loaded = False

    # ── Carregamento ───────────────────────────────────────────────────────

    def load(self) -> None:
        """Carrega todos os YAMLs. Chamado no startup ou via reload()."""
        self._global = self._load_global()
        self._fluxos, self._fluxo_aliases = self._load_fluxos()
        self._loaded = True
        logger.info(
            "Config carregada: global.yaml + %d fluxo(s): %s",
            len(self._fluxos),
            list(self._fluxos.keys()),
        )

    def reload(self) -> None:
        """Recarrega toda a configuração sem reiniciar o app."""
        self._global = None
        self._fluxos = {}
        self._fluxo_aliases = {}
        self._loaded = False
        self.load()
        logger.info("Config recarregada com sucesso.")

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def _load_yaml_file(self, path: Path) -> dict[str, Any]:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError(f"{path.name} precisa ser um objeto YAML no topo.")
        return _normalize_keys(data)

    def _load_yaml_fluxo_file(self, path: Path) -> list[dict[str, Any]]:
        """Carrega um ou mais fluxos de um arquivo YAML.

        Alguns arquivos legados agrupam mais de um fluxo no mesmo YAML usando
        chaves de topo repetidas. O PyYAML manteria só o último bloco; aqui
        separamos cada bloco iniciado por ``fluxo_id:`` antes de validar.
        """
        text = path.read_text(encoding="utf-8")
        starts = [m.start() for m in re.finditer(r"(?m)^fluxo_id:\s*", text)]
        if len(starts) <= 1 or "2_3_remarcacao_cancelamento" not in path.stem:
            return [self._load_yaml_file(path)]

        docs: list[dict[str, Any]] = []
        for idx, start in enumerate(starts):
            end = starts[idx + 1] if idx + 1 < len(starts) else len(text)
            fragment = text[start:end]
            data = yaml.safe_load(fragment)
            if data is None:
                continue
            if not isinstance(data, dict):
                raise ValueError(f"{path.name} precisa ser um objeto YAML no topo.")
            docs.append(_normalize_keys(data))
        return docs

    def _load_global(self) -> GlobalConfig:
        raw = self._load_yaml_file(CONFIG_DIR / "global.yaml")
        return GlobalConfig(**raw)

    def _load_fluxos(self) -> tuple[dict[str, Fluxo], dict[str, str]]:
        fluxos: dict[str, Fluxo] = {}
        aliases: dict[str, str] = {}
        erros: list[str] = []
        fluxos_dir = CONFIG_DIR / "fluxos"
        for yaml_file in sorted(fluxos_dir.glob("*.yaml")):
            for raw in self._load_yaml_fluxo_file(yaml_file):
                try:
                    fluxo = Fluxo(**raw)
                    fluxos[fluxo.fluxo_id] = fluxo
                    slug = yaml_file.stem.replace("fluxo_", "")
                    aliases[slug] = fluxo.fluxo_id
                    aliases[fluxo.fluxo_id] = fluxo.fluxo_id
                    aliases[fluxo.fluxo_id.split("_")[0]] = fluxo.fluxo_id
                    logger.debug("Fluxo carregado: %s (%s)", fluxo.fluxo_id, yaml_file.name)
                except Exception as exc:
                    erros.append(f"{yaml_file.name}: {exc}")
        if erros:
            raise ValueError("Falha ao validar YAMLs de fluxo:\n- " + "\n- ".join(erros))
        return fluxos, aliases

    # ── Accessors ──────────────────────────────────────────────────────────

    @property
    def global_config(self) -> GlobalConfig:
        self._ensure_loaded()
        assert self._global is not None
        return self._global

    def get_plano(self, plano_id: str) -> Plano:
        """Retorna plano pelo ID (ex: 'ouro', 'premium')."""
        self._ensure_loaded()
        planos = self.global_config.planos
        if plano_id not in planos:
            raise KeyError(
                f"Plano {plano_id!r} não encontrado. Disponíveis: {sorted(planos)}"
            )
        return planos[plano_id]

    def get_fluxo(self, fluxo_id: str) -> Fluxo:
        """Retorna fluxo pelo fluxo_id."""
        self._ensure_loaded()
        resolved_id = self._fluxo_aliases.get(fluxo_id, fluxo_id)
        if resolved_id not in self._fluxos:
            raise KeyError(
                f"Fluxo {fluxo_id!r} não encontrado. Disponíveis: {sorted(self._fluxos)}"
            )
        return self._fluxos[resolved_id]

    def list_fluxos(self) -> list[str]:
        """Retorna lista de fluxo_ids carregados."""
        self._ensure_loaded()
        return list(self._fluxos.keys())

    def get_regra_global(self, regra_id: str) -> dict[str, Any]:
        """Retorna regra inviolável global pelo ID (ex: 'R1_nunca_expor_breno')."""
        self._ensure_loaded()
        regras = self.global_config.regras_inviolaveis_globais
        if regra_id not in regras:
            raise KeyError(f"Regra {regra_id!r} não encontrada.")
        return regras[regra_id]

    def get_numero(self, nome: str) -> dict[str, Any]:
        """Retorna config de número pelo nome ('thaynara' ou 'breno')."""
        self._ensure_loaded()
        numeros = self.global_config.numeros
        if nome not in numeros:
            raise KeyError(f"Número {nome!r} não encontrado.")
        return numeros[nome]


# Singleton global — importar e usar diretamente
config = ConfigLoader()
config.load()
