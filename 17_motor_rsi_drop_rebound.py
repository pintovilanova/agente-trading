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
# 1. CONFIGURAÇÕES E CREDENCIAIS (GitHub Secrets)
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

def limpar_float(val):
    """Converte com segurança valores numéricos para float."""
    if val is None: return None
    try:
        val_str = str(val).replace(",", ".").strip()
        if val_str == "" or val_str.lower() in ["nan", "n/a", "none"]: return None
        return float(val_str)
    except (ValueError, TypeError):
        return None

# ===================================================================
# 2. FUNÇÃO DE REDE: LER DADOS DO GOOGLE SHEETS VIA WEBHOOK
# ===================================================================
def buscar_dados_completos():
    print("A carregar Watchlist, Posições Ativas e Configs a partir do Google Sheets...")
    if not WEBHOOK_URL: 
        print("[AVISO] WEBHOOK_URL não configurado.")
        return [], {}, {}
    try:
        url_alvo = WEBHOOK_URL if "?" in WEBHOOK_URL else f"{WEBHOOK_URL}?aba=Analise Compra"
        resp = requests.get(url_alvo, timeout=15)
        
        if resp.status_code == 200:
            try:
                dados = resp.json()
            except json.JSONDecodeError:
                print(f"[ERRO] O Webhook não retornou um JSON válido. Resposta: {resp.text[:200]}")
                return [], {}, {}

            if isinstance(dados, dict):
                ativos = dados.get("ativos", [])
                posicoes = dados.get("posicoesAtivas", {})
                configs = dados.get("configs", {})
                return ativos, posicoes, configs
            elif isinstance(dados, list):
                return dados, {}, {}
                
        print(f"[AVISO] Webhook retornou status {resp.status_code}.")
        return [], {}, {}
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha ao ligar ao Google Sheets: {e}")
        return [], {}, {}

# ===================================================================
# 3. EXECUÇÃO DA CARGA DE DADOS E PARAMETRIZAÇÃO DE RISCO
# ===================================================================
ativos_sheets, posicoes_ativas_dict, configs_dict = buscar_dados_completos()

# Leitura dinâmica do Capital e do Risco por Trade a partir da aba Configs
capital_total = limpar_float(configs_dict.get("CAPITAL_TOTAL_CONTA")) or 10000.00
pct_risco = limpar_float(configs_dict.get("RISCO_SWING_PCT")) or limpar_float(configs_dict.get("RISCO_POR_TRADE")) or 0.01

VALOR_RISCO_USD = capital_total * pct_risco

print(f"[CONFIG] Capital Total: ${capital_total:,.2f} \vert{} Risco/Trade (Swing): {pct_risco*100:.1f}\% (${VALOR_RISCO_USD:,.2f} USD)")

# Montagem da Watchlist Dinâmica
tickers_watchlist = []
for item in ativos_sheets:
    if isinstance(item, dict):
        t = item.get("ticker")
        if t and str(t).strip() not in ["", "#N/A", "NONE", "N/A"]:
            tickers_watchlist.append(str(t).strip().upper())

# Fallback de segurança caso a Watchlist no Sheets esteja vazia
if not tickers_watchlist:
    print("[INFO] Watchlist vazia no Sheets. A carregar lista de fallback de alta liquidez.")
    tickers_watchlist = [
        "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "AMD", 
        "NFLX", "AVGO", "COST", "PEP", "QCOM", "TXN", "AMAT", "CRM"
    ]
else:
    print(f"[SUCESSO] {len(tickers_watchlist)} ativos carregados da Watchlist do Sheets.")

tickers_watchlist = list(dict.fromkeys(tickers_watchlist))

