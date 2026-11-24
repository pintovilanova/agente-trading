# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - DISJUNTOR MACRO GLOBAL (INTERMARKET ANALYSIS)
# ===================================================================================
# Descrição Geral:
# Audita os 4 pilares institucionais do mercado norte-americano antes dos motores:
# 1. Tendência & Momentum do S&P 500 (SPY vs EMA 20, SMA 50 e SMA 200 + Gap Pré-Mercado)
# 2. Índice de Pânico Absoluto (^VIX)
# 3. Estrutura a Termo da Volatilidade (^VIX vs ^VIX3M — Contango vs Backwardation)
# 4. Mercado de Crédito Institucional (HYG High Yield vs IEF Treasuries 7-10Y)
# Emite o regime oficial (VERDE / CAUTELA AMARELA / BLOQUEADO VERMELHO) para o Orquestrador.
# ===================================================================================

import yfinance as yf
import pandas as pd
import numpy as np
import os
import sys
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from zoneinfo import ZoneInfo
import time
import random
import warnings
warnings.filterwarnings("ignore")

from F01_notificador_telegram import enviar_alerta

# ===================================================================
# BYPASS SESSÃO YAHOO FINANCE (PARA GITHUB ACTIONS)
# ===================================================================
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O mercado está fechado. O Disjuntor Macro vai descansar.")
    # sys.exit(0)

# ===================================================================
# 1. CONFIGURAÇÕES E CREDENCIAIS
# ===================================================================
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

if EMAIL_USER:
    EMAIL_USER = EMAIL_USER.strip()
if EMAIL_PASS:
    EMAIL_PASS = EMAIL_PASS.strip()

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

def gravar_ficheiro_macro(conteudo):
    with open("comboio_macro_temp.txt", "w", encoding="utf-8") as f:
        f.write(conteudo)

def buscar_configs_sheets():
    if not WEBHOOK_URL:
        return {}
    try:
        url_alvo = WEBHOOK_URL if "?" in WEBHOOK_URL else f"{WEBHOOK_URL}?aba=Analise Compra"
        resp = requests.get(url_alvo, timeout=15)
        if resp.status_code == 200:
            dados = resp.json()
            if isinstance(dados, dict):
                return dados.get("configs", {})
    except Exception as e:
        print(f"[AVISO] Não foi possível carregar configs do Sheets: {e}")
    return {}

configs_dict = buscar_configs_sheets()

def enviar_alerta_macro(assunto, corpo_email, mensagem_tg, urgente=False):
    print(f"\nA enviar relatório macro (Assunto: '{assunto}')...")
    
    # 1. Envio por E-mail
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] Credenciais de email em falta. A saltar envio por email.")
    else:
        for tentativa in range(3):
            try:
                msg = MIMEMultipart()
                msg['From'] = EMAIL_USER
                msg['To'] = EMAIL_USER
                msg['Subject'] = assunto
                msg.attach(MIMEText(corpo_email, 'plain', 'utf-8'))
                
                server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
                server.starttls()
                server.login(EMAIL_USER, EMAIL_PASS)
                server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
                server.quit()
                print("[SUCESSO] Alerta macro enviado por e-mail!")
                break
            except Exception as e:
                print(f"[ERRO] Falha ao enviar email macro (tentativa {tentativa + 1}): {e}")
                if tentativa < 2:
                    time.sleep(5)

    # 2. Envio por Telegram (Em bloqueio urgente OU quando Debug está ativo)
    telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS", "true")).strip().lower() in ["true", "1", "sim", "yes"]
    debug_telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]
    
    if telegram_ativado and (urgente or debug_telegram_ativado):
        print("A enviar diagnóstico macro para o Telegram...")
        enviar_alerta(mensagem_tg)
    else:
        print("[INFO] Notificação Telegram omitida (sem bloqueio urgente e modo Debug desativado).")

def obter_preco_tempo_real(ticker_str, fallback_close):
    try:
        t = yf.Ticker(ticker_str, session=session)
        fast = t.fast_info
        for attr in ('pre_market_price', 'post_market_price', 'last_price'):
            val = getattr(fast, attr, None)
            if val is not None and not np.isnan(val) and float(val) > 0:
                return round(float(val), 2)
    except Exception:
        pass
    return round(float(fallback_close), 2)

