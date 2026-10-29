# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR 17 (2-DAY RSI DROP & REBOUND)
# ===================================================================
import os
import sys
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import requests
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import warnings
warnings.filterwarnings("ignore")

print("A iniciar Motor 17 - 2-Day RSI Drop & Rebound (Swing 48h-72h)...")

# ===================================================================
# PARÂMETROS E CREDENCIAIS
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
BANCA_TOTAL_USD = 10000.0  # Substitui pelo valor da tua banca real
RISCO_POR_TRADE = 0.01     # 1% de risco por trade
VALOR_RISCO_USD = BANCA_TOTAL_USD * RISCO_POR_TRADE

# ===================================================================
# 1. LER POSIÇÕES ATIVAS E WATCHLIST DO GOOGLE SHEETS VIA WEBHOOK
# ===================================================================
posicoes_ativas = {}
tickers_watchlist = []

if WEBHOOK_URL:
    try:
        res = requests.get(WEBHOOK_URL, timeout=15)
        if res.status_code == 200:
            dados = res.json()
            if isinstance(dados, dict):
                # Posições ativas no Diário de Bordo
                posicoes_ativas = dados.get("posicoesAtivas", {})
                
                # Watchlist vinda da aba "Analise Compra"
                ativos_sheets = dados.get("ativos", [])
                for a in ativos_sheets:
                    t = a.get("ticker")
                    if t and str(t).strip() not in ["", "#N/A", "NONE", "N/A"]:
                        tickers_watchlist.append(str(t).strip().upper())
    except Exception as e:
        print(f"[AVISO] Falha ao carregar dados do Sheets: {e}")

# Fallback de segurança caso a conexão ao Webhook falhe ou a lista venha vazia
if not tickers_watchlist:
    print("[INFO] A usar lista de ativos de fallback (S&P 100 / Nasdaq 100).")
    tickers_watchlist = [
        "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "AMD", 
        "NFLX", "AVGO", "COST", "PEP", "QCOM", "TXN", "AMAT", "CRM"
    ]
else:
    print(f"[SUCESSO] {len(tickers_watchlist)} ativos carregados dinamicamente da Watchlist do Sheets.")

# Remove duplicados mantendo a ordem
tickers_watchlist = list(dict.fromkeys(tickers_watchlist))

# ===================================================================
# 2. AUDITAR POSIÇÕES EM CARTEIRA (STATUS: ATIVA_SWING / ATIVA_M17)
# ===================================================================
bloco_posicoes_ativas = ""
for ticker, info in posicoes_ativas.items():
    status = str(info.get("status", "")).strip().upper()
    if status in ["ATIVA_SWING", "ATIVA_M17"]:
        try:
            df_pos = yf.download(ticker, period="1mo", interval="1d", progress=False)
            if not df_pos.empty:
                if isinstance(df_pos.columns, pd.MultiIndex):
                    df_pos.columns = df_pos.columns.droplevel(1)
                df_pos.ta.ema(length=5, append=True)
                
                ultimo = df_pos.iloc[-1]
                preco_atual = round(float(ultimo['Close']), 2)
                maxima_hoje = round(float(ultimo['High']), 2)
                minima_hoje = round(float(ultimo['Low']), 2)
                ema5_atual = round(float(df_pos['EMA_5'].iloc[-1]), 2)
                
                entrada = float(info.get("precoEntrada", preco_atual))
                stop = float(info.get("stopAtual", 0))
                qtd = info.get("quantidade", "N/A")
                
                # Regras de Auditoria Tática (EMA5 = Take Profit / Stop = Defesa)
                if maxima_hoje >= ema5_atual:
                    acao = f"🎯 ALVO ALCANÇADO (EMA5 em ${ema5_atual})! Recomendado FECHAR POSIÇÃO com Lucro (WIN)."
                elif minima_hoje <= stop and stop > 0:
                    acao = f"🚨 STOP LOSS ATINGIDO (${stop})! Recomendado LIQUIDAR POSIÇÃO (LOSS)."
                else:
                    acao = f"⏳ MANTER POSIÇÃO. A acompanhar ressalto rumo à EMA5 (${ema5_atual}). Stop fixo em ${stop}."
                
                bloco_posicoes_ativas += (
                    f"📌 [POSIÇÃO ATIVA - {status}] {ticker} | Qtd: {qtd} | Entrada: ${entrada} | "
                    f"Preço Atual: ${preco_atual} | Alvo EMA5: ${ema5_atual} | Stop Fixo: ${stop} | "
                    f"AÇÃO: {acao}\n"
                )
        except Exception as e:
            print(f"[ERRO] Falha ao auditar posição ativa {ticker}: {e}")

