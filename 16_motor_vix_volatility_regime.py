# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR 16 (VOLATILITY REGIME & VIX)
# ===================================================================
import os
import sys
import requests
import yfinance as yf
import numpy as np
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
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
# 0. TRAVA DE FIM DE SEMANA & CONFIGURAÇÕES
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O Motor 16 vai descansar.")
    # sys.exit(0)

WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

def gravar_ficheiro_vix(conteudo):
    with open("comboio_vix_temp.txt", "w", encoding="utf-8") as f:
        f.write(conteudo)

def obter_vix_tempo_real(ticker_str, fallback_close):
    try:
        t = yf.Ticker(ticker_str, session=session)
        fast = t.fast_info
        for attr in ('last_price', 'pre_market_price', 'post_market_price'):
            val = getattr(fast, attr, None)
            if val is not None and not np.isnan(val) and float(val) > 0:
                return round(float(val), 2)
    except Exception:
        pass
    return round(float(fallback_close), 2)

def obter_volatilidade_europa():
    """
    Substitui o descontinuado ^V2TX pelo cálculo da Volatilidade Realizada
    Anualizada (20 sessões) do Euro Stoxx 50 (^STOXX50E / FEZ), eliminando erros 404.
    """
    for ticker_eu in ["^STOXX50E", "FEZ"]:
        try:
            df_eu = yf.download(ticker_eu, period="3mo", interval="1d", progress=False, session=session, timeout=15)
            if not df_eu.empty and len(df_eu) >= 22:
                if isinstance(df_eu.columns, pd.MultiIndex):
                    df_eu.columns = df_eu.columns.droplevel(1)
                retornos_eu = df_eu['Close'].dropna().pct_change().dropna()
                if len(retornos_eu) >= 20:
                    vol_20d = float(retornos_eu.tail(20).std() * np.sqrt(252) * 100)
                    return f" | Vol EU 20D ({ticker_eu}): {vol_20d:.2f}%"
        except Exception:
            pass
    return ""

print("A iniciar Motor 16 - Volatility Regime & VIX Dynamic Targeting...")

configs_dict = {}
if WEBHOOK_URL:
    try:
        url_alvo = WEBHOOK_URL if "?" in WEBHOOK_URL else f"{WEBHOOK_URL}?aba=Analise Compra"
        resp = requests.get(url_alvo, timeout=15)
        if resp.status_code == 200:
            json_data = resp.json()
            if isinstance(json_data, dict):
                configs_dict = json_data.get("configs", {})
    except Exception as e:
        print(f"[AVISO] Não foi possível ler as configurações do Sheets: {e}")

data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M")

