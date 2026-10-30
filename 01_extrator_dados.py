# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR DE BREAKOUTS (EUA)
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
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import warnings
warnings.filterwarnings("ignore")

# Importação da função modular de notificação do Telegram
from F01_notificador_telegram import enviar_alerta

# ===================================================================
# 0.1 TRAVA DE FIM DE SEMANA (Não corre ao Sábado e Domingo)
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O mercado está fechado. O Agente vai descansar.")
    #sys.exit(0)

hoje_e_sexta = "SIM" if dia_da_semana == 4 else "NÃO"

# ===================================================================
# 0. CONFIGURAÇÕES E CREDENCIAIS (Lidas do GitHub Secrets)
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

def limpar_float(val):
    """Converte com segurança valores numéricos (mesmo com vírgulas) para float."""
    if val is None: return None
    try:
        val_str = str(val).replace(",", ".").strip()
        if val_str == "" or val_str.lower() in ["nan", "n/a", "none"]: return None
        return float(val_str)
    except (ValueError, TypeError):
        return None

# ===================================================================
# 1. FUNÇÃO DE ENVIO DE EMAIL (Com Sistema Anti-Falhas)
# ===================================================================
def enviar_email_para_agente_ia(relatorio_texto, assunto="🦅 tradingRelatorioIA US 🗽"):
    print(f"\nA enviar email para o Agente IA (Assunto: '{assunto}')...")
    
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] Credenciais de email em falta. A saltar envio.")
        return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = assunto
    
    msg.attach(MIMEText(relatorio_texto, 'plain', 'utf-8'))
    
    max_tentativas = 3
    for tentativa in range(max_tentativas):
        try:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
            server.quit()
            
            print(f"[SUCESSO] Email enviado na tentativa {tentativa + 1}! O teu Agente IA já pode ler a caixa de entrada.")
            break
            
        except Exception as e:
            print(f"[ERRO] Falha ao enviar o email (tentativa {tentativa + 1} de {max_tentativas}): {e}")
            if tentativa < max_tentativas - 1:
                print("A aguardar 5 segundos antes de tentar novamente...")
                time.sleep(5)
            else:
                print("[ERRO CRÍTICO] O servidor Gmail fechou a ligação definitivamente. Falha no envio.")

# ===================================================================
# 2. BUSCAR A WATCHLIST, POSIÇÕES ATIVAS E CONFIGS (Google Sheets via Webhook)
# ===================================================================
print("A carregar a Watchlist, Posições Ativas e Configurações a partir do Google Sheets...")
configs_data = {}
try:
    resposta_webhook = requests.get(WEBHOOK_URL, timeout=15)
    if resposta_webhook.status_code == 200:
        dados_webhook = resposta_webhook.json()
        
        if isinstance(dados_webhook, dict) and "ativos" in dados_webhook:
            ativos_data = dados_webhook.get("ativos", [])
            posicoes_ativas = dados_webhook.get("posicoesAtivas", {})
            configs_data = dados_webhook.get("configs", {})
        elif isinstance(dados_webhook, list):
            ativos_data = dados_webhook
            posicoes_ativas = {}
            configs_data = {}
        else:
            ativos_data = []
            posicoes_ativas = {}
            configs_data = {}

        if len(ativos_data) > 0:
            print(f"[SUCESSO] {len(ativos_data)} ativos carregados da Watchlist.")
            print(f"[SUCESSO] {len(posicoes_ativas)} posições ativas detetadas no Diário de Bordo.")
        else:
            print("[AVISO] A lista de ativos veio vazia. A terminar a execução sem erro.")
            sys.exit(0)
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
        
    df_spy = df_spy.dropna(subset=['Close', 'High', 'Low'])
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
# CONFIGURAÇÕES DE RISCO INSTITUCIONAL (MÉSTATIC/CARVER)
# ===================================================================
try:
    CAPITAL_TOTAL_CONTA = float(configs_data.get("CAPITAL_TOTAL_CONTA", 10400.00))
    ALVO_VOLATILIDADE_ANUAL = float(configs_data.get("ALVO_VOLATILIDADE_ANUAL", 0.05))
except (ValueError, TypeError):
    CAPITAL_TOTAL_CONTA = 10400.00
    ALVO_VOLATILIDADE_ANUAL = 0.05

print(f"[CONFIG] Capital Total da Conta: ${CAPITAL_TOTAL_CONTA:,.2f}")
print(f"[CONFIG] Alvo Volatilidade Anual: {ALVO_VOLATILIDADE_ANUAL*100:.1f}%")

