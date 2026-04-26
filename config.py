"""
config.py - Shadow Bot Solana
Gerenciamento de configuracoes via variaveis de ambiente (.env)
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Carteira alvo ──────────────────────────────────────────────────
    target_wallet: str = Field(
        default="4vw54BmAogeRV3vPKWyFet5yf8DTLcREzdSzx4rw9Ud9",
        description="Carteira Solana a ser monitorada (decu / kingdecu.sol)"
    )

    # ── Helius RPC ──────────────────────────────────────────────────────
    helius_api_key: str = Field(default="", description="Chave API Helius")
    helius_webhook_secret: str = Field(default="", description="Secret do webhook Helius")
    polling_interval_sec: float = Field(default=0.5, description="Intervalo de polling em segundos")
    rpc_max_signatures: int = Field(default=20, description="Max assinaturas por consulta RPC")

    # ── Jito ────────────────────────────────────────────────────────────
    jito_bundle_url: str = Field(
        default="https://mainnet.block-engine.jito.wtf/api/v1/bundles",
        description="URL do block engine Jito"
    )
    jito_tip_lamports: int = Field(default=10000, description="Tip em lamports para bundles Jito")

    # ── GoPlus Security ─────────────────────────────────────────────────
    goplus_api_url: str = Field(
        default="https://api.gopluslabs.io/api/v1/solana/token_security",
        description="Endpoint GoPlus para Solana"
    )

    # ── Telegram ────────────────────────────────────────────────────────
    telegram_bot_token: str = Field(default="", description="Token do bot Telegram")
    telegram_chat_id: str = Field(default="", description="Chat ID do Telegram")

    # ── Filtros de Seguranca Anti-Rug ───────────────────────────────────
    max_market_cap_entry_usd: float = Field(
        default=100_000.0,
        description="Market cap maximo na entrada (USD) - decu opera 99.34% abaixo de 100K"
    )
    min_liquidity_usd: float = Field(
        default=500.0,
        description="Liquidez minima da pool para considerar entrada"
    )
    max_top10_holder_concentration: float = Field(
        default=0.35,
        description="Concentracao maxima dos top 10 holders (35%)"
    )
    min_pool_age_seconds: int = Field(
        default=30,
        description="Idade minima da pool em segundos antes de considerar entrada"
    )
    require_lp_locked_or_burned: bool = Field(
        default=True,
        description="Exige LP travado ou queimado"
    )
    require_mint_revoked: bool = Field(
        default=True,
        description="Exige mint authority revogada"
    )
    block_honeypot: bool = Field(
        default=True,
        description="Bloqueia tokens com risco de honeypot"
    )
    max_rug_percent: float = Field(
        default=15.0,
        description="Rug % maximo aceito (GMGN)"
    )

    # ── Modo de Operacao ─────────────────────────────────────────────────
    simulation_mode: bool = Field(
        default=True,
        description="True = apenas alertas, False = execucao real (CUIDADO!)"
    )
    log_level: str = Field(default="INFO", description="Nivel de log")
    db_path: str = Field(default="data/shadow_bot.db", description="Caminho do banco SQLite")
    webhook_port: int = Field(default=8000, description="Porta do servidor de webhook Helius")

    @property
    def helius_rpc_url(self) -> str:
        return f"https://mainnet.helius-rpc.com/?api-key={self.helius_api_key}"

    @property
    def helius_wss_url(self) -> str:
        return f"wss://mainnet.helius-rpc.com/?api-key={self.helius_api_key}"


# Instancia global de configuracoes
settings = Settings()
