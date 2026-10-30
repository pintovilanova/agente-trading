# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR DE SAZONALIDADE (CALENDAR EDGE)
# ===================================================================================
import pandas as pd
import yfinance as yf
import os
import requests
import time
import random
from datetime import datetime
from zoneinfo import ZoneInfo
import warnings
warnings.filterwarnings("ignore")

# Importação da função modular de notificação do Telegram
from F01_notificador_telegram import enviar_alerta

# ===================================================================
# 1. CONFIGURAÇÕES E PARÂMETROS
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

def get_yf_history_safe(ticker, period="1y"):
    for _ in range(3):
        try:
            time.sleep(random.uniform(0.5, 1.2))
            df = yf.download(ticker, period=period, interval="1d", progress=False, timeout=15)
            if not df.empty and len(df) >= 50:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                return df.dropna(subset=['Close'])
        except Exception:
            time.sleep(2.0)
    return pd.DataFrame()

# ===================================================================
# 2. CARREGAMENTO DA WATCHLIST E CONFIGS (SHEETS)
# ===================================================================
print("A iniciar Motor de Sazonalidade Institucional...")

ativos = []
configs_dict = {}
if WEBHOOK_URL:
    try:
        url_alvo = WEBHOOK_URL if "?" in WEBHOOK_URL else f"{WEBHOOK_URL}?aba=Analise Compra"
        resp = requests.get(url_alvo, timeout=15)
        if resp.status_code == 200:
            json_data = resp.json()
            if isinstance(json_data, dict):
                ativos = json_data.get("ativos", [])
                configs_dict = json_data.get("configs", {})
            elif isinstance(json_data, list):
                ativos = json_data
    except Exception as e:
        print(f"[ERRO] Falha ao ler Watchlist do Sheets: {e}")

if not ativos:
    print("[AVISO] Nenhum ativo encontrado na Watchlist para análise sazonal.")
    exit(0)

# ===================================================================
# 3. ANÁLISE DE JANELAS TEMPORAIS E ESTATÍSTICA HISTÓRICA
# ===================================================================
hoje_lisboa = datetime.now(ZoneInfo("Europe/Lisbon"))
dia_semana = hoje_lisboa.weekday() # 0 = Segunda, 1 = Terça, ..., 4 = Sexta
dia_mes = hoje_lisboa.day

# Definição do Contexto Temporal Atual
eh_turn_of_month = (dia_mes <= 4) or (dia_mes >= 28)
eh_meio_semana = dia_semana in [1, 2] # Terça ou Quarta

print(f"[CONTEXTO] Data: {hoje_lisboa.strftime('%d/%m/%Y')} | Turn-of-the-Month: {eh_turn_of_month} | Meio de Semana (Ter/Qua): {eh_meio_semana}")

sinais_sazonalidade = []

for ativo_info in ativos:
    ticker = str(ativo_info.get("ticker", "")).strip().upper()
    nome_empresa = ativo_info.get("nome", "N/A")
    setor = str(ativo_info.get("setor", "Desconhecido")).strip()
    rs_score = ativo_info.get("rs_score", "N/A")
    
    if not ticker or ticker == "#N/A": continue
    if ticker == "BRK-A": ticker = "BRK-B"
    
    df = get_yf_history_safe(ticker, period="1y")
    if df.empty: continue
    
    df['DayOfWeek'] = df.index.dayofweek
    df['DayOfMonth'] = df.index.day
    df['Return'] = df['Close'].pct_change()
    
    retorno_meio_semana = df[df['DayOfWeek'].isin([1, 2])]['Return'].mean() * 100
    
    score_sazonal = 50.0
    if eh_turn_of_month: score_sazonal += 25.0
    if eh_meio_semana and retorno_meio_semana > 0: score_sazonal += 25.0
    
    if score_sazonal >= 75.0:
        sinais_sazonalidade.append({
            "ticker": ticker,
            "nome": nome_empresa,
            "setor": setor,
            "rs_score": rs_score,
            "score_sazonal": score_sazonal,
            "retorno_historico_meio_semana": retorno_meio_semana
        })

# ===================================================================
# 4. GERAÇÃO DE RELATÓRIO PARA A PIPELINE
# ===================================================================
data_hoje_str = hoje_lisboa.strftime("%d/%m/%Y %H:%M:%S")
relatorio_sazonal = f"📅 MOTOR 14 - SAZONALIDADE INSTITUCIONAL ({data_hoje_str})\n"
relatorio_sazonal += "=" * 65 + "\n\n"
relatorio_sazonal += f"Contexto Temporal: Turn-of-the-Month: {eh_turn_of_month} | Janela de Meio de Semana: {eh_meio_semana}\n\n"

if sinais_sazonalidade:
    relatorio_sazonal += "🌟 ATIVOS COM ALINHAMENTO SAZONAL FAVORÁVEL:\n\n"
    for item in sinais_sazonalidade:
        relatorio_sazonal += f"🔹 {item['ticker']} ({item['nome']}) | Setor: {item['setor']}\n"
        relatorio_sazonal += f"    - Score Sazonal: {item['score_sazonal']}/100\n"
        relatorio_sazonal += f"    - Viés Histórico Meio de Semana: {item['retorno_historico_meio_semana']:.3f}%\n\n"
else:
    relatorio_sazonal += "⚖️ Nenhuma janela sazonal de alta convicção detetada na Watchlist para o dia de hoje.\n"

with open("comboio_sazonalidade_temp.txt", "w", encoding="utf-8") as f:
    f.write(relatorio_sazonal)

print("[SUCESSO] Auditoria de Sazonalidade concluída e ficheiro temporário gerado.")

# ===================================================================
# 5. NOTIFICAÇÃO TELEGRAM DEBUG (CONTROLADA PELA FLAG DE CONFIGS)
# ===================================================================
debug_telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

if debug_telegram_ativado:
    print("A enviar notificação de Debug para o Telegram via função modular...")
    status_msg = f"🌟 {len(sinais_sazonalidade)} Ativos com Sazonalidade Favorável" if sinais_sazonalidade else "⚖️ Sem Janelas Sazonais Ativas"
    mensagem_debug = f"📅 *MOTOR 14 (SAZONALIDADE INSTITUCIONAL)*\n\n🔍 [DEBUG] Execução concluída.\nEstado: {status_msg}\nRelatório temporal gerado."
    enviar_alerta(mensagem_debug)
