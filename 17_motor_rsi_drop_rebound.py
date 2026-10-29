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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from zoneinfo import ZoneInfo
import warnings
warnings.filterwarnings("ignore")

print("A iniciar Motor 17 - 2-Day RSI Drop & Rebound (Hit & Run 48h-72h)...")

# ===================================================================
# 1. CONFIGURAÇÕES E CREDENCIAIS (GitHub Secrets)
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
EMAIL_USER = os.environ.get('EMAIL_USER')
EMAIL_PASS = os.environ.get('EMAIL_PASS')
TELEGRAM_BOT_TOKEN_GERAL = os.environ.get('TELEGRAM_BOT_TOKEN_GERAL')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

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

capital_total = limpar_float(configs_dict.get("CAPITAL_TOTAL_CONTA")) or 10000.00
pct_risco = limpar_float(configs_dict.get("RISCO_SWING_PCT")) or limpar_float(configs_dict.get("RISCO_POR_TRADE")) or 0.01

VALOR_RISCO_USD = capital_total * pct_risco

print(f"[CONFIG] Capital Total: ${capital_total:,.2f} | Risco/Trade: {pct_risco*100:.1f}% (${VALOR_RISCO_USD:,.2f} USD)")

# Tickers conhecidos por estarem deslistados ou causarem falhas no Yahoo Finance
TICKERS_EXCLUIDOS = {"NVVE"}

tickers_watchlist = []
for item in ativos_sheets:
    if isinstance(item, dict):
        t = item.get("ticker")
        if t and str(t).strip() not in ["", "#N/A", "NONE", "N/A"]:
            ticker_limpo = str(t).strip().upper()
            if ticker_limpo not in TICKERS_EXCLUIDOS:
                tickers_watchlist.append(ticker_limpo)
            else:
                print(f"[AVISO] Ticker ignorado por estar na lista de exclusão: {ticker_limpo}")

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
# 4. AUDITAR POSIÇÕES EM CARTEIRA (STATUS: ATIVA_M17 / ATIVA_SWING)
# ===================================================================
bloco_posicoes_ativas = ""
for ticker, info in posicoes_ativas_dict.items():
    status = str(info.get("status", "")).strip().upper()
    # Adicionado ATIVA_M17 e mantido ATIVA_SWING por retrocompatibilidade
    if status in ["ATIVA_SWING", "ATIVA_M17"]:
        try:
            df_pos = yf.download(ticker, period="1mo", interval="1d", progress=False)
            if not df_pos.empty:
                if isinstance(df_pos.columns, pd.MultiIndex):
                    df_pos.columns = df_pos.columns.droplevel(1)
                
                if len(df_pos) > 1:
                    ult = df_pos.iloc[-1]
                    if ult['Open'] == ult['High'] == ult['Low'] == ult['Close']:
                        df_pos = df_pos.iloc[:-1]

                df_pos.ta.ema(length=5, append=True)
                ema5_atual = round(float(df_pos['EMA_5'].iloc[-1]), 2)
                stop = limpar_float(info.get("stopAtual")) or 0.0
                
                try:
                    df_intra = yf.download(ticker, period="2d", interval="1m", prepost=True, progress=False)
                    if isinstance(df_intra.columns, pd.MultiIndex):
                        df_intra.columns = df_intra.columns.droplevel(1)
                    
                    preco_atual = round(float(df_intra['Close'].iloc[-1]), 2)
                    ultimo_dia_str = df_intra.index[-1].strftime('%Y-%m-%d')
                    df_hoje = df_intra[df_intra.index.strftime('%Y-%m-%d') == ultimo_dia_str]
                    
                    maxima_hoje = round(float(df_hoje['High'].max()), 2)
                    minima_hoje = round(float(df_hoje['Low'].min()), 2)
                except Exception:
                    preco_atual = round(float(df_pos['Close'].iloc[-1]), 2)
                    maxima_hoje = round(float(df_pos['High'].iloc[-1]), 2)
                    minima_hoje = round(float(df_pos['Low'].iloc[-1]), 2)
                
                entrada = limpar_float(info.get("precoEntrada")) or preco_atual
                qtd = info.get("quantidade", "N/A")
                
                maxima_efetiva = max(maxima_hoje, preco_atual)
                
                if maxima_efetiva >= ema5_atual:
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
# 5. RASTREAR NOVOS SINAIS DE ENTRADA (WATCHLIST DINÂMICA)
# ===================================================================
alertas_rebound = []

