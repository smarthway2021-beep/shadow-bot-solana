"""
src/telegram_notifier.py - Shadow Bot Solana
Terminal de saida: envia alertas formatados para um chat privado no Telegram.
Sempre em modo simulacao - nenhuma ordem real e executada.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

import httpx
from loguru import logger

from config import settings


@dataclass
class AlertPayload:
    """Dados de um sinal de alerta para o Telegram."""
    token_mint: str
    token_name: str
    action: str  # buy | sell | swap
    source_wallet: str
    market_cap_usd: Optional[float]
    liquidity_usd: Optional[float]
    pool_source: Optional[str]
    pool_age_seconds: Optional[int]

    # Security
    security_approved: bool
    security_score: float
    risk_level: str
    lp_locked: Optional[bool]
    is_honeypot: Optional[bool]
    mint_revoked: Optional[bool]
    top10_concentration: Optional[float]
    rug_percent: Optional[float]
    holders_count: Optional[int]
    warnings: list
    block_reasons: list

    # Performance
    trigger_latency_ms: float
    security_latency_ms: float
    total_latency_ms: float
    observed_at: float
    signature: str
    simulated: bool = True


class TelegramNotifier:
    """
    Envia alertas formatados para o Telegram.
    Usa a Bot API HTTP diretamente (sem dependencia de biblioteca).
    """

    BASE_URL = "https://api.telegram.org"

    def __init__(self):
        self.bot_token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self._client: Optional[httpx.AsyncClient] = None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._worker_task: Optional[asyncio.Task] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    def _build_message(self, alert: AlertPayload) -> str:
        """Constroi mensagem formatada com HTML para o Telegram."""
        ts = time.strftime("%H:%M:%S", time.localtime(alert.observed_at))
        action_emoji = {"buy": "BUY", "sell": "SELL", "swap": "SWAP"}.get(
            alert.action.lower(), alert.action.upper()
        )
        security_emoji = "OK" if alert.security_approved else "X"
        mc_str = f"${alert.market_cap_usd:,.0f}" if alert.market_cap_usd else "N/D"
        liq_str = f"${alert.liquidity_usd:,.0f}" if alert.liquidity_usd else "N/D"
        pool_age_str = (
            f"{alert.pool_age_seconds}s" if alert.pool_age_seconds is not None else "N/D"
        )
        top10_str = (
            f"{alert.top10_concentration:.1%}" if alert.top10_concentration is not None else "N/D"
        )
        rug_str = (
            f"{alert.rug_percent:.1f}%" if alert.rug_percent is not None else "N/D"
        )
        holders_str = str(alert.holders_count) if alert.holders_count else "N/D"
        mode_str = "[SIMULACAO]" if alert.simulated else "[EXECUCAO REAL]"

        warnings_str = ""
        if alert.warnings:
            warnings_str = "\nAvisos: " + " | ".join(alert.warnings)

        block_str = ""
        if alert.block_reasons:
            block_str = "\nBLOQUEIOS: " + " | ".join(alert.block_reasons)

        msg = (
            f"SHADOW BOT SOLANA - {mode_str}\n"
            f"Hora: {ts} | Acao: {action_emoji}\n"
            f"\n"
            f"TOKEN\n"
            f"Nome: {alert.token_name}\n"
            f"Mint: {alert.token_mint[:20]}...\n"
            f"Pool: {alert.pool_source or 'N/D'} | Idade: {pool_age_str}\n"
            f"\n"
            f"MERCADO\n"
            f"Market Cap: {mc_str}\n"
            f"Liquidez: {liq_str}\n"
            f"\n"
            f"SEGURANCA - {security_emoji} {alert.risk_level} (Score: {alert.security_score:.2f})\n"
            f"LP Lock/Burn: {'SIM' if alert.lp_locked else 'NAO' if alert.lp_locked is False else 'N/D'}\n"
            f"Honeypot: {'NAO' if alert.is_honeypot is False else 'SIM' if alert.is_honeypot else 'N/D'}\n"
            f"Mint Revoked: {'SIM' if alert.mint_revoked else 'NAO' if alert.mint_revoked is False else 'N/D'}\n"
            f"Top10 Holders: {top10_str}\n"
            f"Rug%: {rug_str} | Holders: {holders_str}\n"
            f"{warnings_str}{block_str}\n"
            f"\n"
            f"PERFORMANCE\n"
            f"Deteccao: {alert.trigger_latency_ms:.0f}ms\n"
            f"Seguranca: {alert.security_latency_ms:.0f}ms\n"
            f"Total: {alert.total_latency_ms:.0f}ms\n"
            f"\n"
            f"Sig: {alert.signature[:20]}..."
        )
        return msg

    async def _send_raw(self, text: str) -> bool:
        """Envia mensagem de texto para o Telegram."""
        if not self.bot_token or not self.chat_id:
            logger.warning("[Telegram] Bot token ou chat_id nao configurados.")
            return False

        client = await self._get_client()
        url = f"{self.BASE_URL}/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"[Telegram] Falha ao enviar mensagem: {e}")
            return False

    async def send_alert(self, alert: AlertPayload) -> bool:
        """Envia um alerta de sinal para o Telegram."""
        text = self._build_message(alert)
        success = await self._send_raw(text)
        if success:
            logger.info(
                f"[Telegram] Alerta enviado | token={alert.token_mint[:12]}... | "
                f"action={alert.action} | approved={alert.security_approved}"
            )
        return success

    async def send_startup_message(self) -> bool:
        """Notifica inicio do bot no Telegram."""
        msg = (
            "SHADOW BOT SOLANA - INICIADO\n"
            f"Carteira monitorada: {settings.target_wallet[:20]}...\n"
            f"Modo: {'SIMULACAO' if settings.simulation_mode else 'REAL'}\n"
            f"Polling: {settings.polling_interval_sec}s\n"
            f"MC Max Entrada: ${settings.max_market_cap_entry_usd:,.0f}\n"
            f"Liq. Minima: ${settings.min_liquidity_usd:,.0f}\n"
            f"Top10 Max: {settings.max_top10_holder_concentration:.0%}\n"
            f"Rug% Max: {settings.max_rug_percent:.0f}%"
        )
        return await self._send_raw(msg)

    async def send_error(self, error_msg: str) -> bool:
        """Notifica um erro critico."""
        msg = f"SHADOW BOT - ERRO CRITICO\n{error_msg}"
        return await self._send_raw(msg)

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        logger.info("[Telegram] Notifier encerrado.")
