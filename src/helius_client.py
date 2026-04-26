"""
src/helius_client.py - Shadow Bot Solana
Cliente Helius RPC com polling de alta frequencia e suporte a webhook.
Monitora a carteira alvo e emite eventos de transacao em tempo real.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional, Set

import httpx
from loguru import logger

from config import settings


@dataclass
class RawTransaction:
    """Transacao bruta retornada pelo RPC Helius."""
    signature: str
    slot: Optional[int]
    block_time: Optional[int]
    meta: Dict[str, Any] = field(default_factory=dict)
    transaction: Dict[str, Any] = field(default_factory=dict)
    observed_at: float = field(default_factory=time.time)

    @property
    def pre_token_balances(self) -> List[Dict[str, Any]]:
        return self.meta.get("preTokenBalances") or []

    @property
    def post_token_balances(self) -> List[Dict[str, Any]]:
        return self.meta.get("postTokenBalances") or []

    @property
    def pre_sol_balance(self) -> int:
        """Saldo SOL pre-transacao do fee payer (lamports)."""
        balances = self.meta.get("preBalances") or []
        return balances[0] if balances else 0

    @property
    def post_sol_balance(self) -> int:
        """Saldo SOL pos-transacao do fee payer (lamports)."""
        balances = self.meta.get("postBalances") or []
        return balances[0] if balances else 0

    @property
    def sol_delta_lamports(self) -> int:
        """Variacao de SOL em lamports (negativo = saida de SOL = compra de token)."""
        return self.post_sol_balance - self.pre_sol_balance

    def extract_mints_bought(self) -> List[str]:
        """
        Identifica mints de tokens onde o balance aumentou pos-transacao.
        Sinal de BUY: aparece no post mas nao no pre, ou quantidade aumentou.
        """
        pre_map: Dict[str, float] = {}
        for item in self.pre_token_balances:
            mint = item.get("mint", "")
            amount = float(item.get("uiTokenAmount", {}).get("uiAmount") or 0)
            pre_map[mint] = pre_map.get(mint, 0) + amount

        mints_bought = []
        for item in self.post_token_balances:
            mint = item.get("mint", "")
            amount = float(item.get("uiTokenAmount", {}).get("uiAmount") or 0)
            pre_amount = pre_map.get(mint, 0)
            if amount > pre_amount and mint:
                mints_bought.append(mint)

        return list(set(mints_bought))

    def extract_mints_sold(self) -> List[str]:
        """
        Identifica mints de tokens onde o balance diminuiu pos-transacao.
        Sinal de SELL.
        """
        post_map: Dict[str, float] = {}
        for item in self.post_token_balances:
            mint = item.get("mint", "")
            amount = float(item.get("uiTokenAmount", {}).get("uiAmount") or 0)
            post_map[mint] = post_map.get(mint, 0) + amount

        mints_sold = []
        for item in self.pre_token_balances:
            mint = item.get("mint", "")
            amount = float(item.get("uiTokenAmount", {}).get("uiAmount") or 0)
            post_amount = post_map.get(mint, 0)
            if amount > post_amount and mint:
                mints_sold.append(mint)

        return list(set(mints_sold))

    def detect_action(self) -> str:
        """Detecta BUY, SELL ou UNKNOWN com base nos balances."""
        bought = self.extract_mints_bought()
        sold = self.extract_mints_sold()
        if bought and not sold:
            return "buy"
        if sold and not bought:
            return "sell"
        if bought and sold:
            return "swap"
        return "unknown"


class HeliusRPCClient:
    """
    Cliente Helius RPC com:
    - Polling de alta frequencia (getSignaturesForAddress)
    - Fetch detalhado de transacoes (getTransaction)
    - Deduplicacao de assinaturas via seen_set
    - Backoff exponencial em caso de erro
    """

    def __init__(self):
        self.rpc_url = settings.helius_rpc_url
        self.wallet = settings.target_wallet
        self.polling_interval = settings.polling_interval_sec
        self.max_signatures = settings.rpc_max_signatures
        self.seen_signatures: Set[str] = set()
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=5.0),
                limits=httpx.Limits(max_connections=10),
            )
        return self._client

    async def _rpc_call(
        self,
        method: str,
        params: List[Any],
        retries: int = 3,
    ) -> Any:
        client = await self._get_client()
        payload = {
            "jsonrpc": "2.0",
            "id": "shadow-bot",
            "method": method,
            "params": params,
        }
        backoff = 1.0
        for attempt in range(retries):
            try:
                r = await client.post(self.rpc_url, json=payload)
                r.raise_for_status()
                data = r.json()
                if "error" in data:
                    logger.warning(f"RPC error [{method}]: {data['error']}")
                    return None
                return data.get("result")
            except Exception as e:
                logger.warning(f"RPC attempt {attempt + 1}/{retries} failed [{method}]: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(backoff)
                    backoff *= 2
        return None

    async def get_signatures(
        self,
        limit: int = 20,
        before: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Busca assinaturas recentes da carteira alvo."""
        options: Dict[str, Any] = {"limit": limit}
        if before:
            options["before"] = before
        result = await self._rpc_call(
            "getSignaturesForAddress",
            [self.wallet, options],
        )
        return result or []

    async def get_transaction(self, signature: str) -> Optional[RawTransaction]:
        """Busca detalhes completos de uma transacao."""
        result = await self._rpc_call(
            "getTransaction",
            [
                signature,
                {
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 0,
                    "commitment": "confirmed",
                },
            ],
        )
        if not result:
            return None
        return RawTransaction(
            signature=signature,
            slot=result.get("slot"),
            block_time=result.get("blockTime"),
            meta=result.get("meta") or {},
            transaction=result.get("transaction") or {},
            observed_at=time.time(),
        )

    async def poll_new_transactions(
        self,
    ) -> AsyncGenerator[RawTransaction, None]:
        """
        Generator assíncrono que faz polling continuo.
        Emite apenas transacoes novas (nao vistas antes).
        """
        logger.info(
            f"[Helius] Iniciando polling | wallet={self.wallet} | "
            f"interval={self.polling_interval}s"
        )
        while True:
            t_start = time.perf_counter()
            try:
                sigs = await self.get_signatures(limit=self.max_signatures)
                # Processa da mais antiga para mais nova
                for item in reversed(sigs):
                    sig = item.get("signature")
                    if not sig or sig in self.seen_signatures:
                        continue
                    self.seen_signatures.add(sig)
                    # Evita crescimento infinito do set
                    if len(self.seen_signatures) > 10_000:
                        self.seen_signatures = set(list(self.seen_signatures)[-5_000:])

                    tx = await self.get_transaction(sig)
                    if tx:
                        latency_ms = (time.perf_counter() - t_start) * 1000
                        logger.debug(
                            f"[Helius] Nova tx | sig={sig[:12]}... | "
                            f"action={tx.detect_action()} | latency={latency_ms:.1f}ms"
                        )
                        yield tx

            except Exception as e:
                logger.error(f"[Helius] Erro no polling: {e}")

            elapsed = time.perf_counter() - t_start
            sleep_time = max(0.0, self.polling_interval - elapsed)
            await asyncio.sleep(sleep_time)

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        logger.info("[Helius] Cliente encerrado.")
