"""
setup.py - Shadow Bot Solana
Script de configuracao e teste inicial.
Execute: python setup.py

Faz:
1. Verifica Python 3.11+
2. Cria arquivo .env com as chaves fornecidas
3. Testa conexao com Helius RPC
4. Testa conexao com Telegram (envia mensagem de teste)
5. Testa monitoramento da carteira alvo
"""
import sys
import os
import asyncio
import json

# ============================================================
# CONFIGURACOES DE TESTE - Altere aqui antes de rodar
# ============================================================
HELIUS_API_KEY = "3436c74c-7d79-46bf-a78b-9acc7548b08f"
TELEGRAM_BOT_TOKEN = "8508360616:AAF1sc8PzkkRcPWT5H-TgGusaKJXw4BHbyU"
TELEGRAM_CHAT_ID = "8751092942"
TARGET_WALLET = "4vw54BmAogeRV3vPKWyFet5yf8DTLcREzdSzx4rw9Ud9"
# ============================================================

def check_python_version():
    major, minor = sys.version_info[:2]
    print(f"Python {major}.{minor} detectado")
    if major < 3 or (major == 3 and minor < 10):
        print("ERRO: Python 3.10+ necessario")
        sys.exit(1)
    print("OK: Versao Python compativel")

def create_env_file():
    env_path = ".env"
    if os.path.exists(env_path):
        print(f"Arquivo .env ja existe - nao sobrescrevendo")
        return

    content = f"""# Shadow Bot Solana - Configuracao
HELIUS_API_KEY={HELIUS_API_KEY}
TELEGRAM_BOT_TOKEN={TELEGRAM_BOT_TOKEN}
TELEGRAM_CHAT_ID={TELEGRAM_CHAT_ID}
TARGET_WALLET={TARGET_WALLET}
SIMULATION_MODE=true
POLLING_INTERVAL_SEC=1.0
RPC_MAX_SIGNATURES=20
MAX_MARKET_CAP_ENTRY_USD=100000
MIN_LIQUIDITY_USD=500
MAX_TOP10_HOLDER_CONCENTRATION=0.35
MIN_POOL_AGE_SECONDS=20
REQUIRE_LP_LOCKED_OR_BURNED=true
REQUIRE_MINT_REVOKED=true
BLOCK_HONEYPOT=true
MAX_RUG_PERCENT=15.0
LOG_LEVEL=INFO
DB_PATH=data/shadow_bot.db
"""
    with open(env_path, "w") as f:
        f.write(content)
    print("OK: Arquivo .env criado com sucesso")

async def test_helius():
    try:
        import httpx
        url = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
        payload = {
            "jsonrpc": "2.0",
            "id": "setup-test",
            "method": "getSignaturesForAddress",
            "params": [TARGET_WALLET, {"limit": 3}]
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload)
            data = r.json()
            if "result" in data and data["result"]:
                sigs = data["result"]
                print(f"OK: Helius RPC funcionando | Ultimas {len(sigs)} txs detectadas")
                for s in sigs[:3]:
                    sig = s.get("signature", "")[:20]
                    slot = s.get("slot", "")
                    print(f"   -> {sig}... | slot={slot}")
                return True
            else:
                print(f"ERRO Helius: {data.get('error', 'Resposta vazia')}")
                return False
    except ImportError:
        print("ERRO: httpx nao instalado. Rode: pip install httpx")
        return False
    except Exception as e:
        print(f"ERRO Helius: {e}")
        return False

async def test_telegram():
    try:
        import httpx
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        msg = (
            "SHADOW BOT SOLANA\n"
            "Teste de conexao bem-sucedido!\n\n"
            f"Carteira monitorada:\n{TARGET_WALLET[:20]}...\n\n"
            "Sistema pronto para iniciar monitoramento.\n"
            "Execute: python shadow_bot.py"
        )
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload)
            data = r.json()
            if data.get("ok"):
                print("OK: Telegram funcionando | Mensagem de teste enviada")
                return True
            else:
                print(f"ERRO Telegram: {data.get('description', 'Erro desconhecido')}")
                return False
    except Exception as e:
        print(f"ERRO Telegram: {e}")
        return False

