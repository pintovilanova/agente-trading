# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR 17 (2-DAY RSI DROP & REBOUND)
# ===================================================================
import os
import sys
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import datetime
from zoneinfo import ZoneInfo
import warnings
warnings.filterwarnings("ignore")

print("A iniciar Motor 17 - 2-Day RSI Drop & Rebound (Swing 48h-72h)...")

# Lista de ativos de liquidez ultra-elevada (S&P 500 / Nasdaq 100)
TICKERS_ALVO = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "AMD", "NFLX", "AVGO", "COST", "PEP"]

alertas_rebound = []

for ticker in TICKERS_ALVO:
    try:
        df = yf.download(ticker, period="3mo", interval="1d", progress=False)
        if df.empty or len(df) < 30:
            continue
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
            
        # Indicadores: Tendência (MM50), Reversão (RSI 2) e Alvo (EMA 5)
        df.ta.sma(length=50, append=True)
        df.ta.ema(length=5, append=True)
        df.ta.rsi(length=2, append=True)
        
        ultimo_dia = df.iloc[-1]
        dia_anterior = df.iloc[-2]
        
        preco_atual = float(ultimo_dia['Close'])
        sma50 = float(df['SMA_50'].iloc[-1])
        ema5 = float(df['EMA_5'].iloc[-1])
        rsi2 = float(df['RSI_2'].iloc[-1])
        
        # REGRAS DO MOTOR 17:
        # 1. Tendência de Alta Primária: Preço acima da MM50
        # 2. Recuo Violento de Curto Prazo: RSI(2) < 10
        # 3. Dois dias consecutivos de fecho em queda
        fecho_ontem = float(dia_anterior['Close'])
        fecho_anteontem = float(df['Close'].iloc[-3])
        
        dois_dias_queda = (preco_atual < fecho_ontem) and (fecho_ontem < fecho_anteontem)
        
        if preco_atual > sma50 and rsi2 <= 10.0 and dois_dias_queda:
            preco_entrada = round(preco_atual, 2)
            preco_stop = round(float(ultimo_dia['Low']) * 0.99, 2) # Abaixo da mínima de hoje
            preco_tp = round(ema5, 2)                             # Alvo rápido na EMA5
            
            alertas_rebound.append({
                "ticker": ticker,
                "preco_atual": preco_entrada,
                "rsi2": round(rsi2, 2),
                "stop_loss": preco_stop,
                "take_profit_ema5": preco_tp,
                "ordem_tipo": "BUY MARKET (no fecho) / BUY LIMIT"
            })
            
    except Exception as e:
        print(f"[ERRO] Falha ao analisar {ticker} no Motor 17: {e}")

# ===================================================================
# GERAR FICHEIRO TEMPORÁRIO PARA O ORQUESTRADOR
# ===================================================================
data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M")

if alertas_rebound:
    bloco_texto = f"⚡ MOTOR 17: 2-DAY RSI DROP & REBOUND ({data_hoje})\n\n"
    for a in alertas_rebound:
        bloco_texto += (
            f"🎯 TICKER: {a['ticker']} | RSI(2): {a['rsi2']} (Extremo Oversold em Tendência de Alta)\n"
            f"   - Ordem Recomendada: {a['ordem_tipo']}\n"
            f"   - Preço de Entrada: ${a['preco_atual']}\n"
            f"   - Stop Loss (Abaixo do Mínimo): ${a['stop_loss']}\n"
            f"   - Take Profit Alvo (EMA5): ${a['take_profit_ema5']}\n"
            f"   - Prazo Estipulado: 48h a 72h\n"
            f"--------------------------------------------------\n"
        )
else:
    bloco_texto = "✅ Nenhum ativo em retração extrema de 2 dias com RSI(2) < 10 hoje. (Modo Silêncio ativo)."

with open("comboio_rsi_rebound_temp.txt", "w", encoding="utf-8") as f:
    f.write(bloco_texto)

print(f"[SUCESSO] Motor 17 executado. Alertas de ricochete gerados: {len(alertas_rebound)}")
