# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR 16 (VOLATILITY REGIME & VIX)
# ===================================================================
import os
import sys
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
import warnings
warnings.filterwarnings("ignore")

# Importação da função modular de notificação do Telegram
from F01_notificador_telegram import enviar_alerta

# ===================================================================
# 0. CONFIGURAÇÕES E CREDENCIAIS
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

print("A iniciar Motor 16 - Volatility Regime & VIX Dynamic Targeting...")

configs_dict = {}
if WEBHOOK_URL:
    try:
        resp = requests.get(WEBHOOK_URL, timeout=15)
        if resp.status_code == 200:
            json_data = resp.json()
            if isinstance(json_data, dict):
                configs_dict = json_data.get("configs", {})
    except Exception as e:
        print(f"[AVISO] Não foi possível ler as configurações do Sheets: {e}")

try:
    # Obter histórico do VIX (^VIX) via yfinance
    df_vix = yf.download("^VIX", period="3mo", interval="1d", progress=False)
    if df_vix.empty or len(df_vix) < 20:
        print("[ERRO] Não foi possível obter dados do VIX. A assumir regime Neutro (100%).")
        sys.exit(0)
        
    if isinstance(df_vix.columns, pd.MultiIndex):
        df_vix.columns = df_vix.columns.droplevel(1)
        
    vix_atual = float(df_vix['Close'].iloc[-1])
    vix_anterior = float(df_vix['Close'].iloc[-2])
    vix_var_dia = ((vix_atual - vix_anterior) / vix_anterior) * 100
    
    # Média Móvel de 20 períodos para o VIX
    df_vix['SMA_20'] = df_vix['Close'].rolling(window=20).mean()
    vix_sma20 = float(df_vix['SMA_20'].iloc[-1])
    
    # ===================================================================
    # DETERMINAÇÃO DO REGIME E MULTIPLICADOR DE LOTE
    # ===================================================================
    if vix_atual < 15.0:
        regime_nome = "CALMO / VENTO A FAVOR"
        lote_breakout_pct = 100
        lote_carver_pct = 100
        instrucao = "Ambiente propício a expansão de tendência. Utilizar dimensão total de posição."
        cor_alerta = "🟢"
    elif 15.0 <= vix_atual < 20.0:
        regime_nome = "MODERADO / ALERTA"
        lote_breakout_pct = 75
        lote_carver_pct = 100
        instrucao = "Volatilidade controlada com ligeiro ruído. Lote de Breakout ajustado para 75%."
        cor_alerta = "🟡"
    elif 20.0 <= vix_atual < 25.0:
        regime_nome = "TENSÃO / VENTO CONTRA"
        lote_breakout_pct = 50
        lote_carver_pct = 75
        instrucao = "Elevação de risco sistémico. Exigida redução rigorosa de lote para 50% em Breakouts."
        cor_alerta = "🟠"
    else: # VIX >= 25.0
        regime_nome = "PÂNICO / EXPANSÃO EXTREMA"
        lote_breakout_pct = 0
        lote_carver_pct = 50
        instrucao = "🚨 VIX EM PÂNICO! BLOQUEIO TOTAL de novas entradas em Breakouts. Apenas Mean Reversion permitida a 50%."
        cor_alerta = "🔴"

except Exception as e:
    print(f"[ERRO CRÍTICO] Falha ao calcular Motor 16 (VIX): {e}")
    sys.exit(1)

# ===================================================================
# GERAR FICHEIRO TEMPORÁRIO PARA O ORQUESTRADOR
# ===================================================================
data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M")

bloco_texto = (
    f"{cor_alerta} MOTOR 16: REGIME DE VOLATILIDADE VIX ({data_hoje})\n"
    f"📊 VIX Atual: {vix_atual:.2f} (Var Dia: {vix_var_dia:+.2f}%) | Média 20 Dias: {vix_sma20:.2f}\n"
    f"STATUS MACRO: REGIME {regime_nome}\n"
    f"   - Lote Máximo Breakouts (US / Europa): {lote_breakout_pct}%\n"
    f"   - Lote Máximo Trend Carver / Reversão: {lote_carver_pct}%\n"
    f"   - INSTRUÇÃO TÁTICA: {instrucao}\n"
    f"--------------------------------------------------\n"
)

with open("comboio_vix_temp.txt", "w", encoding="utf-8") as f:
    f.write(bloco_texto)

print(f"[SUCESSO] Motor 16 executado com sucesso. Regime: {regime_nome} (VIX: {vix_atual:.2f})")

# ===================================================================
# NOTIFICAÇÃO TELEGRAM DEBUG (CONTROLADA PELA FLAG DE CONFIGS)
# ===================================================================
debug_telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

if debug_telegram_ativado:
    print("A enviar notificação de Debug para o Telegram via função modular...")
    mensagem_debug = f"16 📈 *(REGIME VIX)*\n\n🔍 [DEBUG] Execução concluída.\nVIX: {vix_atual:.2f} | Regime: {regime_nome}\nRelatório de volatilidade gerado."
    enviar_alerta(mensagem_debug)
