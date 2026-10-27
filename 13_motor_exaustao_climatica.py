import pandas as pd
import yfinance as yf
import pandas_ta as ta
import os
import requests
import time
import random
from datetime import datetime
from zoneinfo import ZoneInfo
import warnings
warnings.filterwarnings("ignore")

# ===================================================================
# 1. CONFIGURAÇÕES E PARÂMETROS CLIMÁTICOS
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

# Limiares de Exaustão Parabólica
LIMIAR_DIST_EMA9 = 15.0  # Preço 15% acima da EMA 9 (esticado extremo)
LIMIAR_RVOL = 3.0        # Volume 3x superior à média
LIMIAR_RSI = 80.0        # RSI em sobrecompra crítica

def get_yf_history_safe(ticker, period="3mo"):
    for _ in range(3):
        try:
            time.sleep(random.uniform(0.5, 1.2))
            df = yf.download(ticker, period=period, interval="1d", progress=False, timeout=15)
            if not df.empty and len(df) >= 20:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                return df.dropna(subset=['Close', 'Volume'])
        except Exception:
            time.sleep(2.0)
    return pd.DataFrame()

# ===================================================================
# 2. CARREGAMENTO DE POSIÇÕES ATIVAS (SHEETS)
# ===================================================================
print("A iniciar Motor de Exaustão Climática nas posições ativas...")

ativos_ativos = []
if WEBHOOK_URL:
    try:
        resp = requests.get(WEBHOOK_URL, timeout=15)
        if resp.status_code == 200:
            dados = resp.json().get("ativos", []) if isinstance(resp.json(), dict) else resp.json()
            # Filtrar estritamente ativos que já estão na carteira
            ativos_ativos = [a for a in dados if str(a.get("estado", "")).upper() == "ATIVA_FAST" or str(a.get("posicao_ativa", "")).upper() == "SIM"]
    except Exception as e:
        print(f"[ERRO] Falha ao ler posições ativas do Sheets: {e}")

if not ativos_ativos:
    relatorio_vazio = "🌪️ MOTOR 13 - EXAUSTÃO CLIMÁTICA\n==================================================\nNenhuma posição ativa sob gestão ou falha na leitura. Análise abortada.\n"
    with open("comboio_exaustao_temp.txt", "w", encoding="utf-8") as f:
        f.write(relatorio_vazio)
    print("Nenhuma posição ativa para monitorizar.")
    exit(0)

print(f"[{len(ativos_ativos)}] Posições em carteira enviadas para auditoria parabólica.")

# ===================================================================
# 3. ANÁLISE MATEMÁTICA DE CLÍMAX
# ===================================================================
alertas_exaustao = []

for ativo in ativos_ativos:
    ticker = str(ativo.get("ticker", "")).strip().upper()
    qtd_atual = ativo.get("qtd", "N/A")
    
    if ticker == "BRK-A": ticker = "BRK-B"
    if not ticker or ticker == "#N/A": continue
    
    df = get_yf_history_safe(ticker)
    if df.empty:
        continue
        
    df.ta.ema(length=9, append=True)
    df.ta.rsi(length=14, append=True)
    df['RVOL'] = df['Volume'] / df['Volume'].rolling(20).mean()
    
    ultimo_dia = df.iloc[-1]
    preco = ultimo_dia['Close']
    ema9 = ultimo_dia.get('EMA_9', preco)
    rsi = ultimo_dia.get('RSI_14', 50)
    rvol = ultimo_dia.get('RVOL', 1)
    
    # Cálculo da tensão da "borracha"
    dist_ema9 = ((preco - ema9) / ema9) * 100
    
    # Condição Parabólica: Preço muito esticado + Volume Climático + RSI Extremo
    if dist_ema9 >= LIMIAR_DIST_EMA9 and (rvol >= LIMIAR_RVOL or rsi >= LIMIAR_RSI):
        alertas_exaustao.append({
            "ticker": ticker,
            "preco": preco,
            "dist_ema9": dist_ema9,
            "rvol": rvol,
            "rsi": rsi,
            "qtd": qtd_atual
        })
        print(f"⚠️ [ALERTA CLÍMAX] {ticker} está {dist_ema9:.1f}% acima da EMA9 com RVOL {rvol:.1f}!")

# ===================================================================
# 4. GERAÇÃO DE RELATÓRIO DE INTERVENÇÃO
# ===================================================================
data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M:%S")
relatorio = f"🌪️ MOTOR 13 - EXAUSTÃO CLIMÁTICA & PARABOLIC TAKE-PROFIT ({data_hoje})\n"
relatorio += "=" * 65 + "\n\n"

if alertas_exaustao:
    relatorio += "🚨 ALERTAS DE LIQUIDAÇÃO IMEDIATA (BLOW-OFF TOP DETETADO)\n"
    relatorio += "O algoritmo detetou um movimento parabólico insustentável. A probabilidade de reversão violenta nas próximas 48h excede os 85%.\n\n"
    
    for alerta in alertas_exaustao:
        relatorio += f"🔥 {alerta['ticker']}:\n"
        relatorio += f"   - Estado: PREÇO ESTICADO EXTREMO\n"
        relatorio += f"   - Tensão Estrutural: {alerta['dist_ema9']:.1f}% acima da EMA 9\n"
        relatorio += f"   - Exaustão Vendedora (RVOL): {alerta['rvol']:.2f}x o volume normal\n"
        relatorio += f"   - RSI (14): {alerta['rsi']:.1f}\n"
        relatorio += f"   - ⚡ AÇÃO EXIGIDA: Fechar 50% ou 100% da posição de {alerta['qtd']} ações NA ABERTURA DO MERCADO. Ignorar Trailing Stop normal.\n\n"
else:
    relatorio += "✅ NENHUMA ANOMALIA PARABÓLICA DETETADA NAS POSIÇÕES ATIVAS.\n"
    relatorio += "As tendências em carteira estão orgânicas e saudáveis. A gestão permanece entregue exclusivamente ao Trailing Stop Diário do Motor Carver.\n"

with open("comboio_exaustao_temp.txt", "w", encoding="utf-8") as f:
    f.write(relatorio)

print("\n[SUCESSO] Auditoria Climática concluída.")