async def test_monitor_loop():
    """Roda o monitor por 60 segundos e exibe qualquer tx nova detectada."""
    try:
        import httpx
        print("\nIniciando monitor de teste por 30 segundos...")
        print(f"Monitorando: {TARGET_WALLET}")
        print("Aguardando transacoes...\n")

        url = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
        seen = set()
        
        # Carrega assinaturas existentes primeiro
        payload = {
            "jsonrpc": "2.0", "id": "init",
            "method": "getSignaturesForAddress",
            "params": [TARGET_WALLET, {"limit": 20}]
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload)
            initial = r.json().get("result", [])
            for s in initial:
                seen.add(s.get("signature"))
            print(f"   {len(seen)} transacoes existentes carregadas como baseline")

        # Polling por 30 segundos
        start = asyncio.get_event_loop().time()
        found = 0
        async with httpx.AsyncClient(timeout=10.0) as client:
            while asyncio.get_event_loop().time() - start < 30:
                await asyncio.sleep(1.0)
                payload = {
                    "jsonrpc": "2.0", "id": "poll",
                    "method": "getSignaturesForAddress",
                    "params": [TARGET_WALLET, {"limit": 10}]
                }
                r = await client.post(url, json=payload)
                sigs = r.json().get("result", [])
                for s in reversed(sigs):
                    sig = s.get("signature")
                    if sig and sig not in seen:
                        seen.add(sig)
                        found += 1
                        print(f"   NOVA TX DETECTADA! sig={sig[:20]}... | GATILHO FUNCIONANDO")
                        # Avisa no Telegram tambem
                        tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                        tg_msg = f"NOVA TX DETECTADA\nsig={sig[:30]}...\nGatilho funcionando!"
                        await client.post(tg_url, json={"chat_id": TELEGRAM_CHAT_ID, "text": tg_msg})

                elapsed = int(asyncio.get_event_loop().time() - start)
                print(f"   [{elapsed:02d}s] Polling OK | {len(seen)} txs no baseline | {found} novas", end="\r")

        print(f"\n\nResultado do monitor de teste:")
        print(f"   Novas txs detectadas em 30s: {found}")
        if found > 0:
            print("   SUCESSO: O bot esta detectando trades em tempo real!")
        else:
            print("   OK: Nenhuma tx nova em 30s (decu nao operou neste periodo - normal)")
        return True
    except Exception as e:
        print(f"ERRO no monitor: {e}")
        return False

async def main():
    print("=" * 55)
    print("  SHADOW BOT SOLANA - SETUP E TESTE")
    print("=" * 55)
    print()

    # 1. Versao Python
    print("[1/4] Verificando Python...")
    check_python_version()
    print()

    # 2. Cria .env
    print("[2/4] Criando arquivo .env...")
    create_env_file()
    print()

    # 3. Testa Helius
    print("[3/4] Testando Helius RPC...")
    helius_ok = await test_helius()
    print()

    # 4. Testa Telegram
    print("[4/4] Testando Telegram...")
    telegram_ok = await test_telegram()
    print()

    # Sumario
    print("=" * 55)
    print("RESULTADO DOS TESTES:")
    print(f"  Helius RPC:  {'OK' if helius_ok else 'FALHOU'}")
    print(f"  Telegram:    {'OK' if telegram_ok else 'FALHOU'}")
    print("=" * 55)
    print()

    if helius_ok and telegram_ok:
        print("Todos os sistemas funcionando!")
        print()
        resp = input("Rodar monitor de teste por 30s? (s/n): ").strip().lower()
        if resp == "s":
            await test_monitor_loop()
        print()
        print("Para iniciar o bot em modo simulacao:")
        print("  python shadow_bot.py")
    else:
        print("Corrija os erros acima antes de iniciar o bot.")

if __name__ == "__main__":
    asyncio.run(main())
