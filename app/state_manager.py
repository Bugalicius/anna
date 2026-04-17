"""
RedisStateManager — persistência de estado de conversa no Redis.

Responsabilidades:
  - Serializar/deserializar instâncias de agente para JSON
  - Armazenar estado no Redis usando phone_hash como chave
  - Graceful degradation: falha do Redis loga erro e retorna None (D-15)
  - SEM TTL automático — estado só é removido em finalizacao (D-12)
"""
from __future__ import annotations

import json
import logging

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class RedisStateManager:
    """
    Persiste estado de agentes no Redis.

    Usa phone_hash como chave (nunca o número real — LGPD).
    Não define TTL nas chaves: estado é deletado explicitamente ao fim do fluxo.
    """

    KEY_PREFIX = "agent_state:"

    def __init__(self, redis_url: str) -> None:
        self._client = aioredis.Redis.from_url(redis_url, decode_responses=True)

    async def load(self, phone_hash: str) -> object | None:
        """
        Carrega o estado do agente para o phone_hash.

        Returns:
            Instância de AgenteAtendimento ou AgenteRetencao, ou None se não encontrado
            ou se Redis estiver indisponível.
        """
        # Imports locais para evitar circular imports
        from app.agents.atendimento import AgenteAtendimento
        from app.agents.retencao import AgenteRetencao

        try:
            raw = await self._client.get(f"{self.KEY_PREFIX}{phone_hash}")
        except Exception as e:
            logger.error("Redis load failed for %s: %s", phone_hash[-4:], e)
            return None

        if not raw:
            return None

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Redis state JSON inválido para %s: %s", phone_hash[-4:], e)
            return None

        tipo = data.get("_tipo")
        if tipo == "atendimento":
            return AgenteAtendimento.from_dict(data)
        if tipo == "retencao":
            return AgenteRetencao.from_dict(data)

        logger.warning("Tipo de agente desconhecido no Redis: %s", tipo)
        return None

    async def save(self, phone_hash: str, agent: object) -> None:
        """
        Salva estado do agente no Redis SEM TTL (D-12).

        Estado persiste até ser deletado explicitamente em finalizacao.
        """
        if agent is None:
            return

        try:
            data = agent.to_dict()
            await self._client.set(
                f"{self.KEY_PREFIX}{phone_hash}",
                json.dumps(data, ensure_ascii=False),
                # SEM ex=, px=, exat=, pxat= — per D-12
            )
        except Exception as e:
            logger.error("Redis save failed for %s: %s", phone_hash[-4:], e)

    async def delete(self, phone_hash: str) -> None:
        """Remove o estado do agente do Redis (chamado em finalizacao)."""
        try:
            await self._client.delete(f"{self.KEY_PREFIX}{phone_hash}")
        except Exception as e:
            logger.error("Redis delete failed for %s: %s", phone_hash[-4:], e)
