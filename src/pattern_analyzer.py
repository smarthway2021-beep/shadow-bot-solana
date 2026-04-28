"""
pattern_analyzer.py - Analisador de Padroes da Carteira Alvo (decu)
Carteira: 4vw54BmAogeRV3vPKWyFet5yf8DTLcREzdSzx4rw9Ud9

Padroes identificados via analise de 77k+ swaps no Solscan:
- Plataforma primaria: Axiom Trade
- Estrategia: Probe buy (sonda pequena) -> entrada completa
- Tamanho probe: ~0.05-0.1 SOL
- Tamanho entrada completa: 1-3 SOL (~$170-260)
- Alvo: micro-caps < 100k MC (99.34% dos trades)
- Hold medio: 21 horas
- Win rate: 62.11%
- Foco: tokens em fase de descoberta / early momentum
"""

import asyncio
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Programa Axiom Trade no Solana
AXIOM_TRADE_PROGRAM = "AXiom3T5pBqefbH3QxWfbLYKBGEQJXp6FEXKhHfP9b4"

# Parametros baseados na analise da carteira alvo
PROBE_BUY_MIN_SOL = 0.03
PROBE_BUY_MAX_SOL = 0.15
FULL_ENTRY_MIN_SOL = 0.8
FULL_ENTRY_MAX_SOL = 4.0
PROBE_TO_FULL_WINDOW_SECONDS = 300  # 5 minutos max entre probe e full entry
TARGET_MC_MAX_USD = 200_000  # micro-cap threshold
TARGET_MC_MIN_USD = 5_000    # evitar tokens mortos
AVG_HOLD_HOURS = 21
MIN_MOMENTUM_WINDOW = 60     # segundos de momentum minimo


@dataclass
class TokenPattern:
    """Representa um padrao identificado para um token."""
    token_address: str
    token_symbol: str = ""
    probe_detected: bool = False
    probe_amount_sol: float = 0.0
    probe_timestamp: float = 0.0
    full_entry_detected: bool = False
    full_entry_amount_sol: float = 0.0
    full_entry_timestamp: float = 0.0
    market_cap_usd: float = 0.0
    platform: str = ""
    confidence_score: float = 0.0
    signal_generated: bool = False
    notes: List[str] = field(default_factory=list)

    @property
    def is_probe_phase(self) -> bool:
        """Probe detectado mas full entry ainda nao."""
        if not self.probe_detected or self.full_entry_detected:
            return False
        elapsed = time.time() - self.probe_timestamp
        return elapsed < PROBE_TO_FULL_WINDOW_SECONDS

    @property
    def is_strong_signal(self) -> bool:
        """Sinal forte: probe + full entry confirmados."""
        return self.probe_detected and self.full_entry_detected and self.confidence_score >= 0.65


