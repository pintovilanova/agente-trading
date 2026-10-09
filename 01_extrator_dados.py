# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR DE BREAKOUTS (EUA)
# ===================================================================
# Descrição Geral:
# Este script opera como um "Predador de Breakouts" automatizado na nuvem 
# (via GitHub Actions). O seu objetivo é varrer a Watchlist, auditar a saúde 
# macroeconómica, calcular posições com base na volatilidade institucional 
# (Método Carver) e enviar um relatório estruturado por email para triagem de uma IA.
#
# Pilares Técnicos e Arquitetura de Execução:
# 1. Travas de Segurança e Calendário:
#    - Trava de Fim de Semana: Aborta automaticamente aos sábados e domingos.
#    - Veto Macro (SPY): Cancela a execução se o SPY estiver em pânico (queda >= 1.5%) 
#      ou se negociar abaixo da sua SMA de 200 períodos (Bear Market).
# 2. Gestão de Risco Institucional (Target Volatility - Método Carver):
#    - Orçamento de flutuação diária calculado sobre o capital total da conta 
#      ($10,400.00) com um alvo de volatilidade anual conservador (5%).
#    - Dimensionamento dinâmico baseado no ATR (Average True Range) para 
#      nivelar o risco real por ativo, independentemente do preço nominal.
# 3. Auditoria Macro e Lotes Defensivos:
#    - Avaliação coletiva da Watchlist: se 70% ou mais dos ativos estiverem 
#      estagnados ("Observar" ou "Aguardar Recuo"), o sistema decreta "Ambiente 
#      Hostil" e corta automaticamente o lote de todas as ordens para 50%.
#    - Redução automática de lote obrigatória às sextas-feiras.
# 4. Integração Cloud & LLM:
#    - Sincronização bidirecional com Google Sheets via Webhook.
#    - Envio de prompt e dados estruturados ("Comboio") para auditoria autónoma por IA.
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

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# ===================================================================
# 1. FUNÇÃO DE ENVIO DE EMAIL
# ===================================================================
def enviar_email_para_agente_ia(relatorio_texto, assunto="🦅 tradingRelatorioIA US 🗽"):
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
print("A carregar a Watchlist e Posições Ativas a partir do Google Sheets...")
try:
    resposta_webhook = requests.get(WEBHOOK_URL)
    if resposta_webhook.status_code == 200:
        dados_webhook = resposta_webhook.json()
        
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
            print(f"[SUCESSO] {len(ativos_data)} ativos carregados da Watchlist.")
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

# ===================================================================
# CONFIGURAÇÕES DE RISCO INSTITUCIONAL (MÉTODO CARVER)
# ===================================================================
CAPITAL_TOTAL_CONTA = 10400.00  # <-- AJUSTA AQUI O VALOR DA TUA CONTA (Trading212 / XTB)
ALVO_VOLATILIDADE_ANUAL = 0.05 # Alvo de 20% ao ano de flutuação de capital (Padrão Quant)

# Calcula o orçamento diário de volatilidade (dividido pela constante 16, raiz de 256 dias úteis)
VOLATILIDADE_ALVO_DIARIA_USD = (CAPITAL_TOTAL_CONTA * ALVO_VOLATILIDADE_ANUAL) / 16.0 

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
        setor = "Descon
