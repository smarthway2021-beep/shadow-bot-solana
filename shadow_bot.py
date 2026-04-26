"""
shadow_bot.py - Shadow Bot Solana
Orquestrador principal: conecta Helius -> SecurityAnalyzer -> TelegramNotifier.

MODO SIMULACAO: apenas monitora e alerta. Nenhuma ordem real e executada.

Uso:
    python shadow_bot.py

Variaveis de ambiente (.env):
    HELIUS_API_KEY=...
    TELEGRAM_BOT_TOKEN=...
    TELEGRAM_CHAT_ID=...
    SIMULATION_MODE=true
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Optional

from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Adiciona o diretorio raiz ao path para imports relativos
sys.path.insert(0, str(Path(__file__).parent))

from config import settings
from src.helius_client import HeliusRPCClient, RawTransaction
from src.security_analyzer import SecurityAnalyzer, SecurityReport, RiskLevel
from src.telegram_notifier import TelegramNotifier, AlertPayload

console = Console()


class ShadowBot:
    """
    Orquestrador principal do Shadow Bot.

    Fluxo:
    1. HeliusRPCClient faz polling continuo da carteira alvo
    2. Para cada tx de BUY detectada:
       a. Extrai o mint do token comprado
       b. SecurityAnalyzer verifica o contrato via GoPlus
       c. TelegramNotifier envia alerta com todos os dados
    3. Para SELL: apenas registra e alerta (sem filtro de seguranca)
    """

    def __init__(self):
        self.helius = HeliusRPCClient()
        self.security = SecurityAnalyzer()
        self.telegram = TelegramNotifier()
        self._running = False
        self._stats = {
            "total_txs": 0,
            "buys_detected": 0,
            "sells_detected": 0,
            "approved": 0,
            "blocked": 0,
            "alerts_sent": 0,
            "started_at": time.time(),
        }

    async def _process_buy(
        self,
        tx: RawTransaction,
        mint: str,
        t_start: float,
    ) -> None:
        """Processa um sinal de BUY: analisa seguranca e envia alerta."""
        trigger_latency = (time.perf_counter() - t_start) * 1000

        # Analise de seguranca
        t_sec = time.perf_counter()
        report: SecurityReport = await self.security.analyze(mint)
        security_latency = (time.perf_counter() - t_sec) * 1000
        total_latency = trigger_latency + security_latency

        if report.approved:
            self._stats["approved"] += 1
        else:
            self._stats["blocked"] += 1

        # Loga no terminal
        status_color = "green" if report.approved else "red"
        console.print(
            f"[{status_color}]BUY[/{status_color}] | "
            f"mint={mint[:16]}... | "
            f"risk={report.risk_level} | "
            f"score={report.score:.2f} | "
            f"latency={total_latency:.0f}ms"
        )

        if report.block_reasons:
            for reason in report.block_reasons:
                console.print(f"  [red]BLOQUEADO: {reason}[/red]")
        if report.warnings:
            for w in report.warnings:
                console.print(f"  [yellow]AVISO: {w}[/yellow]")

        # Monta payload para o Telegram
        alert = AlertPayload(
            token_mint=mint,
            token_name=mint[:12] + "...",
            action="buy",
            source_wallet=settings.target_wallet,
            market_cap_usd=None,  # TODO: enriquecer com DexScreener/Jupiter
            liquidity_usd=None,   # TODO: enriquecer com DexScreener/Jupiter
            pool_source=None,     # TODO: detectar Pump.fun vs Raydium
            pool_age_seconds=None,# TODO: calcular com blockTime da pool
            security_approved=report.approved,
            security_score=report.score,
            risk_level=report.risk_level.value,
            lp_locked=report.lp_locked_or_burned,
            is_honeypot=report.is_honeypot,
            mint_revoked=report.mint_authority_revoked,
            top10_concentration=report.top10_concentration,
            rug_percent=report.rug_percent,
            holders_count=report.holders_count,
            warnings=report.warnings,
            block_reasons=report.block_reasons,
            trigger_latency_ms=trigger_latency,
            security_latency_ms=security_latency,
            total_latency_ms=total_latency,
            observed_at=tx.observed_at,
            signature=tx.signature,
            simulated=settings.simulation_mode,
        )

        # Envia alerta no Telegram
        sent = await self.telegram.send_alert(alert)
        if sent:
            self._stats["alerts_sent"] += 1

    async def _process_sell(
        self,
        tx: RawTransaction,
        mint: str,
        t_start: float,
    ) -> None:
        """Registra e alerta sobre SELL da carteira alvo."""
        total_latency = (time.perf_counter() - t_start) * 1000
        console.print(
            f"[yellow]SELL[/yellow] | "
            f"mint={mint[:16]}... | "
            f"latency={total_latency:.0f}ms"
        )

        alert = AlertPayload(
            token_mint=mint,
            token_name=mint[:12] + "...",
            action="sell",
            source_wallet=settings.target_wallet,
            market_cap_usd=None,
            liquidity_usd=None,
            pool_source=None,
            pool_age_seconds=None,
            security_approved=True,  # Sell nao precisa de filtro
            security_score=1.0,
            risk_level="N/A",
            lp_locked=None,
            is_honeypot=None,
            mint_revoked=None,
            top10_concentration=None,
            rug_percent=None,
            holders_count=None,
            warnings=[],
            block_reasons=[],
            trigger_latency_ms=total_latency,
            security_latency_ms=0,
            total_latency_ms=total_latency,
            observed_at=tx.observed_at,
            signature=tx.signature,
            simulated=settings.simulation_mode,
        )
        await self.telegram.send_alert(alert)
        self._stats["alerts_sent"] += 1

    async def _handle_transaction(self, tx: RawTransaction) -> None:
        """Roteador de transacoes: detecta acao e despacha."""
        t_start = time.perf_counter()
        self._stats["total_txs"] += 1
        action = tx.detect_action()

        if action == "buy":
            self._stats["buys_detected"] += 1
            mints = tx.extract_mints_bought()
            for mint in mints:
                await self._process_buy(tx, mint, t_start)

        elif action == "sell":
            self._stats["sells_detected"] += 1
            mints = tx.extract_mints_sold()
            for mint in mints:
                await self._process_sell(tx, mint, t_start)

        elif action == "swap":
            # Swap = vende um token e compra outro
            self._stats["buys_detected"] += 1
            self._stats["sells_detected"] += 1
            for mint in tx.extract_mints_bought():
                await self._process_buy(tx, mint, t_start)

    def _print_banner(self) -> None:
        """Exibe banner de inicializacao no terminal."""
        table = Table(title="Shadow Bot Solana - Configuracao")
        table.add_column("Parametro", style="cyan")
        table.add_column("Valor", style="white")
        table.add_row("Carteira alvo", settings.target_wallet[:20] + "...")
        table.add_row("Modo", "[yellow]SIMULACAO[/yellow]" if settings.simulation_mode else "[red]REAL[/red]")
        table.add_row("Polling interval", f"{settings.polling_interval_sec}s")
        table.add_row("MC max entrada", f"${settings.max_market_cap_entry_usd:,.0f}")
        table.add_row("Liquidez minima", f"${settings.min_liquidity_usd:,.0f}")
        table.add_row("Top10 max", f"{settings.max_top10_holder_concentration:.0%}")
        table.add_row("Rug% max", f"{settings.max_rug_percent:.0f}%")
        table.add_row("Helius API Key", "OK" if settings.helius_api_key else "[red]NAO CONFIGURADA[/red]")
        table.add_row("Telegram", "OK" if settings.telegram_bot_token else "[red]NAO CONFIGURADO[/red]")
        console.print(Panel(table, title="Shadow Bot v1.0", border_style="blue"))

    def _print_stats(self) -> None:
        """Exibe estatisticas de execucao."""
        uptime = time.time() - self._stats["started_at"]
        console.print(
            f"\n[cyan]Stats[/cyan] | "
            f"txs={self._stats['total_txs']} | "
            f"buys={self._stats['buys_detected']} | "
            f"sells={self._stats['sells_detected']} | "
            f"aprovados={self._stats['approved']} | "
            f"bloqueados={self._stats['blocked']} | "
            f"alertas={self._stats['alerts_sent']} | "
            f"uptime={uptime:.0f}s"
        )

    async def run(self) -> None:
        """Loop principal do bot."""
        self._print_banner()
        self._running = True

        logger.info(
            f"[ShadowBot] Iniciando | wallet={settings.target_wallet} | "
            f"simulation={settings.simulation_mode}"
        )

        # Notifica Telegram sobre inicio
        await self.telegram.send_startup_message()

        stats_task = asyncio.create_task(self._periodic_stats())

        try:
            async for tx in self.helius.poll_new_transactions():
                if not self._running:
                    break
                try:
                    await self._handle_transaction(tx)
                except Exception as e:
                    logger.exception(f"[ShadowBot] Erro ao processar tx {tx.signature}: {e}")

        except asyncio.CancelledError:
            logger.info("[ShadowBot] Loop cancelado.")
        except KeyboardInterrupt:
            logger.info("[ShadowBot] Interrupcao do usuario.")
        finally:
            stats_task.cancel()
            self._print_stats()
            await self.close()

    async def _periodic_stats(self) -> None:
        """Exibe estatisticas periodicamente."""
        while self._running:
            await asyncio.sleep(60)
            self._print_stats()

    async def close(self) -> None:
        self._running = False
        await self.helius.close()
        await self.security.close()
        await self.telegram.close()
        logger.info("[ShadowBot] Encerrado.")


async def main() -> None:
    bot = ShadowBot()
    await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Bot encerrado pelo usuario.[/yellow]")
