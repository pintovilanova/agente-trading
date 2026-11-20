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
# 2. AUDITORIA MACRO GLOBAL (INTERMARKET ANALYSIS)
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

    if queda_referencia <= -1.50:
        motivos_bloqueio.append(f"Queda/Gap abrupto no SPY de {queda_referencia:.2f}% (<= -1.50%).")
    if preco_spy < sma200_spy:
        motivos_bloqueio.append(f"SPY (${preco_spy:.2f}) abaixo da SMA 200 (${sma200_spy:.2f}) — Regime Baixista.")
    elif preco_spy < ema20_spy:
        alertas_amarelos.append(f"SPY (${preco_spy:.2f}) abaixo da EMA 20 (${ema20_spy:.2f}) — Pullback de curto prazo (evitar perseguir breakouts).")

    if vix_hoje > 30.00:
        motivos_bloqueio.append(f"VIX nos {vix_hoje:.2f} (> 30.00) — Pânico sistémico elevado.")
    elif vix_hoje > 23.00:
        alertas_amarelos.append(f"VIX elevado nos {vix_hoje:.2f} (> 23.00) — Volatilidade acima do normal (reduzir lote para 50%).")

    # B. AVALIAÇÃO DE ESTRUTURA DE VOLATILIDADE (Curva do VIX)
    vix3m_hoje = None
    razao_vix = None
    if not df_vix3m.empty:
        vix3m_hoje = float(df_vix3m['Close'].iloc[-1])
        razao_vix = vix_hoje / vix3m_hoje if vix3m_hoje > 0 else 0.0
        if razao_vix >= 1.00:
            motivos_bloqueio.append(f"Curva VIX Invertida (Backwardation): VIX ({vix_hoje:.2f}) >= VIX3M ({vix3m_hoje:.2f}) [Rácio {razao_vix:.2f}].")
        elif razao_vix > 0.90:
            alertas_amarelos.append(f"Curva VIX sob pressão (Rácio VIX/VIX3M: {razao_vix:.2f} > 0.90) — Institucional a comprar proteção.")

    # C. AVALIAÇÃO DO MERCADO DE CRÉDITO (HYG vs IEF)
    credito_disponivel = False
    ratio_atual = 0.0
    ratio_sma50 = 0.0
    diff_credito_pct = 0.0
    if not df_hyg.empty and not df_ief.empty:
        df_credito = pd.DataFrame({
            'HYG': df_hyg['Close'],
            'IEF': df_ief['Close']
        }).dropna()
        if len(df_credito) >= 50:
            df_credito['Ratio'] = df_credito['HYG'] / df_credito['IEF']
            df_credito['Ratio_SMA50'] = df_credito['Ratio'].rolling(window=50).mean()
            df_credito = df_credito.dropna()
            if not df_credito.empty:
                credito_disponivel = True
                ratio_atual = float(df_credito['Ratio'].iloc[-1])
                ratio_sma50 = float(df_credito['Ratio_SMA50'].iloc[-1])
                diff_credito_pct = ((ratio_atual - ratio_sma50) / ratio_sma50) * 100
                if ratio_atual < (ratio_sma50 * 0.985):
                    motivos_bloqueio.append(f"Estresse de Crédito Institucional: Rácio HYG/IEF ({ratio_atual:.4f}) caiu {diff_credito_pct:.2f}% abaixo da SMA 50 ({ratio_sma50:.4f}).")
                elif ratio_atual < ratio_sma50:
                    alertas_amarelos.append(f"Crédito High-Yield ligeiramente abaixo da média (HYG/IEF {diff_credito_pct:+.2f}% vs SMA 50).")

    # ===================================================================
    # 3. VEREDICTO E AÇÃO DO DISJUNTOR (COM PAINEL VISUAL)
    # ===================================================================
    if motivos_bloqueio:
        corpo_email = "🚨 [DISJUNTOR MACRO VERMELHO] - MERCADO HOSTIL (NOVAS COMPRAS BLOQUEADAS)\n\n"
        corpo_email += "O Motor Intermarket detetou hostilidades sistémicas no mercado norte-americano.\n"
        corpo_email += "⚠️ DIRETRIZ OPERACIONAL: Novas compras BLOQUEADAS. A pipeline prossegue apenas para auditar e proteger as POSIÇÕES ATIVAS.\n\n"
        corpo_email += "MOTIVOS CRÍTICOS DE BLOQUEIO:\n"
        for m in motivos_bloqueio:
            corpo_email += f"❌ {m}\n"
        
        if alertas_amarelos:
            corpo_email += "\nSINAIS SECUNDÁRIOS DE TENSÃO:\n"
            for a in alertas_amarelos:
                corpo_email += f"⚠️ {a}\n"

        corpo_email += f"\nResumo Indicadores: SPY ${preco_spy:.2f} (SMA200: ${sma200_spy:.2f}) | VIX {vix_hoje:.2f}"
        if razao_vix is not None:
            corpo_email += f" | VIX/VIX3M {razao_vix:.2f}"
        corpo_email += f"\nData/Hora: {data_hoje_str}"

        motivos_tg = "\n".join([f"❌ {m}" for m in motivos_bloqueio])
        mensagem_tg = (
            f"🚨 *DISJUNTOR MACRO VERMELHO*\n\n"
            f"🛑 *Novas Compras Bloqueadas* (Gestão de ativas mantida):\n"
            f"{motivos_tg}\n\n"
            f"📊 SPY: *${preco_spy:.2f}* | VIX: *{vix_hoje:.2f}*"
        )

        gravar_ficheiro_macro(corpo_email)
        enviar_alerta_macro(
            "tradingRelatorioIA US - 🚨 DISJUNTOR MACRO VERMELHO (COMPRAS BLOQUEADAS)",
            corpo_email,
            mensagem_tg,
            urgente=True
        )
        
        print("\n[ALERTA MACRO] Condições macro hostis. Novas compras bloqueadas. Pipeline segue para gestão de ativas.")
        sys.exit(0)

    else:
        distancia_sma200 = ((preco_spy - sma200_spy) / sma200_spy) * 100
        regime_label = "🟡 [DISJUNTOR MACRO AMARELO] - MERCADO EM CAUTELA" if alertas_amarelos else "✅ [DISJUNTOR MACRO VERDE] - MERCADO SAUDÁVEL"
        assunto_email = (
            "tradingRelatorioIA US - 🟡 DISJUNTOR MACRO AMARELO (CAUTELA)"
            if alertas_amarelos else
            "tradingRelatorioIA US - ✅ DISJUNTOR MACRO VERDE (MERCADO SAUDÁVEL)"
        )

        print(f"\n[OK] {regime_label}. Pipeline autorizada.")

        corpo_verde = f"{regime_label}\n\n"
        if alertas_amarelos:
            corpo_verde += "⚠️ ALERTAS AMARELOS DE CAUTELA (OPERAR COM SELETIVIDADE / LOTE REDUZIDO):\n"
            for a in alertas_amarelos:
                corpo_verde += f"• ⚠️ {a}\n"
            corpo_verde += "\n"
        else:
            corpo_verde += "O Motor Intermarket confirmou que o capital institucional suporta o mercado sem tensões sistémicas. Pipeline autorizada a 100%.\n\n"

        corpo_verde += "📊 PAINEL DE CONTROLO MACRO (RADAR INSTITUCIONAL)\n"
        corpo_verde += "==================================================\n"
        
        status_spy = "🟢 BULL MARKET (> EMA20 & SMA200)" if preco_spy >= ema20_spy else "🟡 PULLBACK CURTO PRAZO (< EMA20, > SMA200)"
        corpo_verde += f"1. TENDÊNCIA S&P 500 (SPY): {status_spy}\n"
        corpo_verde += f"   Cotação: ${preco_spy:.2f} (Var Dia: {var_fecho_spy:+.2f}%) | EMA20: ${ema20_spy:.2f} | SMA50: ${sma50_spy:.2f} | SMA200: ${sma200_spy:.2f}\n"
        corpo_verde += f"   Termómetro vs SMA200: {desenhar_barra(distancia_sma200, maximo=15, tamanho=10)} +{distancia_sma200:.1f}% acima do suporte longo.\n\n"
        
        status_vix = "🟡 ATENÇÃO (> 23)" if vix_hoje > 23 else ("🟢 MODERADO" if vix_hoje > 18 else "🟢 TRANQUILO")
        corpo_verde += f"2. ÍNDICE DE PÂNICO (VIX): {status_vix}\n"
        corpo_verde += f"   Valor Atual: {vix_hoje:.2f} (Alerta: > 23.00 | Crítico: > 30.00)\n"
        corpo_verde += f"   Termómetro: {desenhar_barra(vix_hoje, maximo=35, tamanho=10)}\n\n"
        
        if vix3m_hoje and razao_vix is not None:
            estado_vix_curva = "🟡 ALERTA AMARELO (> 0.90)" if razao_vix > 0.90 else "🟢 CONTANGO SAUDÁVEL"
            corpo_verde += f"3. ESTRUTURA DE CURVA (VIX vs VIX3M): {estado_vix_curva}\n"
            corpo_verde += f"   Rácio Atual: {razao_vix:.2f} (VIX {vix_hoje:.2f} / VIX3M {vix3m_hoje:.2f} | Crítico: >= 1.00)\n"
            corpo_verde += f"   Termómetro: {desenhar_barra(razao_vix * 100, maximo=100, tamanho=10)}\n\n"

        if credito_disponivel:
            estado_credito = "🟡 TENSÃO LEVE (< SMA50)" if ratio_atual < ratio_sma50 else "🟢 APETITE POR RISCO (RISK-ON)"
            corpo_verde += f"4. MERCADO DE CRÉDITO (HYG / IEF): {estado_credito}\n"
            corpo_verde += f"   Rácio Atual: {ratio_atual:.4f} vs SMA50: {ratio_sma50:.4f} ({diff_credito_pct:+.2f}%)\n"
            corpo_verde += f"   Termómetro: {desenhar_barra(50 + (diff_credito_pct * 10), maximo=100, tamanho=10)}\n"
        
        corpo_verde += "==================================================\n"
        corpo_verde += f"Data/Hora de Execução: {data_hoje_str}"

        status_tg = "🟡 *DISJUNTOR MACRO AMARELO*" if alertas_amarelos else "✅ *DISJUNTOR MACRO VERDE*"
        mensagem_tg = (
            f"{status_tg}\n\n"
            f"📊 SPY: *${preco_spy:.2f}* ({var_fecho_spy:+.2f}%) | VIX: *{vix_hoje:.2f}*\n"
            f"📈 Curva VIX/VIX3M: *{razao_vix:.2f}*" if razao_vix is not None else
            f"{status_tg}\n\n📊 SPY: *${preco_spy:.2f}* ({var_fecho_spy:+.2f}%) | VIX: *{vix_hoje:.2f}*"
        )
        
        gravar_ficheiro_macro(corpo_verde)
        enviar_alerta_macro(assunto_email, corpo_verde, mensagem_tg, urgente=False)
        sys.exit(0)

except Exception as e:
    print(f"[ERRO CRÍTICO] Falha na auditoria macro: {e}")
    gravar_ficheiro_macro(f"⚠️ [ERRO MACRO] Falha técnica na auditoria ({data_hoje_str}): {e}\n")
    sys.exit(0)