class PatternAnalyzer:
    """
    Analisa transacoes em tempo real buscando o padrao da carteira 'decu'.
    
    Logica principal:
    1. Detecta probe buy (compra pequena testando liquidez)
    2. Aguarda confirmacao de full entry dentro de 5 minutos
    3. Valida MC < 200k e plataforma Axiom Trade
    4. Calcula confidence score baseado em multiplos fatores
    5. Emite sinal se score >= 0.65
    """

    def __init__(self, target_wallet: str):
        self.target_wallet = target_wallet
        self.active_patterns: Dict[str, TokenPattern] = {}
        self.completed_signals: List[TokenPattern] = []
        self.stats = {
            'probes_detected': 0,
            'full_entries_detected': 0,
            'signals_emitted': 0,
            'false_probes_expired': 0,
        }

    def analyze_transaction(self, tx: dict) -> Optional[TokenPattern]:
        """
        Analisa uma transacao e retorna TokenPattern se sinal detectado.
        
        Args:
            tx: dict com campos:
                - signature: str
                - timestamp: float (unix)
                - token_address: str
                - token_symbol: str
                - amount_sol: float
                - amount_usd: float
                - type: 'buy' | 'sell'
                - platform: str
                - market_cap_usd: float
        
        Returns:
            TokenPattern se sinal gerado, None caso contrario
        """
        if tx.get('type') != 'buy':
            return None

        token_addr = tx.get('token_address', '')
        amount_sol = tx.get('amount_sol', 0)
        platform = tx.get('platform', '')
        mc = tx.get('market_cap_usd', 0)

        # Valida MC dentro do alvo
        if mc and (mc < TARGET_MC_MIN_USD or mc > TARGET_MC_MAX_USD):
            return None

        pattern = self.active_patterns.get(token_addr)

        # === DETECTA PROBE BUY ===
        if PROBE_BUY_MIN_SOL <= amount_sol <= PROBE_BUY_MAX_SOL:
            if pattern is None:
                pattern = TokenPattern(
                    token_address=token_addr,
                    token_symbol=tx.get('token_symbol', ''),
                    probe_detected=True,
                    probe_amount_sol=amount_sol,
                    probe_timestamp=tx.get('timestamp', time.time()),
                    market_cap_usd=mc,
                    platform=platform,
                )
                pattern.notes.append(f"Probe buy: {amount_sol:.4f} SOL @ MC ${mc:,.0f}")
                self.active_patterns[token_addr] = pattern
                self.stats['probes_detected'] += 1
                logger.info(f"[PROBE] {tx.get('token_symbol',token_addr[:8])} | {amount_sol:.4f} SOL | MC ${mc:,.0f}")

        # === DETECTA FULL ENTRY ===
        elif FULL_ENTRY_MIN_SOL <= amount_sol <= FULL_ENTRY_MAX_SOL:
            if pattern and pattern.is_probe_phase:
                pattern.full_entry_detected = True
                pattern.full_entry_amount_sol = amount_sol
                pattern.full_entry_timestamp = tx.get('timestamp', time.time())
                pattern.notes.append(f"Full entry: {amount_sol:.4f} SOL")
                self.stats['full_entries_detected'] += 1

                # Calcula confidence score
                pattern.confidence_score = self._calculate_confidence(pattern, tx)

                logger.info(
                    f"[FULL ENTRY] {pattern.token_symbol or token_addr[:8]} | "
                    f"{amount_sol:.4f} SOL | Score: {pattern.confidence_score:.2f}"
                )

                if pattern.is_strong_signal:
                    pattern.signal_generated = True
                    self.completed_signals.append(pattern)
                    self.stats['signals_emitted'] += 1
                    del self.active_patterns[token_addr]
                    return pattern

        return None

    def _calculate_confidence(self, pattern: TokenPattern, tx: dict) -> float:
        """
        Score de 0.0 a 1.0 baseado nos padroes do alvo.
        
        Fatores positivos:
        - Plataforma = Axiom (+0.30)
        - MC < 50k (+0.20) ou < 100k (+0.10)
        - Ratio probe/full entry coerente (+0.15)
        - Tempo entre probe e full < 2 min (+0.10)
        - Token nao visto antes (fresh) (+0.10)
        - Full entry >= 1 SOL (+0.10)
        """
        score = 0.0

        # Plataforma Axiom
        platform = pattern.platform.lower()
        if 'axiom' in platform:
            score += 0.30
        elif 'padre' in platform or 'pumpfun' in platform or 'raydium' in platform:
            score += 0.10

        # Market cap
        mc = pattern.market_cap_usd
        if mc and mc < 50_000:
            score += 0.20
        elif mc and mc < 100_000:
            score += 0.10

        # Ratio probe/full (probe deve ser 2-10% do full)
        if pattern.probe_amount_sol > 0 and pattern.full_entry_amount_sol > 0:
            ratio = pattern.probe_amount_sol / pattern.full_entry_amount_sol
            if 0.02 <= ratio <= 0.15:
                score += 0.15

        # Velocidade: probe -> full entry
        if pattern.probe_timestamp and pattern.full_entry_timestamp:
            elapsed = pattern.full_entry_timestamp - pattern.probe_timestamp
            if elapsed < 120:
                score += 0.10

        # Tamanho do full entry
        if pattern.full_entry_amount_sol >= 1.0:
            score += 0.10

        # Token sem historico recente (fresh)
        if pattern.token_address not in [s.token_address for s in self.completed_signals[-20:]]:
            score += 0.10

        return min(score, 1.0)

    def cleanup_expired_probes(self):
        """Remove probes que expiraram sem full entry."""
        now = time.time()
        expired = [
            addr for addr, p in self.active_patterns.items()
            if p.probe_detected and not p.full_entry_detected
            and (now - p.probe_timestamp) > PROBE_TO_FULL_WINDOW_SECONDS
        ]
        for addr in expired:
            logger.debug(f"[EXPIRED] Probe expirado: {self.active_patterns[addr].token_symbol or addr[:8]}")
            del self.active_patterns[addr]
            self.stats['false_probes_expired'] += 1

    def get_stats(self) -> dict:
        """Retorna estatisticas do analisador."""
        return {
            **self.stats,
            'active_probes': len(self.active_patterns),
            'total_signals': len(self.completed_signals),
        }

    def format_signal_message(self, pattern: TokenPattern) -> str:
        """Formata mensagem de sinal para envio via Telegram."""
        probe_time = datetime.fromtimestamp(pattern.probe_timestamp).strftime('%H:%M:%S')
        full_time = datetime.fromtimestamp(pattern.full_entry_timestamp).strftime('%H:%M:%S')
        elapsed = pattern.full_entry_timestamp - pattern.probe_timestamp

        stars = int(pattern.confidence_score * 5)
        star_display = 'STAR' * stars + 'star' * (5 - stars)

        msg = (
            f"SINAL SHADOW BOT [SIMULACAO]\n"
            f"{'=' * 35}\n"
            f"Token: {pattern.token_symbol or pattern.token_address[:12]}\n"
            f"Endereco: {pattern.token_address[:20]}...\n"
            f"MC Atual: ${pattern.market_cap_usd:,.0f}\n"
            f"Plataforma: {pattern.platform}\n"
            f"{'=' * 35}\n"
            f"PADRAO DETECTADO:\n"
            f"  Probe: {pattern.probe_amount_sol:.4f} SOL ({probe_time})\n"
            f"  Full:  {pattern.full_entry_amount_sol:.4f} SOL ({full_time})\n"
            f"  Delta: {elapsed:.0f}s\n"
            f"{'=' * 35}\n"
            f"Confianca: {pattern.confidence_score:.0%} [{star_display}]\n"
            f"\nNOTAS:\n" + "\n".join(f"  - {n}" for n in pattern.notes) + "\n"
            f"\n[MODO SIMULACAO - SEM ORDEM REAL]"
        )
        return msg