for ticker in tickers_watchlist:
    if ticker in posicoes_ativas_dict:
        continue

    try:
        df = yf.download(ticker, period="3mo", interval="1d", progress=False)
        if df.empty or len(df) < 30:
            continue
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        if len(df) > 1:
            ult = df.iloc[-1]
            if ult['Open'] == ult['High'] == ult['Low'] == ult['Close']:
                df = df.iloc[:-1]
            
        df.ta.sma(length=50, append=True)
        df.ta.ema(length=5, append=True)
        df.ta.rsi(length=2, append=True)
        
        ultimo_dia = df.iloc[-1]
        dia_anterior = df.iloc[-2]
        
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
                "status_sheets": "ATIVA_M17"
            })
            
    except Exception as e:
        print(f"[ERRO] Falha ao analisar {ticker} no Motor 17: {e}")

# ===================================================================
# 6. RELATÓRIO, FICHEIRO TEMPORÁRIO E TELEGRAM
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
            f"   - 🔄 PASSAGEM DE TESTEMUNHO: ⚠️ ATENÇÃO: Operação HIT AND RUN. Assim que executada, regista o estado no Sheets como 'ATIVA_M17'. Logo que a EMA5 for tocada, fecha a posição integralmente.\n"
            f"--------------------------------------------------\n"
        )
else:
    bloco_texto += "✅ Nenhum novo sinal de entrada hoje. (Modo Silêncio ativo para novas ordens).\n"

# Grava o ficheiro temporário para o Orquestrador
with open("comboio_rsi_rebound_temp.txt", "w", encoding="utf-8") as f:
    f.write(bloco_texto)

print(f"[SUCESSO] Ficheiro temporário gerado.")

# 📧 Envio de E-mail Direto (Ativo)
if EMAIL_USER and EMAIL_PASS:
    try:
        print("A enviar e-mail direto do Motor 17...")
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_USER
        msg['Subject'] = f"⚡ Relatório Direto - Motor 17 (RSI Drop & Rebound) [{data_hoje}]"
        msg.attach(MIMEText(bloco_texto, 'plain', 'utf-8'))
        
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
        print("[SUCESSO] E-mail direto enviado com sucesso!")
    except Exception as e:
        print(f"[AVISO] Falha ao enviar e-mail direto: {e}")

# 📱 Envio de Notificação Telegram (Controlado pelo Sheets)
telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS", "true")).strip().lower() in ["true", "1", "sim", "yes"]

if not telegram_ativado:
    print("[INFO] Notificações de Telegram desativadas no Google Sheets (TELEGRAM_NOTIFICATIONS = false).")
elif TELEGRAM_BOT_TOKEN_GERAL and TELEGRAM_CHAT_ID:
    try:
        print("A enviar notificação para o Telegram...")
        url_tg = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN_GERAL}/sendMessage"
        payload_tg = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": f"🎯 *MOTOR 17 (2-DAY RSI DROP & REBOUND)*\n\n✅ Execução concluída com sucesso. Verifica o e-mail para consultar os sinais detetados."
        }
        resp_tg = requests.post(url_tg, json=payload_tg, timeout=10)
        if resp_tg.status_code == 200:
            print("[SUCESSO] Alerta enviado via Telegram com sucesso!")
        else:
            print(f"[AVISO] Falha ao enviar Telegram: {resp_tg.text}")
    except Exception as e:
        print(f"[ERRO] Erro de rede ao enviar Telegram: {e}")
else:
    print("[AVISO] Credenciais de Telegram não configuradas. Notificação ignorada.")

print(f"[SUCESSO] Ciclo completo do Motor 17 concluído.")
