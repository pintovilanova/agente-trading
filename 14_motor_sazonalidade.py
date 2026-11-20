# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR 14: SAZONALIDADE INSTITUCIONAL (CALENDAR EDGE)
# ===================================================================================
# Descrição Geral:
# Analisa 5 anos de histórico diário para identificar anomalias estatísticas de calendário
# (Calendar Edge) nos líderes da Watchlist (RS Score >= 65 & Preço > SMA 200):
# 1. Edge do Dia da Semana Atual (Retorno Médio + Win Rate histórico)
# 2. Efeito Turn-of-the-Month (Dias <= 4 ou >= 28 — fluxos automáticos de pensões/fundos)
# 3. Sazonalidade Mensal (Desempenho histórico do ativo no mês corrente nos últimos 5 anos)
# Funciona como camada de confluência temporal para o Orquestrador.
# ===================================================================================

import pandas as pd
import yfinance as yf
import numpy as np
import os
import sys
import requests
import time
import random
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
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
hoje_lisboa = datetime.now(ZoneInfo("Europe/Lisbon"))
dia_semana = hoje_lisboa.weekday()  # 0 = Segunda, ..., 4 = Sexta
if dia_semana >= 5:
    print("[INFO] Fim de semana detetado. O Motor 14 (Sazonalidade) vai descansar.")
    # sys.exit(0)

# ===================================================================
# 1. CONFIGURAÇÕES E PARÂMETROS
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

DIAS_SEMANA_PT = {
    0: "Segunda-feira",
    1: "Terça-feira",
    2: "Quarta-feira",
    3: "Quinta-feira",
    4: "Sexta-feira",
    5: "Sábado",
    6: "Domingo"
}

MESES_PT = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
}

def limpar_float(val):
    if val is None:
        return None
    try:
        val_str = str(val).replace(",", ".").strip()
        if val_str == "" or val_str.lower() in ["nan", "n/a", "none"]:
            return None
        return float(val_str)
    except (ValueError, TypeError):
        return None

def gravar_ficheiro_sazonalidade(conteudo):
    with open("comboio_sazonalidade_temp.txt", "w", encoding="utf-8") as f:
        f.write(conteudo)

def get_yf_history_safe(ticker, period="5y"):
    for _ in range(3):
        try:
            time.sleep(random.uniform(0.35, 0.85))
            df = yf.download(ticker, period=period, interval="1d", progress=False, session=session, timeout=15)
            if not df.empty and len(df) >= 200:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                df = df.dropna(subset=['Close'])
                if len(df) >= 200:
                    return df
        except Exception:
            time.sleep(1.5)
    return pd.DataFrame()

# ===================================================================
# 2. CARREGAMENTO DA WATCHLIST E CONFIGS (SHEETS)
# ===================================================================
print("A iniciar Motor 14 — Sazonalidade Institucional (Calendar Edge)...")

ativos = []
configs_dict = {}
if WEBHOOK_URL:
    try:
        url_alvo = WEBHOOK_URL if "?" in WEBHOOK_URL else f"{WEBHOOK_URL}?aba=Analise Compra"
        resp = requests.get(url_alvo, timeout=20)
        if resp.status_code == 200:
            json_data = resp.json()
            if isinstance(json_data, dict):
                ativos = json_data.get("ativos", [])
                configs_dict = json_data.get("configs", {})
            elif isinstance(json_data, list):
                ativos = json_data
    except Exception as e:
        print(f"[ERRO] Falha ao ler Watchlist do Sheets: {e}")

data_hoje_str = hoje_lisboa.strftime("%d/%m/%Y %H:%M:%S")
dia_mes = hoje_lisboa.day
mes_atual = hoje_lisboa.month
nome_dia_pt = DIAS_SEMANA_PT.get(dia_semana, "Dia Útil")
nome_mes_pt = MESES_PT.get(mes_atual, str(mes_atual))

# Janelas institucionais de calendário
eh_turn_of_month = (dia_mes <= 4) or (dia_mes >= 28)
eh_meio_semana = dia_semana in [1, 2]  # Terça ou Quarta
eh_pre_fim_semana = (dia_semana == 4)  # Sexta-feira (realização de lucros / fecho semanal)

if not ativos:
    msg_vazio = (
        f"📅 MOTOR 14 - SAZONALIDADE INSTITUCIONAL ({data_hoje_str})\n"
        f"=================================================================\n"
        f"⚠️ Nenhum ativo encontrado na Watchlist para análise sazonal.\n"
    )
    gravar_ficheiro_sazonalidade(msg_vazio)
    print("[AVISO] Nenhum ativo encontrado na Watchlist para análise sazonal.")
    sys.exit(0)