# ===================================================================
# 4. AUDITAR POSIÇÕES EM CARTEIRA (STATUS: ATIVA_SWING / ATIVA_M17)
# ===================================================================
bloco_posicoes_ativas = ""
for ticker, info in posicoes_ativas_dict.items():
    status = str(info.get("status", "")).strip().upper()
    if status in ["ATIVA_SWING", "ATIVA_M17"]:
        try:
            df_pos = yf.download(ticker, period="1mo", interval="1d", progress=False)
            if not df_pos.empty:
                if isinstance(df_pos.columns, pd.MultiIndex):
                    df_pos.columns = df_pos.columns.droplevel(1)
                
                # 🛡️ PROTEÇÃO ANTI-BUG DO YAHOO: Remove a vela fantasma se O=H=L=C (fora de horas)
                if len(df_pos) > 1:
                    ult = df_pos.iloc[-1]
                    if ult['Open'] == ult['High'] == ult['Low'] == ult['Close']:
                        df_pos = df_pos.iloc[:-1] # Descarta a vela corrompida

                df_pos.ta.ema(length=5, append=True)
                ultimo = df_pos.iloc[-1]
                
                # 🎯 Busca o preço real através do último minuto negociado (Ignora bugs diários)
                try:
                    df_intra = yf.download(ticker, period="5d", interval="1m", progress=False)
                    if isinstance(df_intra.columns, pd.MultiIndex):
                        df_intra.columns = df_intra.columns.droplevel(1)
                    preco_atual = round(float(df_intra['Close'].iloc[-1]), 2)
                    max_intra = round(float(df_intra['High'].max()), 2)
                except Exception:
                    preco_atual = round(float(ultimo['Close']), 2)
                    max_intra = preco_atual
                
                maxima_hoje = max(round(float(ultimo['High']), 2), max_intra)
                minima_hoje = round(float(ultimo['Low']), 2)
                ema5_atual = round(float(df_pos['EMA_5'].iloc[-1]), 2)
                
                entrada = limpar_float(info.get("precoEntrada")) or preco_atual
                stop = limpar_float(info.get("stopAtual")) or 0.0
                qtd = info.get("quantidade", "N/A")
                
                # Regras de Auditoria Tática
                maxima_efetiva = max(maxima_hoje, preco_atual)
                
                if maxima_efetiva >= ema5_atual:
                    acao = f"🎯 ALVO ALCANÇADO (EMA5 em ${ema5_atual})! Recomendado FECHAR POSIÇÃO com Lucro (WIN)."
                elif minima_hoje <= stop and stop > 0:
                    acao = f"🚨 STOP LOSS ATINGIDO (${stop})! Recomendado LIQUIDAR POSIÇÃO (LOSS)."
                else:
                    acao = f"⏳ MANTER POSIÇÃO. A acompanhar ressalto rumo à EMA5 (${ema5_atual}). Stop fixo em ${stop}."
                
                bloco_posicoes_ativas += (
                    f"📌 [POSIÇÃO ATIVA - {status}] {ticker} | Qtd: {qtd} | Entrada: ${entrada} | "
                    f"Preço Atual: ${preco_atual} | Alvo EMA5: ${ema5_atual} \vert{} Stop Fixo:${stop} | "
                    f"AÇÃO: {acao}\n"
                )
        except Exception as e:
            print(f"[ERRO] Falha ao auditar posição ativa {ticker}: {e}")

# ===================================================================
# 5. RASTREAR NOVOS SINAIS DE ENTRADA (WATCHLIST DINÂMICA)
# ===================================================================
alertas_rebound = []

for ticker in tickers_watchlist:
    # Ignora se já for uma posição ativa em carteira
    if ticker in posicoes_ativas_dict:
        continue

    try:
        df = yf.download(ticker, period="3mo", interval="1d", progress=False)
        if df.empty or len(df) < 30:
            continue
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        # 🛡️ PROTEÇÃO ANTI-BUG DO YAHOO: Remove a vela fantasma se O=H=L=C (fora de horas)
        if len(df) > 1:
            ult = df.iloc[-1]
            if ult['Open'] == ult['High'] == ult['Low'] == ult['Close']:
                df = df.iloc[:-1] # Descarta a vela corrompida
            
        df.ta.sma(length=50, append=True)
        df.ta.ema(length=5, append=True)
        df.ta.rsi(length=2, append=True)
        
        ultimo_dia = df.iloc[-1]
        dia_anterior = df.iloc[-2]
        
        # 🎯 Busca o preço real consolidado via vela de 1m (fallback mais seguro que fast_info na madrugada)
        try:
            df_intra = yf.download(ticker, period="1d", interval="1m", progress=False)
            if isinstance(df_intra.columns, pd.MultiIndex):
                df_intra.columns = df_intra.columns.droplevel(1)
            preco_atual = float(df_intra['Close'].iloc[-1])
        except Exception:
            preco_atual = float(ultimo_dia['Close'])
            
        sma50 = float(df['SMA_50'].iloc[-1])
        ema5 = float(df['EMA_5'].iloc[-1])
        rsi2 = float(df['RSI_2'].iloc[-1])
        
        fecho_ontem = float(dia_anterior['Close'])
        fecho_anteontem = float(df['Close'].iloc[-3])
        
        dois_dias_queda = (preco_atual < fecho_ontem) and (fecho_ontem < fecho_anteontem)
        
        # Filtro de Entrada: Tendência de Alta + RSI(2) Oversold + 2 Dias Consecutivos de Queda
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
                "preco_atual": preco_