try:
    # Obter histórico do VIX (^VIX) via yfinance
    df_vix = yf.download("^VIX", period="3mo", interval="1d", progress=False, session=session, timeout=15)
    if df_vix.empty or len(df_vix) < 20:
        print("[AVISO] Não foi possível obter dados do VIX. A assumir regime Neutro (100%) e a gravar fallback.")
        bloco_fallback = (
            f"🟡 MOTOR 16: REGIME DE VOLATILIDADE VIX ({data_hoje})\n"
            f"📊 VIX Atual: N/A (Falha temporária Yahoo Finance)\n"
            f"STATUS MACRO: REGIME NEUTRO (FALLBACK)\n"
            f"   - Lote Máximo Breakouts (US / Europa): 100%\n"
            f"   - Lote Máximo Trend Carver / Reversão: 100%\n"
            f"   - INSTRUÇÃO TÁTICA: Dados VIX indisponíveis; aplicar filtros padrão do SPY/EMA20.\n"
            f"--------------------------------------------------\n"
        )
        gravar_ficheiro_vix(bloco_fallback)
        sys.exit(0)
        
    if isinstance(df_vix.columns, pd.MultiIndex):
        df_vix.columns = df_vix.columns.droplevel(1)
        
    vix_fecho = float(df_vix['Close'].iloc[-1])
    vix_anterior = float(df_vix['Close'].iloc[-2])
    vix_rt = obter_vix_tempo_real("^VIX", vix_fecho)
    vix_atual = max(vix_fecho, vix_rt)
    vix_var_dia = ((vix_atual - vix_anterior) / vix_anterior) * 100 if vix_anterior > 0 else 0.0
    
    # Média Móvel de 20 períodos para o VIX
    df_vix['SMA_20'] = df_vix['Close'].rolling(window=20).mean()
    vix_sma20 = float(df_vix['SMA_20'].iloc[-1])

    # Volatilidade Realizada Europeia (^STOXX50E / FEZ) sem chamar o ^V2TX
    info_vol_eu = obter_volatilidade_europa()

    # Deteção de choque súbito de volatilidade (Spike > +15% no dia ou > 25% acima da SMA20)
    spike_volatilidade = (vix_var_dia >= 15.0) or (vix_sma20 > 0 and vix_atual >= vix_sma20 * 1.25)
    
    # ===================================================================
    # DETERMINAÇÃO DO REGIME E MULTIPLICADOR DE LOTE (ALINHADO COM DISJUNTOR MACRO)
    # ===================================================================
    alerta_critico_macro = False

    if vix_atual >= 30.0:
        regime_nome = "PÂNICO SISTÉMICO EXTREMO"
        lote_breakout_pct = 0
        lote_carver_pct = 25
        instrucao = "🚨 VIX EM PÂNICO (>= 30)! BLOQUEIO TOTAL de novas entradas em Breakouts. Apenas Mean Reversion/Trend reduzido a 25%."
        cor_alerta = "🔴"
        alerta_critico_macro = True
    elif 23.0 <= vix_atual < 30.0 or (spike_volatilidade and vix_atual >= 20.0):
        regime_nome = "ALTA VOLATILIDADE / TENSÃO" + (" (SPIKE VIX!)" if spike_volatilidade else "")
        lote_breakout_pct = 50
        lote_carver_pct = 75
        instrucao = "Volatilidade elevada (23–30) ou choque súbito. Redução rigorosa de lote para 50% em Breakouts e 75% em Trend."
        cor_alerta = "🟠"
        if spike_volatilidade:
            alerta_critico_macro = True
    elif 18.0 <= vix_atual < 23.0 or spike_volatilidade:
        regime_nome = "MODERADO / ALERTA" + (" (SPIKE VIX!)" if spike_volatilidade else "")
        lote_breakout_pct = 75
        lote_carver_pct = 100
        instrucao = "Volatilidade moderada com ruído intradiário. Lote de Breakout ajustado para 75%."
        cor_alerta = "🟡"
    else:  # VIX < 18.0 e sem spike
        regime_nome = "CALMO / VENTO A FAVOR"
        lote_breakout_pct = 100
        lote_carver_pct = 100
        instrucao = "Ambiente institucional calmo e propício a expansão de tendência. Utilizar dimensão total (100%)."
        cor_alerta = "🟢"

except Exception as e:
    print(f"[ERRO CRÍTICO] Falha ao calcular Motor 16 (VIX): {e}")
    bloco_erro = (
        f"⚠️ MOTOR 16: REGIME DE VOLATILIDADE VIX ({data_hoje})\n"
        f"STATUS MACRO: ERRO DE LEITURA ({e})\n"
        f"   - Lote Máximo Breakouts (US / Europa): 75%\n"
        f"   - Lote Máximo Trend Carver / Reversão: 75%\n"
        f"--------------------------------------------------\n"
    )
    gravar_ficheiro_vix(bloco_erro)
    sys.exit(0)

# ===================================================================
# GERAR FICHEIRO TEMPORÁRIO PARA O ORQUESTRADOR
# ===================================================================
bloco_texto = (
    f"{cor_alerta} MOTOR 16: REGIME DE VOLATILIDADE VIX ({data_hoje})\n"
    f"📊 VIX Atual: {vix_atual:.2f} (Var Dia: {vix_var_dia:+.2f}%) | Média 20 Dias: {vix_sma20:.2f}{info_vol_eu}\n"
    f"STATUS MACRO: REGIME {regime_nome}\n"
    f"   - Lote Máximo Breakouts (US / Europa): {lote_breakout_pct}%\n"
    f"   - Lote Máximo Trend Carver / Reversão: {lote_carver_pct}%\n"
    f"   - INSTRUÇÃO TÁTICA: {instrucao}\n"
    f"--------------------------------------------------\n"
)

gravar_ficheiro_vix(bloco_texto)

print(f"[SUCESSO] Motor 16 executado com sucesso. Regime: {regime_nome} (VIX: {vix_atual:.2f})")

# ===================================================================
# NOTIFICAÇÃO TELEGRAM (DEBUG OU ALERTA CRÍTICO DE VOLATILIDADE)
# ===================================================================
debug_telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

if debug_telegram_ativado or alerta_critico_macro:
    print("A enviar notificação para o Telegram via função modular...")
    mensagem_debug = (
        f"16 {cor_alerta} *MOTOR 16 (REGIME VIX)*\n\n"
        f"📊 VIX: *{vix_atual:.2f}* ({vix_var_dia:+.2f}%) | SMA20: *{vix_sma20:.2f}*\n"
        f"🌐 Regime: *{regime_nome}*\n"
        f"⚖️ Lote Máx Breakouts: *{lote_breakout_pct}%* | Carver: *{lote_carver_pct}%*"
    )
    enviar_alerta(mensagem_debug)