# ===================================================================
# 3. ANÁLISE DE JANELAS TEMPORAIS E ESTATÍSTICA HISTÓRICA (5 ANOS)
# ===================================================================
print(
    f"[CONTEXTO] {hoje_lisboa.strftime('%d/%m/%Y')} ({nome_dia_pt} | {nome_mes_pt}) | "
    f"Turn-of-the-Month: {eh_turn_of_month} | Meio de Semana: {eh_meio_semana}"
)

sinais_sazonalidade = []
total_analisados = 0

for ativo_info in ativos:
    ticker = str(ativo_info.get("ticker", "")).strip().upper().replace(".", "-")
    if not ticker or ticker == "#N/A" or ticker == "NONE":
        continue
    if ticker == "BRK-A":
        ticker = "BRK-B"

    # Pré-filtro de qualidade: analisa apenas líderes da watchlist (RS >= 65)
    rs_val = limpar_float(ativo_info.get("rs_score"))
    if rs_val is not None and rs_val < 65.0:
        continue

    nome_empresa = ativo_info.get("nome") or ativo_info.get("nomeEmpresa") or "N/A"
    setor = str(ativo_info.get("setor") or ativo_info.get("setorAtivo") or "Desconhecido").strip()

    total_analisados += 1
    df = get_yf_history_safe(ticker, period="5y")
    if df.empty or len(df) < 200:
        continue

    # Filtro estrutural: apenas ativos em tendência primária de alta (Close > SMA 200)
    close_atual = float(df['Close'].iloc[-1])
    sma_200 = float(df['Close'].rolling(200).mean().iloc[-1])
    if close_atual < sma_200:
        continue

    df['DayOfWeek'] = df.index.dayofweek
    df['DayOfMonth'] = df.index.day
    df['Month'] = df.index.month
    df['Return'] = df['Close'].pct_change()
    df = df.dropna(subset=['Return'])

    # 1. Estatística específica para o Dia da Semana atual (ex: todas as Sextas dos últimos 5 anos)
    df_dia_atual = df[df['DayOfWeek'] == dia_semana]
    ret_dia_atual = float(df_dia_atual['Return'].mean() * 100) if not df_dia_atual.empty else 0.0
    wr_dia_atual = float((df_dia_atual['Return'] > 0).mean() * 100) if not df_dia_atual.empty else 50.0

    # 2. Estatística Turn-of-the-Month (dias <= 4 ou >= 28)
    df_tom = df[(df['DayOfMonth'] <= 4) | (df['DayOfMonth'] >= 28)]
    ret_tom = float(df_tom['Return'].mean() * 100) if not df_tom.empty else 0.0
    wr_tom = float((df_tom['Return'] > 0).mean() * 100) if not df_tom.empty else 50.0

    # 3. Estatística do Mês Atual (retorno médio anualizado no mês corrente nos últimos 5 anos)
    df_mes_atual = df[df['Month'] == mes_atual]
    ret_medio_diario_mes = float(df_mes_atual['Return'].mean() * 100) if not df_mes_atual.empty else 0.0
    wr_mes_atual = float((df_mes_atual['Return'] > 0).mean() * 100) if not df_mes_atual.empty else 50.0

    # Cálculo do Score Sazonal Institucional (0 a 100)
    score_sazonal = 40.0
    fatores_positivos = []

    # Pilar A: Dia da semana com edge estatístico real
    if ret_dia_atual >= 0.12 and wr_dia_atual >= 55.0:
        score_sazonal += 25.0
        fatores_positivos.append(f"{nome_dia_pt} Forte (+{ret_dia_atual:.2f}%/dia | WR {wr_dia_atual:.0f}%)")
    elif ret_dia_atual > 0.04 and wr_dia_atual >= 52.0:
        score_sazonal += 15.0
        fatores_positivos.append(f"{nome_dia_pt} Positivo (+{ret_dia_atual:.2f}%/dia | WR {wr_dia_atual:.0f}%)")

    # Pilar B: Janela Turn-of-the-Month ativa e confirmada historicamente no ativo
    if eh_turn_of_month and ret_tom >= 0.10 and wr_tom >= 54.0:
        score_sazonal += 20.0
        fatores_positivos.append(f"Turn-of-Month (+{ret_tom:.2f}%/dia | WR {wr_tom:.0f}%)")

    # Pilar C: Mês historicamente favorável para o ativo
    if ret_medio_diario_mes >= 0.08 and wr_mes_atual >= 53.0:
        score_sazonal += 15.0
        fatores_positivos.append(f"Sazonalidade {nome_mes_pt} (+{ret_medio_diario_mes:.2f}%/dia | WR {wr_mes_atual:.0f}%)")

    if score_sazonal >= 75.0 and len(fatores_positivos) >= 2:
        sinais_sazonalidade.append({
            "ticker": ticker,
            "nome": nome_empresa,
            "setor": setor,
            "rs_score": rs_val if rs_val is not None else "N/A",
            "score_sazonal": round(score_sazonal, 1),
            "ret_dia": ret_dia_atual,
            "wr_dia": wr_dia_atual,
            "ret_tom": ret_tom,
            "wr_tom": wr_tom,
            "ret_mes": ret_medio_diario_mes,
            "fatores": " + ".join(fatores_positivos)
        })

