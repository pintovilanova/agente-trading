from datetime import datetime
from zoneinfo import ZoneInfo
import yfinance as yf
import pandas_ta as ta
import pandas as pd
import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O mercado está fechado. O Disjuntor Macro vai descansar.")
    sys.exit(0)

# ===================================================================
# 1. CONFIGURAÇÕES E CREDENCIAIS (GitHub Secrets)
# ===================================================================
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

def enviar_alerta_macro(assunto, corpo):
    print(f"\nA enviar alerta macro (Assunto: '{assunto}')...")
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] Credenciais de email em falta. A saltar envio.")
        return
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_USER
        msg['Subject'] = assunto
        
        msg.attach(MIMEText(corpo, 'plain', 'utf-8'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
        server.quit()
        print("[SUCESSO] Alerta macro enviado!")
    except Exception as e:
        print(f"[ERRO] Falha ao enviar email macro: {e}")

# ===================================================================
# 2. AUDITORIA MACRO GLOBAL (SPY & VIX)
# ===================================================================
print("A executar auditoria macro global do mercado US...")

try:
    # Descarregar SPY e VIX de forma isolada para garantir histórico limpo de 200 dias
    df_spy = yf.download("SPY", period="3y", interval="1d", progress=False)
    df_vix = yf.download("^VIX", period="1y", interval="1d", progress=False)
    
    if df_spy.empty or df_vix.empty:
        print("[ERRO CRÍTICO] Não foi possível obter dados macro do Yahoo Finance.")
        sys.exit(1)

    if isinstance(df_spy.columns, pd.MultiIndex):
        df_spy.columns = df_spy.columns.droplevel(1)
    if isinstance(df_vix.columns, pd.MultiIndex):
        df_vix.columns = df_vix.columns.droplevel(1)

    # Calcular SMA 200 explicitamente com pandas para evitar falhas do pandas_ta
    df_spy['SMA_200'] = df_spy['Close'].rolling(window=200).mean()

    spy_hoje = df_spy.iloc[-1]
    spy_ontem = df_spy.iloc[-2]
    vix_hoje = df_vix.iloc[-1]['Close']

    preco_spy = spy_hoje['Close']
    preco_spy_ontem = spy_ontem['Close']
    sma200_spy = spy_hoje['SMA_200']

    queda_spy = ((preco_spy - preco_spy_ontem) / preco_spy_ontem) * 100
    abaixo_sma200 = preco_spy < sma200_spy if pd.notna(sma200_spy) else False

    print(f"-> SPY Fecho: {preco_spy:.2f} USD (Var 1D: {queda_spy:.2f}%)")
    print(f"-> SPY SMA200: {sma200_spy:.2f} USD" if pd.notna(sma200_spy) else "-> SPY SMA200: A calcular (insuficiente)")
    print(f"-> VIX Atual: {vix_hoje:.2f}")

    # ===================================================================
    # 3. AVALIAÇÃO DE DISJUNTOR (CIRCUIT BREAKER)
    # ===================================================================
    motivos_bloqueio = []

    if queda_spy <= -1.50:
        motivos_bloqueio.append(f"Queda abrupta intradiária/diária no SPY de {queda_spy:.2f}% (<= -1.50%).")

    if abaixo_sma200:
        motivos_bloqueio.append(f"SPY ({preco_spy:.2f}) encontra-se abaixo da sua Média Móvel de 200 dias ({sma200_spy:.2f}) - Contexto de Bear Market.")

    if vix_hoje > 30.00:
        motivos_bloqueio.append(f"Índice de Volatilidade (VIX) nos {vix_hoje:.2f} (> 30.00) - Risco sistémico elevado.")

    if motivos_bloqueio:
        corpo_email = "🚨 [DISJUNTOR MACRO ATIVADO] - EXECUÇÃO DE PIPELINE ABORTADA\n\n"
        corpo_email += "O Motor Macro detetou condições anómalas ou hostilidades sistémicas no mercado norte-americano. Para proteger o capital, a abertura de novas posições foi totalmente bloqueada hoje.\n\n"
        corpo_email += "Motivos detetados:\n"
        for m in motivos_bloqueio:
            corpo_email += f"- {m}\n"
        corpo_email += f"\nData/Hora: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
        
        enviar_alerta_macro("tradingRelatorioIA US - 🚨 BLOQUEIO MACRO (DISJUNTOR ATIVO)", corpo_email)
        print(f"\n[BLOQUEIO] Condições macro hostil detetadas. A abortar pipeline.")
        sys.exit(1)  # Retorna código de erro para parar o workflow do GitHub Actions

    else:
        print("\n[OK] Mercado Saudável. Disjuntor Macro em verde. Pipeline autorizado a prosseguir.")
        sys.exit(0)  # Sucesso limpo

except Exception as e:
    print(f"[ERRO CRÍTICO] Falha na auditoria macro: {e}")
    sys.exit(1)
