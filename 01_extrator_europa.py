# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR DE BREAKOUTS (EUROPA)
# ===================================================================
from datetime import datetime
from zoneinfo import ZoneInfo
import yfinance as yf
import pandas_ta as ta
import pandas as pd
import requests
import os
import sys
import smtplib
import json
import numpy as np
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ===================================================================
# 0.1 TRAVA DE FIM DE SEMANA (Não corre ao Sábado e Domingo)
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O mercado está fechado. O Agente vai descansar.")
    sys.exit(0)

hoje_e_sexta = "SIM" if dia_da_semana == 4 else "NÃO"

# ===================================================================
# 0. CONFIGURAÇÕES E CREDENCIAIS (Lidas do GitHub Secrets)
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")
NOME_ABA_EUROPA = "Analise Compra EU"

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# ===================================================================
# 1. FUNÇÃO DE ENVIO DE EMAIL
# ===================================================================
def enviar_email_para_agente_ia(relatorio_texto, assunto="🇪🇺🎯 tradingRelatorioIA Europa 🛡️"):
    print(f"\nA enviar email para o Agente IA (Assunto: '{assunto}')...")
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_USER
        msg['Subject'] = assunto
        
        msg.attach(MIMEText(relatorio_texto, 'plain', 'utf-8'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
        server.quit()
        print(f"[SUCESSO] Email enviado! O teu Agente IA já pode ler a caixa de entrada.")
    except Exception as e:
        print(f"[ERRO] Falha ao enviar o email para o Agente IA: {e}")

# ===================================================================
# 2. BUSCAR A WATCHLIST E POSIÇÕES ATIVAS (Google Sheets via Webhook)
# ===================================================================
print(f"A carregar a Watchlist e Posições Ativas da Europa a partir do Google Sheets (Aba: {NOME_ABA_EUROPA})...")
try:
    url_get = f"{WEBHOOK_URL}?aba={NOME_ABA_EUROPA}"
    resposta_webhook = requests.get(url_get)
    if resposta_webhook.status_code == 200:
        dados_webhook = resposta_webhook.json()
        
        # Compatibilidade com a estrutura unificada
        if isinstance(dados_webhook, dict) and "ativos" in dados_webhook:
            ativos_data = dados_webhook.get("ativos", [])
            posicoes_ativas = dados_webhook.get("posicoesAtivas", {})
        elif isinstance(dados_webhook, list):
            ativos_data = dados_webhook
            posicoes_ativas = {}
        else:
            ativos_data = []
            posicoes_ativas = {}

        if len(ativos_data) > 0:
            print(f"[SUCESSO] {len(ativos_data)} ativos europeus carregados da Watchlist.")
            print(f"[SUCESSO] {len(posicoes_ativas)} posições ativas detetadas no Diário de Bordo.")
        else:
            print("[ERRO] A lista de ativos veio vazia.")
            sys.exit(1)
    else:
        print(f"[ERRO] Falha ao descarregar dados: {resposta_webhook.status_code}")
        sys.exit(1)
except Exception as e:
    print(f"[ERRO CRÍTICO] Falha de comunicação com Sheets: {e}")
    sys.exit(1)

# ===================================================================
# 3. VETO MACRO (SPY FLASH CRASH & BEAR MARKET)
# ===================================================================
print("\nA verificar Veto Macro (SPY)...")
try:
    df_spy = yf.download("SPY", period="2y", interval="1d", progress=False)
    if isinstance(df_spy.columns, pd.MultiIndex):
        df_spy.columns = df_spy.columns.droplevel(1)
        
    df_spy.ta.sma(length=200, append=True)
    spy_hoje = df_spy.iloc[-1]
    spy_ontem = df_spy.iloc[-2]
    
    preco_spy = spy_hoje['Close']
    preco_spy_ontem = spy_ontem['Close']
    sma200_spy = spy_hoje['SMA_200']
    
    queda_spy = ((preco_spy - preco_spy_ontem) / preco_spy_ontem) * 100
    
    if queda_spy <= -1.50:
        print(f"[BLOQUEIO] SPY em Pânico: Caiu {queda_spy:.2f}%. Execução abortada.")
        sys.exit(0)
        
    if preco_spy < sma200_spy:
        print(f"[BLOQUEIO] SPY em Baixa: Preço ({preco_spy:.2f}) abaixo da SMA200 ({sma200_spy:.2f}). Execução abortada.")
        sys.exit(0)
        
    print("[OK] SPY Saudável. A iniciar extração...\n")
except Exception as e:
    print(f"Erro na validação do SPY: {e}")

# Configurações de Risco
risco_maximo_dolares = 25.00
multiplicador_trailing_ts = 1.5
racio_tp_base = 1.2

dados_temporarios = []

# ===================================================================
# 4. MOTOR MATEMÁTICO V2 (Para todos os Ativos)
# ===================================================================
for ativo_info in ativos_data:
    ticker = ativo_info.get("ticker")
    nome_empresa = ativo_info.get("nome", "N/A")
    
    if not ticker or ticker == "#N/A":
        continue
    
    try:
        df = yf.download(ticker, period="2y", interval="1d", progress=False)
        if df.empty:
            print(f"[AVISO] Sem dados para {ticker}.")
            continue
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        alerta_earnings = "OK"
        setor = "Europa"
        try:
            ticker_obj = yf.Ticker(ticker)
            setor = ticker_obj.info.get('sector', 'Europa')
            
            calendario = ticker_obj.calendar
            if isinstance(calendario, dict) and 'Earnings Date' in calendario:
                proxima_data = calendario['Earnings Date'][0]
                if hasattr(proxima_data, 'date'):
                    proxima_data = proxima_data.date()
                
                hoje = datetime.now(ZoneInfo("Europe/Lisbon")).date()
                dias_restantes = (proxima_data - hoje).days
                
                if 0 <= dias_restantes <= 3:
                    alerta_earnings = f"PERIGO (em {dias_restantes} dias)"
        except Exception:
            pass

        df.ta.rsi(length=14, append=True)
        df.ta.adx(length=14, append=True)
        df.ta.atr(length=14, append=True)
        df.ta.sma(length=200, append=True)
        df.ta.sma(length=20, append=True)
        df.ta.mom(length=14, append=True)
        df.ta.ema(length=9, append=True)

        media_volume_20 = df['Volume'].rolling(window=20).mean()
        df['RVOL'] = df['Volume'] / media_volume_20

        ultimo_dia = df.iloc[-1]
        dia_anterior = df.iloc[-2]

        preco = ultimo_dia['Close']
        preco_anterior = dia_anterior['Close']
        var_perc = ((preco - preco_anterior) / preco_anterior) * 100
        
        sma20 = ultimo_dia['SMA_20']
        dist_mm20 = ((preco - sma20) / sma20) *