# Ordena pelos melhores scores e maior Win Rate no dia da semana atual
sinais_sazonalidade = sorted(sinais_sazonalidade, key=lambda x: (x['score_sazonal'], x['wr_dia']), reverse=True)

# ===================================================================
# 4. GERAÇÃO DE RELATÓRIO PARA A PIPELINE (ORQUESTRADOR)
# ===================================================================
relatorio_sazonal = f"📅 MOTOR 14 - SAZONALIDADE INSTITUCIONAL / CALENDAR EDGE ({data_hoje_str})\n"
relatorio_sazonal += "=" * 75 + "\n"
relatorio_sazonal += (
    f"🗓️ Contexto Temporal: {nome_dia_pt} (Dia {dia_mes} de {nome_mes_pt}) | "
    f"Turn-of-the-Month: {'SIM 🟢' if eh_turn_of_month else 'NÃO'} | "
    f"Janela Meio de Semana: {'SIM' if eh_meio_semana else 'NÃO'}\n"
)
if eh_pre_fim_semana:
    relatorio_sazonal += "⚠️ Nota de Sexta-feira: Evitar perseguir breakouts tardios sem volume; priorizar apenas ativos com edge histórico comprovado à Sexta.\n"
relatorio_sazonal += "=" * 75 + "\n\n"

if sinais_sazonalidade:
    top_sinais = sinais_sazonalidade[:10]
    relatorio_sazonal += f"🌟 ATIVOS COM ALINHAMENTO SAZONAL FAVORÁVEL (TOP {len(top_sinais)} de {len(sinais_sazonalidade)}):\n\n"
    for item in top_sinais:
        relatorio_sazonal += f"• {item['ticker']} ({item['nome']}) | Setor: {item['setor']} | RS: {item['rs_score']}\n"
        relatorio_sazonal += f"    - Score Sazonal (5Y): {item['score_sazonal']:.0f}/100 | Confluência: {item['fatores']}\n"
        relatorio_sazonal += f"    - Estatística {nome_dia_pt}: Retorno Médio {item['ret_dia']:+.3f}% | Win Rate {item['wr_dia']:.1f}%\n\n"
else:
    relatorio_sazonal += "⚖️ Nenhuma janela sazonal de alta convicção (Score >= 75 com duplo fator histórico) detetada hoje.\n"

gravar_ficheiro_sazonalidade(relatorio_sazonal)

print(relatorio_sazonal)
print("[SUCESSO] Auditoria de Sazonalidade concluída e ficheiro temporário gerado.")

# ===================================================================
# 5. NOTIFICAÇÃO TELEGRAM DEBUG (CONTROLADA PELA FLAG DE CONFIGS)
# ===================================================================
debug_telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

if debug_telegram_ativado:
    print("A enviar notificação de Debug para o Telegram via função modular...")
    status_msg = f"🌟 {len(sinais_sazonalidade)} Ativos com Calendar Edge (Top: {sinais_sazonalidade[0]['ticker']})" if sinais_sazonalidade else "⚖️ Sem Janelas Sazonais Ativas"
    mensagem_debug = (
        f"14 📅 *MOTOR 14 (SAZONALIDADE INSTITUCIONAL)*\n\n"
        f"🔍 Execução concluída ({nome_dia_pt} | {nome_mes_pt}).\n"
        f"📊 Líderes auditados: *{total_analisados}* | Alinhados: *{len(sinais_sazonalidade)}*\n"
        f"Estado: {status_msg}"
    )
    enviar_alerta(mensagem_debug)
