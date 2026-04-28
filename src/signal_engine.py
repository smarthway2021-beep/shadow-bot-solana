"""
signal_engine.py - Motor de Sinais Shadow Bot

Integra PatternAnalyzer + SecurityAnalyzer para produzir
sinais qualificados em modo simulacao.

Fluxo:
  HeliusClient -> transactions -> PatternAnalyzer -> TokenPattern
  TokenPattern -> SecurityAnalyzer -> security_score
  security_score >= threshold -> TelegramNotifier -> SINAL
"""

import asyncio
import logging
import time
from typing import Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


class SignalEngine:
    """
    Orquestra o pipeline completo de deteccao de sinais.
    
    Modo Simulacao: Nenhuma ordem real e executada.
    Apenas monitora, analisa e alerta via Telegram.
    """

    def __init__(
        self,
        helius_client,
        pattern_analyzer,
        security_analyzer,
        telegram_notifier,
        config: dict = None,
    ):
        self.helius = helius_client
        self.pattern = pattern_analyzer
        self.security = security_analyzer
        self.telegram = telegram_notifier
        self.config = config or {}

        # Thresholds
        self.min_security_score = self.config.get('min_security_score', 60)
        self.min_confidence = self.config.get('min_confidence', 0.65)

        # Estado
        self.running = False
        self.processed_txs = set()
        self.signals_today: List[dict] = []
        self.session_start = time.time()

        # Contadores
        self.stats = {
            'txs_processed': 0,
            'patterns_detected': 0,
            'security_passed': 0,
            'security_failed': 0,
            'signals_sent': 0,
            'errors': 0,
        }

    async def start(self):
        """Inicia o motor de sinais."""
        self.running = True
        logger.info("[ENGINE] Shadow Bot Signal Engine iniciado")
        logger.info(f"[ENGINE] Threshold seguranca: {self.min_security_score}/100")
        logger.info(f"[ENGINE] Threshold confianca: {self.min_confidence:.0%}")

        await self.telegram.send_message(
            f"Shadow Bot ONLINE\n"
            f"Modo: SIMULACAO\n"
            f"Alvo: 4vw54BmA...9Ud9\n"
            f"Estrategia: Probe-buy + Axiom\n"
            f"Threshold: Score >= {self.min_security_score} + Conf >= {self.min_confidence:.0%}\n"
            f"Iniciado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        )

        try:
            await self._monitoring_loop()
        except asyncio.CancelledError:
            logger.info("[ENGINE] Loop cancelado")
        except Exception as e:
            logger.error(f"[ENGINE] Erro fatal: {e}")
            await self.telegram.send_message(f"ERRO FATAL no bot: {e}")
        finally:
            await self.stop()

    async def stop(self):
        """Para o motor e envia resumo."""
        self.running = False
        uptime = time.time() - self.session_start
        uptime_str = f"{uptime/3600:.1f}h"

        summary = (
            f"Shadow Bot OFFLINE\n"
            f"Uptime: {uptime_str}\n"
            f"Transacoes: {self.stats['txs_processed']}\n"
            f"Padroes: {self.stats['patterns_detected']}\n"
            f"Sinais emitidos: {self.stats['signals_sent']}\n"
            f"Erros: {self.stats['errors']}"
        )
        logger.info(f"[ENGINE] {summary}")
        await self.telegram.send_message(summary)

    async def _monitoring_loop(self):
        """Loop principal de monitoramento."""
        poll_interval = self.config.get('poll_interval', 5)  # segundos
        cleanup_interval = 60  # limpar probes expirados a cada 60s
        last_cleanup = time.time()
        last_heartbeat = time.time()
        heartbeat_interval = 3600  # 1h

        logger.info(f"[ENGINE] Monitorando com intervalo de {poll_interval}s")

        while self.running:
            try:
                # Busca transacoes recentes da carteira alvo
                txs = await self.helius.get_recent_transactions(
                    wallet=self.config.get('target_wallet'),
                    limit=20
                )

                for tx in txs:
                    sig = tx.get('signature', '')
                    if sig in self.processed_txs:
                        continue

                    self.processed_txs.add(sig)
                    # Evita crescimento ilimitado do set
                    if len(self.processed_txs) > 10000:
                        # Remove os mais antigos (metade)
                        old = list(self.processed_txs)[:5000]
                        for o in old:
                            self.processed_txs.discard(o)

                    self.stats['txs_processed'] += 1
                    await self._process_transaction(tx)

                # Limpeza periodica de probes expirados
                now = time.time()
                if now - last_cleanup > cleanup_interval:
                    self.pattern.cleanup_expired_probes()
                    last_cleanup = now

                # Heartbeat periodico
                if now - last_heartbeat > heartbeat_interval:
                    await self._send_heartbeat()
                    last_heartbeat = now

                await asyncio.sleep(poll_interval)

            except Exception as e:
                self.stats['errors'] += 1
                logger.error(f"[ENGINE] Erro no loop: {e}")
                await asyncio.sleep(poll_interval * 2)

    async def _process_transaction(self, tx: dict):
        """Processa uma transacao pelo pipeline completo."""
        try:
            # 1. Analisa padrao
            signal = self.pattern.analyze_transaction(tx)

            if signal is None:
                return

            self.stats['patterns_detected'] += 1
            logger.info(f"[ENGINE] Padrao detectado: {signal.token_symbol or signal.token_address[:12]}")

            # 2. Verifica seguranca do contrato
            token_addr = signal.token_address
            security_result = await self.security.check_token(token_addr)
            security_score = security_result.get('score', 0)

            security_summary = self._format_security_summary(security_result)

            if security_score < self.min_security_score:
                self.stats['security_failed'] += 1
                logger.warning(
                    f"[ENGINE] Token REPROVADO na seguranca: {signal.token_symbol} "
                    f"| Score: {security_score}/100"
                )
                # Notifica rejeicao (opcional, pode comentar para reduzir spam)
                await self.telegram.send_message(
                    f"SINAL REJEITADO [SIMULACAO]\n"
                    f"Token: {signal.token_symbol or token_addr[:12]}\n"
                    f"Motivo: Score seguranca {security_score}/100 < {self.min_security_score}\n"
                    f"Detalhes: {security_summary}"
                )
                return

            self.stats['security_passed'] += 1

            # 3. Emite sinal qualificado
            await self._emit_signal(signal, security_result)

        except Exception as e:
            self.stats['errors'] += 1
            logger.error(f"[ENGINE] Erro ao processar tx: {e}")

    async def _emit_signal(self, signal, security_result: dict):
        """Emite sinal qualificado via Telegram."""
        self.stats['signals_sent'] += 1

        security_score = security_result.get('score', 0)
        security_summary = self._format_security_summary(security_result)

        # Formata mensagem completa
        pattern_msg = self.pattern.format_signal_message(signal)

        full_msg = (
            f"{pattern_msg}\n"
            f"{'=' * 35}\n"
            f"SEGURANCA: {security_score}/100\n"
            f"{security_summary}\n"
            f"{'=' * 35}\n"
            f"Sinal #{self.stats['signals_sent']} | "
            f"{datetime.now().strftime('%H:%M:%S')}"
        )

        await self.telegram.send_message(full_msg)

        # Registra sinal
        self.signals_today.append({
            'token': signal.token_symbol or signal.token_address[:12],
            'confidence': signal.confidence_score,
            'security': security_score,
            'timestamp': time.time(),
            'mc': signal.market_cap_usd,
        })

        logger.info(
            f"[SINAL] {signal.token_symbol} | "
            f"Conf: {signal.confidence_score:.0%} | "
            f"Seg: {security_score}/100 | "
            f"MC: ${signal.market_cap_usd:,.0f}"
        )

    def _format_security_summary(self, security_result: dict) -> str:
        """Formata resumo de seguranca."""
        checks = security_result.get('checks', {})
        lines = []
        for check, passed in checks.items():
            icon = 'OK' if passed else 'FAIL'
            lines.append(f"  [{icon}] {check}")
        return "\n".join(lines) if lines else "  Sem dados de seguranca"

    async def _send_heartbeat(self):
        """Envia heartbeat periodico com estatisticas."""
        uptime = time.time() - self.session_start
        stats = self.pattern.get_stats()

        msg = (
            f"HEARTBEAT Shadow Bot\n"
            f"Uptime: {uptime/3600:.1f}h\n"
            f"TXs: {self.stats['txs_processed']}\n"
            f"Probes ativos: {stats['active_probes']}\n"
            f"Sinais hoje: {self.stats['signals_sent']}\n"
            f"Status: RODANDO"
        )
        await self.telegram.send_message(msg)
        logger.info(f"[ENGINE] Heartbeat enviado")

    def get_full_stats(self) -> dict:
        """Retorna estatisticas completas."""
        pattern_stats = self.pattern.get_stats()
        return {
            'engine': self.stats,
            'pattern': pattern_stats,
            'uptime_seconds': time.time() - self.session_start,
            'signals_today': len(self.signals_today),
        }