VOLATILIDADE_ALVO_DIARIA_USD = (CAPITAL_TOTAL_CONTA * ALVO_VOLATILIDADE_ANUAL) / 16.0 

# REGRAS OTIMIZADAS
multiplicador_trailing_ts = 1.5
racio_tp_base = 3.0 

dados_temporarios = []

# ===================================================================
# 4. MOTOR MATEMÁTICO V2 (Para todos os Ativos)
# ===================================================================
for ativo_info in ativos_data:
    ticker = str(ativo_info.get("ticker", "")).strip().upper()
    nome_empresa = ativo_info.get("nome", "N/A")
    rs_score = ativo_info.get("rs_score", "N/A")
    setor = str(ativo_info.get("setor", "Desconhecido")).strip()
    
    if not ticker or ticker == "#N/A" or ticker == "NONE":
        continue

    if ticker == "BRK-A":
        print("[AJUSTE] Ticker BRK-A convertido automaticamente para BRK-B.")
        ticker = "BRK-B"

    try:
        df = yf.download(ticker, period="2y", interval="1d", progress=False)
        if df.empty:
            print(f"[AVISO] Sem dados para {ticker}.")
            continue
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])
        if df.empty or len(df) < 50:
            continue

        alerta_earnings = "OK"
        try:
            ticker_obj = yf.Ticker(ticker)
            
            if setor in ["Desconhecido", "N/A", "", "NONE"]:
                setor_yf = ticker_obj.info.get('sector')
                if setor_yf:
                    setor = setor_yf

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

        df = df.dropna(subset=['RSI_14', 'ADX_14', 'ATRr_14', 'SMA_20', 'EMA_9', 'MOM_14'])
        if df.empty: continue

        ultimo_dia = df.iloc[-1]
        dia_anterior = df.iloc[-2]

        preco = ultimo_dia['Close']
        preco_anterior = dia_anterior['Close']
        var_perc = ((preco - preco_anterior) / preco_anterior) * 100
        
        sma20 = ultimo_dia['SMA_20']
        dist_mm20 = ((preco - sma20) / sma20) * 100
        
        ema9 = ultimo_dia['EMA_9']
        ema9_anterior = dia_anterior['EMA_9']
        
        cruzou_ema9 = (preco > ema9) and (preco_anterior <= ema9_anterior) if pd.notna(ema9) and pd.notna(ema9_anterior) else False
        acima_ema9 = preco > ema9 if pd.notna(ema9) else False

        rvol = ultimo_dia['RVOL']
        adx = ultimo_dia['ADX_14']
        rsi = ultimo_dia['RSI_14']
        atr = ultimo_dia['ATRr_14']
        momentum = ultimo_dia['MOM_14']

        atr_perc = round((atr / preco) * 100, 2) if pd.notna(atr) and pd.notna(preco) and preco > 0 else "N/A"

        recomendacao = "Observar"
        preco_entrada = "N/A"
        preco_stop = "N/A"
        preco_tp = "N/A"
        preco_be = "N/A"
        qtd_acoes = "N/A"
        multiplicador_atr = 1.0

        trailing_base = preco - (atr * multiplicador_trailing_ts) if pd.notna(preco) and pd.notna(atr) else "N/A"
        trailing_final = round(trailing_base, 2) if trailing_base != "N/A" else "N/A"

        preco_caiu_hoje = preco < preco_anterior if pd.notna(preco) and pd.notna(preco_anterior) else False
        volume_despejo = rvol > 1.20 if pd.notna(rvol) else False

        if pd.isna(momentum) or pd.isna(adx) or pd.isna(rvol) or pd.isna(rsi) or pd.isna(dist_mm20) or pd.isna(atr):
             recomendacao = "Observar"
        elif (preco_caiu_hoje and volume_despejo) or (momentum <= 0.5):
            recomendacao = "Observar"
            
        elif var_perc > 0 and adx < 25 and not cruzou_ema9:
            recomendacao = "Aguardar Recuo"
            preco_entrada = round(preco - (atr * 0.4), 2)
            multiplicador_atr = 1.0
            
        elif cruzou_ema9 and rvol > 1.00 and momentum > 0.50 and rsi > 50 and dist_mm20 <= 3.00:
            recomendacao = "Ignicao EMA9"
            preco_entrada = round(preco - (atr * 0.1), 2)
            multiplicador_
