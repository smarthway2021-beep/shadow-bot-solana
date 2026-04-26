"""
src/security_analyzer.py - Shadow Bot Solana
Camada Anti-Cilada: verifica contratos antes de qualquer decisao.
Integra GoPlus Security API para Solana.

Filtros baseados no perfil da carteira decu (GMGN):
- 99.34% das entradas com MC < $100K
- Perdas maximas de -50% (1.16% dos trades)
- Win Rate de 62.11% com filtros rigorosos
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from config import settings


class RiskLevel(str, Enum):
    SAFE = "SAFE"
    WARNING = "WARNING"
    DANGER = "DANGER"
    BLOCKED = "BLOCKED"


@dataclass
class SecurityReport:
    mint: str
    risk_level: RiskLevel = RiskLevel.DANGER
    score: float = 0.0  # 0.0 = perigo total, 1.0 = seguro

    # Checks individuais
    lp_locked_or_burned: Optional[bool] = None
    is_honeypot: Optional[bool] = None
    mint_authority_revoked: Optional[bool] = None
    top10_concentration: Optional[float] = None
    rug_percent: Optional[float] = None
    is_blacklisted: Optional[bool] = None
    has_freeze_authority: Optional[bool] = None
    holders_count: Optional[int] = None

    warnings: List[str] = field(default_factory=list)
    block_reasons: List[str] = field(default_factory=list)

    raw_goplus: Dict[str, Any] = field(default_factory=dict)
    analysis_latency_ms: float = 0.0
    analyzed_at: float = field(default_factory=time.time)

    @property
    def approved(self) -> bool:
        """True apenas se passou por todos os filtros criticos."""
        return self.risk_level in (RiskLevel.SAFE, RiskLevel.WARNING)

    def summary(self) -> str:
        status = "APROVADO" if self.approved else "BLOQUEADO"
        lines = [
            f"[Security] {status} | mint={self.mint[:12]}...",
            f"  Score: {self.score:.2f} | Risco: {self.risk_level}",
            f"  LP Lock/Burn: {self.lp_locked_or_burned}",
            f"  Honeypot: {self.is_honeypot}",
            f"  Mint Revoked: {self.mint_authority_revoked}",
            f"  Top10 Conc.: {self.top10_concentration}",
            f"  Rug%: {self.rug_percent}",
            f"  Holders: {self.holders_count}",
        ]
        if self.warnings:
            lines.append(f"  Warnings: {', '.join(self.warnings)}")
        if self.block_reasons:
            lines.append(f"  BLOQUEIOS: {', '.join(self.block_reasons)}")
        return "\n".join(lines)


class SecurityAnalyzer:
    """
    Analisa o risco de um token Solana usando GoPlus Security API.
    Aplica os filtros heuristicos baseados no perfil da carteira decu.
    """

    GOPLUS_URL = settings.goplus_api_url

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._cache: Dict[str, SecurityReport] = {}
        self._cache_ttl_sec = 300  # 5 minutos

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(8.0, connect=4.0)
            )
        return self._client

    async def _fetch_goplus(self, mint: str) -> Dict[str, Any]:
        """Busca dados de seguranca do token na GoPlus API."""
        client = await self._get_client()
        try:
            r = await client.get(
                self.GOPLUS_URL,
                params={"contract_addresses": mint},
                headers={"accept": "application/json"},
            )
            r.raise_for_status()
            data = r.json()
            result = data.get("result", {})
            # GoPlus retorna o mint em lowercase como chave
            return result.get(mint) or result.get(mint.lower()) or {}
        except Exception as e:
            logger.warning(f"[GoPlus] Falha ao buscar {mint[:12]}...: {e}")
            return {}

    def _parse_bool(self, value: Any, true_values=None) -> Optional[bool]:
        if true_values is None:
            true_values = ("1", 1, True, "true")
        false_values = ("0", 0, False, "false", None)
        if value in true_values:
            return True
        if value in false_values:
            return False
        return None

    def _parse_float(self, value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _parse_int(self, value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _evaluate(self, report: SecurityReport) -> SecurityReport:
        """
        Aplica logica de scoring e determina risk_level.
        Scoring baseado nos filtros do perfil decu:
        - Honeypot: bloqueio automatico
        - Blacklist: bloqueio automatico
        - LP lock/burn: obrigatorio
        - Mint revoked: fortemente recomendado
        - Top10 < 35%: alerta se ultrapassar
        - Rug% < 15%: alerta se ultrapassar
        - Holders > 50: sinal positivo
        """
        score = 1.0
        block_reasons = []
        warnings = []

        # ---- BLOQUEIOS AUTOMATICOS ----
        if report.is_honeypot is True:
            block_reasons.append("HONEYPOT detectado")
            score = 0.0

        if report.is_blacklisted is True:
            block_reasons.append("Token na blacklist GoPlus")
            score = 0.0

        if report.has_freeze_authority is True:
            block_reasons.append("Freeze authority ativa (dono pode congelar tokens)")
            score = max(0.0, score - 0.4)

        # ---- CHECKS DE LP ----
        if settings.require_lp_locked_or_burned:
            if report.lp_locked_or_burned is False:
                block_reasons.append("LP NAO travado/queimado")
                score = max(0.0, score - 0.5)
            elif report.lp_locked_or_burned is None:
                warnings.append("Status LP nao determinado")
                score = max(0.0, score - 0.15)

        # ---- MINT AUTHORITY ----
        if settings.require_mint_revoked:
            if report.mint_authority_revoked is False:
                block_reasons.append("Mint authority NAO revogada (inflacao possivel)")
                score = max(0.0, score - 0.35)
            elif report.mint_authority_revoked is None:
                warnings.append("Status mint authority nao determinado")
                score = max(0.0, score - 0.1)

        # ---- CONCENTRACAO TOP 10 ----
        if report.top10_concentration is not None:
            if report.top10_concentration > settings.max_top10_holder_concentration:
                msg = f"Top10 concentracao alta: {report.top10_concentration:.1%}"
                if report.top10_concentration > 0.60:
                    block_reasons.append(msg)
                    score = max(0.0, score - 0.4)
                else:
                    warnings.append(msg)
                    score = max(0.0, score - 0.2)

        # ---- RUG PERCENT ----
        if report.rug_percent is not None:
            if report.rug_percent > settings.max_rug_percent:
                msg = f"Rug% elevado: {report.rug_percent:.1f}%"
                warnings.append(msg)
                score = max(0.0, score - 0.15)

        # ---- HOLDERS ----
        if report.holders_count is not None:
            if report.holders_count < 30:
                warnings.append(f"Poucos holders: {report.holders_count}")
                score = max(0.0, score - 0.15)

        # ---- DETERMINA RISK LEVEL ----
        report.warnings = warnings
        report.block_reasons = block_reasons

        if block_reasons:
            report.risk_level = RiskLevel.BLOCKED
            report.score = 0.0
        elif score >= 0.75:
            report.risk_level = RiskLevel.SAFE
            report.score = score
        elif score >= 0.45:
            report.risk_level = RiskLevel.WARNING
            report.score = score
        else:
            report.risk_level = RiskLevel.DANGER
            report.score = score

        return report

    async def analyze(self, mint: str) -> SecurityReport:
        """Analisa um token e retorna o SecurityReport completo."""
        t0 = time.perf_counter()

        # Checa cache
        cached = self._cache.get(mint)
        if cached and (time.time() - cached.analyzed_at) < self._cache_ttl_sec:
            logger.debug(f"[Security] Cache hit para {mint[:12]}...")
            return cached

        raw = await self._fetch_goplus(mint)

        report = SecurityReport(
            mint=mint,
            raw_goplus=raw,
        )

        # Parseia campos GoPlus Solana
        report.lp_locked_or_burned = self._parse_bool(
            raw.get("lp_locked") or raw.get("is_locked") or raw.get("lp_burned")
        )
        report.is_honeypot = self._parse_bool(
            raw.get("is_honeypot") or raw.get("honeypot")
        )
        report.mint_authority_revoked = (
            not self._parse_bool(raw.get("is_mintable"))
            if raw.get("is_mintable") is not None else None
        )
        report.has_freeze_authority = self._parse_bool(
            raw.get("is_freezable") or raw.get("freeze_authority")
        )
        report.is_blacklisted = self._parse_bool(raw.get("is_blacklisted"))

        conc = self._parse_float(
            raw.get("holder_percent_top10") or
            raw.get("top_10_holder_rate") or
            raw.get("top10_percent")
        )
        report.top10_concentration = conc

        report.rug_percent = self._parse_float(
            raw.get("rug_ratio") or raw.get("rug_percent")
        )
        report.holders_count = self._parse_int(
            raw.get("holder_count") or raw.get("holders")
        )

        # Avalia e calcula score
        report = self._evaluate(report)
        report.analysis_latency_ms = (time.perf_counter() - t0) * 1000

        # Salva no cache
        self._cache[mint] = report

        logger.info(
            f"[Security] mint={mint[:12]}... | risk={report.risk_level} | "
            f"score={report.score:.2f} | latency={report.analysis_latency_ms:.1f}ms"
        )
        return report

    async def analyze_batch(
        self, mints: List[str], concurrency: int = 5
    ) -> Dict[str, SecurityReport]:
        """Analisa varios tokens em paralelo com limite de concorrencia."""
        semaphore = asyncio.Semaphore(concurrency)

        async def analyze_with_sem(mint: str) -> tuple[str, SecurityReport]:
            async with semaphore:
                return mint, await self.analyze(mint)

        tasks = [analyze_with_sem(m) for m in mints]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            mint: report
            for mint, report in results
            if isinstance(report, SecurityReport)
        }

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        logger.info("[Security] Analyzer encerrado.")