def get_yf_data(ticker, period="1y"):
    for _ in range(3):
        try:
            df = yf.download(ticker, period=period, interval="1d", progress=False, session=session, timeout=15)
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                return df.dropna(subset=['Close'])
        except Exception:
            pass
        time.sleep(random.uniform(0.6, 1.4))
    return pd.DataFrame()

def desenhar_barra(valor, maximo=100, tamanho=10):
    preenchido = int((valor / maximo) * tamanho)
    preenchido = min(max(preenchido, 0), tamanho)
    return f"[{'█' * preenchido}{'░' * (tamanho - preenchido)}]"

# ===================================================================
# 2. AUDITORIA MACRO GLOBAL (INTERMARKET ANALYSIS - CALIBRADA)
# ===================================================================
print("A executar auditoria macro global do mercado US (Análise Intermarket)...")
data_hoje_str = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M:%S")

try:
    df_spy = get_yf_data("SPY", "2y")
    df_vix = get_yf_data("^VIX", "1y")
    df_vix3m = get_yf_data("^VIX3M", "1y")  # Volatilidade a 3 meses
    df_hyg = get_yf_data("HYG", "1y")       # Junk Bonds (Apetite por Risco)
    df_ief = get_yf_data("IEF", "1y")       # Safe Bonds (Fuga para Segurança)
    
    if df_spy.empty or len(df_spy) < 200 or df_vix.empty:
        msg_fallback = (
            f"⚠️ [AVISO MACRO] - DADOS INSUFICIENTES ({data_hoje_str})\n"
            f"Não foi possível obter histórico completo do SPY/VIX no Yahoo Finance. Pipeline autorizada com cautela."
        )
        print(f"[ERRO CRÍTICO] {msg_fallback}")
        gravar_ficheiro_macro(msg_fallback)
        sys.exit(0)

    motivos_bloqueio = []
    alertas_amarelos = []

    # A. AVALIAÇÃO CLÁSSICA: PREÇO, TENDÊNCIA & PÂNICO (SPY e VIX)
    df_spy['EMA_20'] = df_spy['Close'].ewm(span=20, adjust=False).mean()
    df_spy['SMA_50'] = df_spy['Close'].rolling(window=50).mean()
    df_spy['SMA_200'] = df_spy['Close'].rolling(window=200).mean()

    fecho_spy = float(df_spy['Close'].iloc[-1])
    fecho_spy_ontem = float(df_spy['Close'].iloc[-2])
    preco_spy = obter_preco_tempo_real("SPY", fecho_spy)

    ema20_spy = float(df_spy['EMA_20'].iloc[-1])
    sma50_spy = float(df_spy['SMA_50'].iloc[-1])
    sma200_spy = float(df_spy['SMA_200'].iloc[-1])

    var_fecho_spy = ((fecho_spy - fecho_spy_ontem) / fecho_spy_ontem) * 100
    var_viva_spy = ((preco_spy - fecho_spy) / fecho_spy) * 100
    queda_referencia = min(var_fecho_spy, var_viva_spy)

    vix_fecho = float(df_vix['Close'].iloc[-1])
    vix_hoje = obter_preco_tempo_real("^VIX", vix_fecho)

    if queda_referencia <= -2.00:
        motivos_bloqueio.append(f"Queda/Gap abrupto no SPY de {queda_referencia:.2f}% (<= -2.00%).")
    elif queda_referencia <= -1.25:
        alertas_amarelos.append(f"Pressão vendedora intradiária no SPY ({queda_referencia:.2f}%) — reduzir exposição.")

    if preco_spy < sma200_spy:
        motivos_bloqueio.append(f"SPY (${preco_spy:.2f}) abaixo da SMA 200 (${sma200_spy:.2f}) — Regime Baixista para Breakouts.")
    elif preco_spy < ema20_spy:
        alertas_amarelos.append(f"SPY (${preco_spy:.2f}) abaixo da EMA 20 (${ema20_spy:.2f}) — Pullback de curto prazo (evitar perseguir breakouts
