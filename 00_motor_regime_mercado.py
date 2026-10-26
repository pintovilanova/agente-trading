import yfinance as yf
import pandas as pd
import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from zoneinfo import ZoneInfo
import time
import random
import warnings
warnings.filterwarnings("ignore")

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

# Função robusta de extração para evitar bloqueios do Yahoo Finance
def get_yf_data(ticker, period="1y"):
    for _ in range(3):
        try:
            df = yf.download(ticker, period=period, interval="1d", progress=False, timeout=15)
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                return df.dropna(subset=['Close'])
        except Exception:
            pass
        time.sleep(random.uniform(1.0, 2.0))
    return pd.DataFrame()

# ===================================================================
# 2. AUDITORIA MACRO GLOBAL (INTERMARKET ANALYSIS)
# ===================================================================
print("A executar auditoria macro global do mercado US (Análise Intermarket)...")

try:
    df_spy = get_yf_data("SPY", "3y")
    df_vix = get_yf_data("^VIX", "1y")
    df_vix3m = get_yf_data("^VIX3M", "1y")  # Volatilidade a 3 meses
    df_hyg = get_yf_data("HYG", "1y")       # Junk Bonds (Apetite por Risco)
    df_ief = get_yf_data("IEF", "1y")       # Safe Bonds (Fuga para Segurança)
    
    if df_spy.empty or df_vix.empty:
        print("[ERRO CRÍTICO] Não foi possível obter dados macro base (SPY/VIX).")
        sys.exit(1)

    motivos_bloqueio = []
    alertas_amarelos = []

    # A. AVALIAÇÃO CLÁSSICA: PREÇO & PÂNICO (SPY e VIX)
    df_spy['SMA_200'] = df_spy['Close'].rolling(window=200).mean()
    preco_spy = float(df_spy['Close'].iloc[-1])
    preco_spy_ontem = float(df_spy['Close'].iloc[-2])
    sma200_spy = float(df_spy['SMA_200'].iloc[-1])
    queda_spy = ((preco_spy - preco_spy_ontem) / preco_spy_ontem) * 100
    vix_hoje = float(df_vix['Close'].iloc[-1])

    if queda_spy <= -1.50:
        motivos_bloqueio.append(f"Queda abrupta no SPY de {queda_spy:.2f}% (<= -1.50%).")
    if preco_spy < sma200_spy:
        motivos_bloqueio.append(f"SPY ({preco_spy:.2f}) abaixo da SMA 200 ({sma200_spy:.2f}) - Contexto de Bear Market.")
    if vix_hoje > 30.00:
        motivos_bloqueio.append(f"VIX nos {vix_hoje:.2f} (> 30.00) - Pânico sistémico elevado.")

    # B. AVALIAÇÃO DE ESTRUTURA DE VOLATILIDADE (Curva do VIX)
    vix3m_hoje = None
    if not df_vix3m.empty:
        vix3m_hoje = float(df_vix3m['Close'].iloc[-1])
        razao_vix = vix_hoje / vix3m_hoje
        # Se o VIX > VIX3M (Rácio >= 1.0), o mercado está em Backwardation (Estresse Imediato Máximo)
        if razao_vix >= 1.0:
            motivos_bloqueio.append(f"Curva VIX Invertida (Backwardation). VIX ({vix_hoje:.2f}) > VIX3M ({vix3m_hoje:.2f}). Liquidez institucional a secar.")
        elif razao_vix > 0.90:
            alertas_amarelos.append(f"Curva VIX sob pressão (Rácio {razao_vix:.2f}). Risco de inversão iminente.")

    # C. AVALIAÇÃO DO MERCADO DE CRÉDITO (HYG vs IEF)
    if not df_hyg.empty and not df_ief.empty:
        df_credito = pd.DataFrame()
        df_credito['HYG'] = df_hyg['Close']
        df_credito['IEF'] = df_ief['Close']
        # Criação de um rácio de apetite por risco (Lixo vs Segurança)
        df_credito['Ratio'] = df_credito['HYG'] / df_credito['IEF']
        df_credito['Ratio_SMA50'] = df_credito['Ratio'].rolling(window=50).mean()
        df_credito = df_credito.dropna()
        
        if not df_credito.empty:
            ratio_atual = float(df_credito['Ratio'].iloc[-1])
            ratio_sma50 = float(df_credito['Ratio_SMA50'].iloc[-1])
            
            # Se o rácio cai mais de 1.5% abaixo da sua média móvel de 50 dias, há fuga maciça para segurança.
            if ratio_atual < (ratio_sma50 * 0.985):
                motivos_bloqueio.append(f"Estresse de Crédito Institucional detetado. Rácio HYG/IEF caiu abaixo do suporte crítico.")

    # ===================================================================
    # 3. VEREDICTO E AÇÃO DO DISJUNTOR
    # ===================================================================
    if motivos_bloqueio:
        corpo_email = "🚨 [DISJUNTOR MACRO ATIVADO] - EXECUÇÃO DE PIPELINE ABORTADA\n\n"
        corpo_email += "O Motor Macro detetou hostilidades sistémicas no mercado norte-americano (Ações, Volatilidade ou Obrigações).\nPara proteger o capital, a abertura de novas posições foi totalmente bloqueada hoje.\n\n"
        corpo_email += "MOTIVOS CRÍTICOS DETETADOS:\n"
        for m in motivos_bloqueio:
            corpo_email += f"❌ {m}\n"
        
        corpo_email += f"\nData/Hora: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
        enviar_alerta_macro("tradingRelatorioIA US - 🚨 BLOQUEIO MACRO (DISJUNTOR ATIVO)", corpo_email)
        print(f"\n[BLOQUEIO] Condições macro hostis detetadas. A abortar pipeline.")
        sys.exit(1)  

    else:
        print("\n[OK] Mercado Saudável. Disjuntor Macro em verde. Pipeline autorizada.")
        
        corpo_verde = "✅ [DISJUNTOR MACRO VERDE] - MERCADO SAUDÁVEL\n\n"
        corpo_verde += "A Análise Intermarket confirmou que a estrutura de liquidez, volatilidade e crédito dos EUA estão saudáveis. A pipeline de trading está autorizada a prosseguir e acionar gatilhos de compra.\n\n"
        corpo_verde += f"📊 DADOS MACRO DO DIA:\n"
        corpo_verde += f"📈 SPY Fecho: {preco_spy:.2f} USD (Var: {queda_spy:.2f}% | SMA200: {sma200_spy:.2f})\n"
        corpo_verde += f"📉 VIX: {vix_hoje:.2f} (Estrutura Normalizada)\n"
        
        if alertas_amarelos:
            corpo_verde += "\n⚠️ AVISOS DE ATENÇÃO (NÃO BLOQUEANTES):\n"
            for a in alertas_amarelos:
                corpo_verde += f"- {a}\n"
                
        corpo_verde += f"\nData/Hora de Execução: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
        enviar_alerta_macro("tradingRelatorioIA US - ✅ MERCADO SAUDÁVEL", corpo_verde)
        sys.exit(0)  

except Exception as e:
    print(f"[ERRO CRÍTICO] Falha na auditoria macro: {e}")
    sys.exit(1)