# ===================================================================
# 3. RASTREAR NOVOS SINAIS DE ENTRADA (WATCHLIST DINÂMICA)
# ===================================================================
alertas_rebound = []

for ticker in tickers_watchlist:
    try:
        df = yf.download(ticker, period="3mo", interval="1d", progress=False)
        if df.empty or len(df) < 30:
            continue
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
            
        df.ta.sma(length=50, append=True)
        df.ta.ema(length=5, append=True)
        df.ta.rsi(length=2, append=True)
        
        ultimo_dia = df.iloc[-1]
        dia_anterior = df.iloc[-2]
        
        preco_atual = float(ultimo_dia['Close'])
        sma50 = float(df['SMA_50'].iloc[-1])
        ema5 = float(df['EMA_5'].iloc[-1])
        rsi2 = float(df['RSI_2'].iloc[-1])
        
        fecho_ontem = float(dia_anterior['Close'])
        fecho_anteontem = float(df['Close'].iloc[-3])
        
        dois_dias_queda = (preco_atual < fecho_ontem) and (fecho_ontem < fecho_anteontem)
        
        if preco_atual > sma50 and rsi2 <= 10.0 and dois_dias_queda:
            preco_entrada = round(preco_atual, 2)
            preco_stop = round(float(ultimo_dia['Low']) * 0.99, 2)
            preco_tp = round(ema5, 2)
            
            risco_por_acao = preco_entrada - preco_stop
            if risco_por_acao > 0:
                qtd_acoes = round(VALOR_RISCO_USD / risco_por_acao, 2)
                valor_a_investir = round(qtd_acoes * preco_entrada, 2)
            else:
                qtd_acoes = 0
                valor_a_investir = 0
            
            alertas_rebound.append({
                "ticker": ticker,
                "preco_atual": preco_entrada,
                "rsi2": round(rsi2, 2),
                "stop_loss": preco_stop,
                "take_profit_ema5": preco_tp,
                "ordem_tipo": "BUY MARKET (no fecho) / BUY LIMIT",
                "qtd_acoes": qtd_acoes,
                "valor_investir": valor_a_investir,
                "status_sheets": "ATIVA_SWING"
            })
            
    except Exception as e:
        print(f"[ERRO] Falha ao analisar {ticker} no Motor 17: {e}")

# ===================================================================
# 4. GERAR FICHEIRO TEMPORÁRIO PARA O ORQUESTRADOR
# ===================================================================
data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M")

bloco_texto = f"⚡ MOTOR 17: 2-DAY RSI DROP & REBOUND ({data_hoje})\n\n"

if bloco_posicoes_ativas:
    bloco_texto += "--------------------------------------------------\n"
    bloco_texto += "GESTÃO DE POSIÇÕES ATIVAS (MOTOR 17 - SWING REBOUND):\n\n"
    bloco_texto += bloco_posicoes_ativas
    bloco_texto += "--------------------------------------------------\n\n"

if alertas_rebound:
    bloco_texto += "NOVOS SINAIS DE ENTRADA DETETADOS:\n\n"
    for a in alertas_rebound:
        bloco_texto += (
            f"🎯 TICKER: {a['ticker']} | RSI(2): {a['rsi2']} (Extremo Oversold em Tendência de Alta)\n"
            f"   - Estratégia / Tag Sheets: {a['status_sheets']}\n"
            f"   - Ordem Recomendada: {a['ordem_tipo']}\n"
            f"   - Preço de Entrada: ${a['preco_atual']}\n"
            f"   - Stop Loss (Abaixo da Mínima): ${a['stop_loss']}\n"
            f"   - Take Profit Alvo (EMA5): ${a['take_profit_ema5']}\n"
            f"   - Qtd. Recomendada: {a['qtd_acoes']} Ações\n"
            f"   - Valor Estimado do Lote: ~${a['valor_investir']} USD\n"
            f"   - Horizonte Tático: 48h a 72h\n"
            f"--------------------------------------------------\n"
        )
else:
    bloco_texto += "✅ Nenhum novo sinal de entrada hoje. (Modo Silêncio ativo para novas ordens).\n"

with open("comboio_rsi_rebound_temp.txt", "w", encoding="utf-8") as f:
    f.write(bloco_texto)

print(f"[SUCESSO] Motor 17 executado com sucesso.")
