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

# Importação da função modular de notificação do Telegram
from F01_notificador_telegram import enviar_alerta

print("A iniciar Motor 17 - 2-Day RSI Drop & Rebound (Hit & Run 48h-72h)...")

# ===================================================================
# 1. CONFIGURAÇÕES E CREDENCIAIS (GitHub Secrets)
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
EMAIL_USER = os.environ.get('EMAIL_USER')
EMAIL_PASS = os.environ.get('EMAIL_PASS')

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

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
                posicoes = dados.get("posicoesAtivas", {}) or dados.get("posicoes", {})
                configs = dados.get("configs", {})
                return ativos, posicoes, configs
            elif isinstance(dados, list):
                return dados, {}, {}
                
        print(f"[AVISO] Webhook retornou status {resp.status_code}.")
        return [], {}, {}
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha ao ligar ao Google Sheets: {e}")
        return [], {}, {}

def enviar_email(conteudo):
    print("\nA enviar relatório do Motor 17 por e-mail...")
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] EMAIL_USER ou EMAIL_PASS não definidos. Email não enviado.")
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_USER
        msg['Subject'] = f"⚡ tradingRelatorioIA US - MOTOR 17 (2-DAY RSI) ({datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')})"
        msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
        server.quit()
        print("[SUCESSO] Email enviado com sucesso!")
        return True
    except Exception as e:
        print(f"[ERRO] Falha ao enviar email: {e}")
        return False

# ===================================================================
# 3. EXECUÇÃO DA CARGA DE DADOS E PARAMETRIZAÇÃO DE RISCO
# ===================================================================
ativos_sheets, posicoes_ativas_dict, configs_dict = buscar_dados_completos()

capital_total = limpar_float(configs_dict.get("CAPITAL_TOTAL_CONTA")) or 10000.00
pct_risco = limpar_float(configs_dict.get("RISCO_SWING_PCT")) or limpar_float(configs_dict.get("RISCO_POR_TRADE")) or 0.01

VALOR_RISCO_USD = capital_total * pct_risco

print(f"[CONFIG] Capital Total: ${capital_total:,.2f} | Risco/Trade: {pct_risco*100:.1f}% (${VALOR_RISCO_USD:,.2f} USD)")

TICKERS_EXCLUIDOS = {"NVVE"}

tickers_watchlist = []
for item in ativos_sheets:
    if isinstance(item, dict):
        t = item.get("ticker")
        if t and str(t).strip() not in ["", "#N/A", "NONE", "N/A"]:
            ticker_limpo = str(t).strip().upper()
            if ticker_limpo not in TICKERS_EXCLUIDOS:
                tickers_watchlist.append(ticker_limpo)

if not tickers_watchlist:
    tickers_watchlist = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "AMD"]
else:
    print(f"[SUCESSO] {len(tickers_watchlist)} ativos carregados da Watchlist do Sheets.")

tickers_watchlist = list(dict.fromkeys(tickers_watchlist))

# ===================================================================
# 4. AUDITAR POSIÇÕES EM CARTEIRA
# ===================================================================
bloco_posicoes_ativas = ""
for chave_pos, info in posicoes_ativas_dict.items():
    if not isinstance(info, dict):
        continue
    status = str(info.get("status", "")).strip().upper()
    if "ATIVA" in status or status in ["ATIVA_SWING", "ATIVA_M17"]:
        try:
            # Mapeamento robusto de tickers (ex: C3.ai -> AI)
            ticker = "AI" if chave_pos.lower() in ["c3.ai", "c3"] else chave_pos.strip().upper()
            
            df_pos = yf.download(ticker, period="1mo", interval="1d", progress=False)
            if not df_pos.empty:
                if isinstance(df_pos.columns, pd.MultiIndex):
                    df_pos.columns = df_pos.columns.droplevel(1)
                
                df_pos.ta.ema(length=5, append=True)
                ema5_atual = round(float(df_pos['EMA_5'].iloc[-1]), 2)
                stop = limpar_float(info.get("stopAtual")) or limpar_float(info.get("stopLoss")) or 0.0
                
                try:
                    df_intra = yf.download(ticker, period="2d", interval="1m", prepost=True, progress=False)
                    if isinstance(df_intra.columns, pd.MultiIndex):
                        df_intra.columns = df_intra.columns.droplevel(1)
                    preco_atual = round(float(df_intra['Close'].iloc[-1]), 2)
                    maxima_hoje = round(float(df_intra['High'].max()), 2)
                    minima_hoje = round(float(df_intra['Low'].min()), 2)
                except Exception:
                    preco_atual = round(float(df_pos['Close'].iloc[-1]), 2)
                    maxima_hoje = round(float(df_pos['High'].iloc[-1]), 2)
                    minima_hoje = round(float(df_pos['Low'].iloc[-1]), 2)
                
                entrada = limpar_float(info.get("precoEntrada")) or preco_atual
                qtd = info.get("quantidade", "N/A")
                maxima_efetiva = max(maxima_hoje, preco_atual)
                
                if maxima_efetiva >= ema5_atual:
                    acao = f"🎯 ALVO ALCANÇADO (EMA5 em ${ema5_atual})! FECHAR POSIÇÃO."
                elif minima_hoje <= stop and stop > 0:
                    acao = f"🚨 STOP LOSS ATINGIDO (${stop})! LIQUIDAR POSIÇÃO."
                else:
                    acao = f"⏳ MANTER POSIÇÃO. Alvo EMA5: ${ema5_atual} | Stop: ${stop}."
                
                bloco_posicoes_ativas += f"📌 [{status}] {ticker} ({chave_pos}) | Qtd: {qtd} | Entrada: ${entrada} | Atual: ${preco_atual} | {acao}\n"
        except Exception as e:
            print(f"[ERRO] Falha ao auditar posição ativa {chave_pos}: {e}")

