# Shadow Bot Solana

> Modo simulacao — monitoramento e alertas apenas. Nenhuma ordem real executada.

Shadow Bot para analise de padroes algoritmicos em carteiras Solana de alta consistencia.
Integra Helius RPC, GoPlus Security API e alertas via Telegram.

## Carteira Alvo Analisada

| Parametro | Valor |
|---|---|
| Wallet | `4vw54BmAogeRV3vPKWyFet5yf8DTLcREzdSzx4rw9Ud9` |
| Label | decu (kingdecu.sol) |
| Win Rate (7D) | 62.11% |
| Hold Time Medio | 21 horas |
| 7D PnL Realizado | +$17.3K (+15.21%) |
| MC Entrada | 99.34% abaixo de $100K |
| Tokens operados (7D) | 604 tokens |

## Estrutura do Projeto

```
shadow-bot-solana/
  shadow_bot.py          # Orquestrador principal
  config.py              # Configuracoes via .env
  requirements.txt       # Dependencias Python
  src/
    helius_client.py     # Polling RPC + parse de transacoes
    security_analyzer.py # Filtros anti-rug via GoPlus
    telegram_notifier.py # Alertas formatados no Telegram
```

## Instalacao

```bash
# Clone o repositorio
git clone https://github.com/smarthway2021-beep/shadow-bot-solana.git
cd shadow-bot-solana

# Crie ambiente virtual
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows

# Instale dependencias
pip install -r requirements.txt
```

## Configuracao

Crie um arquivo `.env` na raiz:

```env
# Helius RPC (obrigatorio)
HELIUS_API_KEY=sua_chave_aqui

# Telegram (obrigatorio para alertas)
TELEGRAM_BOT_TOKEN=seu_token_aqui
TELEGRAM_CHAT_ID=seu_chat_id_aqui

# Modo de operacao (SEMPRE true na fase 1)
SIMULATION_MODE=true

# Carteira monitorada
TARGET_WALLET=4vw54BmAogeRV3vPKWyFet5yf8DTLcREzdSzx4rw9Ud9

# Filtros anti-rug (valores baseados no perfil decu)
MAX_MARKET_CAP_ENTRY_USD=100000
MIN_LIQUIDITY_USD=500
MAX_TOP10_HOLDER_CONCENTRATION=0.35
MIN_POOL_AGE_SECONDS=30
REQUIRE_LP_LOCKED_OR_BURNED=true
REQUIRE_MINT_REVOKED=true
BLOCK_HONEYPOT=true
MAX_RUG_PERCENT=15.0
```

## Como obter as chaves

### Helius API Key
1. Acesse https://helius.xyz
2. Crie uma conta gratuita
3. Gere uma API Key no dashboard

### Telegram Bot Token + Chat ID
1. No Telegram, converse com `@BotFather`
2. Use `/newbot` para criar um bot
3. Copie o token gerado
4. Para obter o chat_id: envie uma mensagem para o bot e acesse:
   `https://api.telegram.org/bot<TOKEN>/getUpdates`

## Execucao

```bash
python shadow_bot.py
```

## Filtros de Seguranca (Anti-Rug)

| Filtro | Criterio | Acao |
|---|---|---|
| Honeypot | Detectado | BLOQUEIO AUTOMATICO |
| Blacklist | Token na lista GoPlus | BLOQUEIO AUTOMATICO |
| Freeze Authority | Ativa | BLOQUEIO AUTOMATICO |
| LP Lock/Burn | Nao travado | BLOQUEIO |
| Mint Authority | Nao revogada | BLOQUEIO |
| Top10 Holders | Acima de 60% | BLOQUEIO |
| Top10 Holders | Entre 35%-60% | AVISO |
| Rug% | Acima de 15% | AVISO |
| Holders | Menos de 30 | AVISO |

## Alerta Telegram (Exemplo)

```
SHADOW BOT SOLANA - [SIMULACAO]
Hora: 17:42:31 | Acao: BUY

TOKEN
Nome: 4vw54BmAogeR...
Mint: ErfTQcL7Mmod...
Pool: Pump.fun | Idade: 45s

MERCADO
Market Cap: $4,200
Liquidez: $1,850

SEGURANCA - OK SAFE (Score: 0.85)
LP Lock/Burn: SIM
Honeypot: NAO
Mint Revoked: SIM
Top10 Holders: 18.3%
Rug%: 8.2% | Holders: 87

PERFORMANCE
Deteccao: 312ms
Seguranca: 156ms
Total: 468ms

Sig: 3xK9mP2vQrLt...
```

## Roadmap

- [x] Fase 1: Monitoramento + Alertas (modo simulacao)
- [ ] Fase 2: Enriquecimento de MC/Liquidez via DexScreener
- [ ] Fase 3: Banco SQLite para historico e analise de padroes
- [ ] Fase 4: Servidor webhook Helius (FastAPI)
- [ ] Fase 5: Integracao Jito Bundles (execucao real - opcional)

## Aviso Legal

Este projeto e exclusivamente para fins educacionais e de pesquisa.
Nao constitui conselho financeiro. Use por sua conta e risco.
Nenhuma ordem real e executada no modo padrao (SIMULATION_MODE=true).