# ===================================================================
# 5. RASTREAR NOVOS SINAIS DE ENTRADA
# ===================================================================
alertas_rebound = []
total_analisados = 0

for ticker in tickers_watchlist:
    if ticker in posicoes_ativas_dict:
        continue
    try:
        total_analisados += 1
        df = yf.download(ticker, period="3mo", interval="1d", progress=False)
        if df.empty or len(df) < 30: continue
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)

        df.ta.sma(length=50, append=True)
        df.ta.ema(length=5, append=True)
        df.ta.rsi(length=2, append=True)
        
        ultimo_dia = df.iloc[-1]
        dia_anterior = df.iloc[-2]
        
        try:
            df_intra = yf.download(ticker, period="1d", interval="1m", progress=False)
            if isinstance(df_intra.columns, pd.MultiIndex): df_intra.columns = df_intra.columns.droplevel(1)
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
            qtd_acoes = round(VALOR_RISCO_USD / risco_por_acao, 2) if risco_por_acao > 0 else 0
            valor_investir = round(qtd_acoes * preco_entrada, 2)
            
            alertas_rebound.append({
                "ticker": ticker,
                "preco_atual": preco_entrada,
                "rsi2": round(rsi2, 2),
                "stop_loss": preco_stop,
                "take_profit_ema5": preco_tp,
                "qtd_acoes": qtd_acoes,
                "valor_investir": valor_investir
            })
    except Exception as e:
        print(f"[ERRO] Falha ao analisar {ticker}: {e}")

# ===================================================================
# 6. RELATÓRIO E ENVIO POR E-MAIL
# ===================================================================
data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M")
bloco_texto = f"⚡ MOTOR 17: 2-DAY RSI DROP & REBOUND ({data_hoje})\n\n"

if bloco_posicoes_ativas:
    bloco_texto += f"POSIÇÕES ATIVAS:\n{bloco_posicoes_ativas}\n"
else:
    bloco_texto += "POSIÇÕES ATIVAS: Nenhuma posição ativa detetada.\n\n"

if alertas_rebound:
    bloco_texto += "NOVOS SINAIS DETETADOS:\n"
    for a in alertas_rebound:
        bloco_texto += f"🎯 {a['ticker']} | RSI: {a['rsi2']} | Entrada: ${a['preco_atual']} | Stop: ${a['stop_loss']} | Alvo: ${a['take_profit_ema5']}\n"
else:
    bloco_texto += "✅ Nenhum novo sinal hoje.\n"

# Enviar o relatório por e-mail
enviar_email(bloco_texto)

# ===================================================================
# 7. NOTIFICAÇÃO TELEGRAM DEBUG (CONTROLADA PELA FLAG DE CONFIGS)
# ===================================================================
debug_telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

if debug_telegram_ativado:
    print("A enviar notificação de Debug para o Telegram via função modular...")
    total_acionados = len(alertas_rebound)
    mensagem_debug = (
        f"17 ⚡ *MOTOR 17 (2-DAY RSI DROP & REBOUND)*\n\n"
        f"🔍 [DEBUG] Execução concluída com sucesso.\n"
        f"📊 Ativos analisados: *{total_analisados}* | Acionados: *{total_acionados}*\n"
        f"✉️ Relatório de reversão de curto prazo gerado e enviado por e-mail."
    )
    enviar_alerta(mensagem_debug)

print(f"[SUCESSO] Ciclo completo do Motor 17 concluído.")
