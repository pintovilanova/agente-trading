# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR 18: MOMENTUM BURST & VOLUME SURGE
# ===================================================================================
# Descrição Geral:
# Identifica ativos de alta liquidez a sofrer uma explosão de volume institucional 
# (RVOL >= 2.0) acompanhada de um rompimento direcional de curto prazo (Hit and Run),
# auditando em simultâneo as posições ativas em carteira (ATIVA_M18).
# ===================================================================================

import pandas as pd
import yfinance as yf
import pandas_ta as ta
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo
import sys
import os
import requests
import smtplib
import time
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json
import warnings
warnings.filterwarnings("ignore")

# Importação da função modular de notificação do Telegram
from F01_notificador_telegram import enviar_alerta

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O Motor Momentum Burst vai descansar.")
    # sys.exit(0)

# ===================================================================
# 1. CONFIGURAÇÕES E CREDENCIAIS
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

def limpar_float(val):
    if val is None: return None
    try:
        val_str = str(val).replace(",", ".").strip()
        if val_str == "" or val_str.lower() in ["nan", "n/a", "none"]: return None
        return float(val_str)
    except (ValueError, TypeError):
        return None

# ===================================================================
# 2. FUNÇÕES DE REDE E CONFIGS (LEITURA COMPLETA DO SHEETS)
# ===================================================================
def buscar_dados_completos():
    print("A carregar Watchlist, Posições Ativas e Configs a partir do Google Sheets...")
    if not WEBHOOK_URL: 
        print("[ERRO] WEBHOOK_URL não configurado.")
        return [], {}, {}
    try:
        url_alvo = WEBHOOK_URL if "?" in WEBHOOK_URL else f"{WEBHOOK_URL}?aba=Analise Compra"
        resp = requests.get(url_alvo, timeout=15)
        
        if resp.status_code == 200:
            try:
                dados = resp.json()
            except json.JSONDecodeError:
                print(f"[ERRO] O Webhook não retornou um JSON válido. Resposta: {resp.text[:200]}")
                return [], {}, {}

            if isinstance(dados, dict):
                ativos = dados.get("ativos", [])
                posicoes = dados.get("posicoesAtivas", {})
                configs = dados.get("configs", {})
                return ativos, posicoes, configs
            elif isinstance(dados, list):
                return dados, {}, {}
        return [], {}, {}
    except Exception as e:
        print(f"[ERRO CRÍTICO] Sheets: {e}")
        return [], {}, {}

def enviar_email(conteudo):
    print("\nA enviar email do Motor 18 para o Agente IA...")
    if not EMAIL_USER or not EMAIL_PASS: return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = "⚡ tradingRelatorioIA US - MOTOR 18 MOMENTUM BURST"
    msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
    
    for tentativa in range(3):
        try:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
            server.quit()
            print(f"[SUCESSO] Email enviado na tentativa {tentativa + 1}!")
            break
        except Exception as e:
            if tentativa < 2: time.sleep(5)

# ===================================================================
# 3. CARGA DE DADOS E PARAMETRIZAÇÃO
# ===================================================================
ativos_sheets, posicoes_ativas_dict, configs_dict = buscar_dados_completos()

try:
    capital = float(configs_dict.get("CAPITAL_TOTAL_CONTA", 10400.00))
    vol_anual = float(configs_dict.get("ALVO_VOLATILIDADE_ANUAL", 0.05))
except (ValueError, TypeError):
    capital, vol_anual = 10400.00, 0.05

vol_diaria_usd = (capital * vol_anual) / 16.0
print(f"[CONFIG] Orçamento Diário de Volatilidade: ${vol_diaria_usd:.2f}\n")

# ===================================================================
# 4. AUDITAR POSIÇÕES EM CARTEIRA (ESTADO: ATIVA_M18)
# ===================================================================
bloco_posicoes_ativas = ""
for ticker, info in posicoes_ativas_dict.items():
    status = str(info.get("status", "")).strip().upper()
    if status in ["ATIVA_M18", "ATIVA_SWING"]:
        try:
            df_pos = yf.download(ticker, period="1mo", interval="1d", progress=False)
            if not df_pos.empty:
                if isinstance(df_pos.columns, pd.MultiIndex):
                    df_pos.columns = df_pos.columns.droplevel(1)
                
                stop = limpar_float(info.get("stopAtual")) or limpar_float(info.get("stopLoss")) or 0.0
                alvo_tp = limpar_float(info.get("alvoTp")) or limpar_float(info.get("takeProfit")) or 0.0
                
                try:
                    df_intra = yf.download(ticker, period="2d", interval="1m", prepost=True, progress=False)
                    if isinstance(df_intra.columns, pd.MultiIndex):
                        df_intra.columns = df_intra.columns.droplevel(1)
                    preco_atual = round(float(df_intra['Close'].iloc[-1]), 2)
                    maxima_hoje = round(float(df_intra['High'].max()), 2)
                    minima_hoje = round(float(df_intra['Low'].min()), 2)
                except Exception:
                    preco_atual = round(float(df_pos['Close'].iloc[-1]), 2)
                    maxima_hoje = round(float(df_pos['High'].iloc[-1]), 2)
                    minima_hoje = round(float(df_pos['Low'].iloc[-1]), 2)
                
                entrada = limpar_float(info.get("precoEntrada")) or preco_atual
                qtd = info.get("quantidade", "N/A")
                maxima_efetiva = max(maxima_hoje, preco_atual)
                
                if alvo_tp > 0 and maxima_efetiva >= alvo_tp:
                    acao = f"🎯 ALVO ALCANÇADO (TP em ${alvo_tp})! Recomendado FECHAR POSIÇÃO com Lucro (WIN)."
                elif stop > 0 and minima_hoje <= stop:
                    acao = f"🚨 STOP LOSS ATINGIDO (${stop})! Recomendado LIQUIDAR POSIÇÃO (LOSS)."
                else:
                    acao = f"⏳ MANTER POSIÇÃO (Hit and Run). Alvo TP: ${alvo_tp} | Stop Fixo/Trail: ${stop}."
                
                bloco_posicoes_ativas += (
                    f"📌 [POSIÇÃO ATIVA - {status}] {ticker} | Qtd: {qtd} | Entrada: ${entrada} | "
                    f"Preço Atual: ${preco_atual} | Alvo: ${alvo_tp} | Stop: ${stop} | "
                    f"AÇÃO: {acao}\n"
                )
        except Exception as e:
            print(f"[ERRO] Falha ao auditar posição ativa {ticker}: {e}")

# ===================================================================
# 5. MOTOR MATEMÁTICO: MOMENTUM BURST & RVOL (NOVOS SINAIS)
# ===================================================================
def analisar_momentum_burst(ativo_info):
    try:
        ticker = str(ativo_info.get("ticker", "")).strip().upper()
        nome_empresa = ativo_info.get("nome", "N/A")
        setor = str(ativo_info.get("setor", "Desconhecido")).strip()

        if not ticker or ticker == "#N/A" or ticker == "NONE": return None
        if ticker in posicoes_ativas_dict: return None # Ignora se já estiver em carteira
        if ticker == "BRK-A": ticker = "BRK-B"

        time.sleep(random.uniform(0.8, 1.8))

        max_52s = None
        alerta_earnings = "OK"
        try:
            ticker_obj = yf.Ticker(ticker)
            info_dados = ticker_obj.info
            if setor in ["Desconhecido", "N/A", "", "NONE"]:
                setor = info_dados.get('sector', setor)
            max_52s = info_dados.get('fiftyTwoWeekHigh', None)

            calendario = ticker_obj.calendar
            if isinstance(calendario, dict) and 'Earnings Date' in calendario:
                proxima_data = calendario['Earnings Date'][0]
                if hasattr(proxima_data, 'date'): proxima_data = proxima_data.date()
                dias_restantes = (proxima_data - datetime.now(ZoneInfo("Europe/Lisbon")).date()).days
                if 0 <= dias_restantes <= 3:
                    alerta_earnings = f"PERIGO (em {dias_restantes} dias)"
        except:
            pass

        df = pd.DataFrame()
        for _ in range(3):
            try:
                df = yf.download(ticker, period="1y", interval="1d", progress=False, timeout=15)
                if not df.empty and len(df) >= 60:
                    break
            except Exception:
                time.sleep(2)

        if df.empty or len(df) < 60: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
        df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])

        preco = float(df['Close'].iloc[-1])
        if preco < 5.00: return None

        df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['Vol_SMA_20'] = df['Volume'].rolling(window=20).mean()
        df.ta.atr(length=14, append=True)

        col_atr = [c for c in df.columns if str(c).startswith('ATRr_') or str(c).startswith('ATR_')][0]
        df = df.dropna(subset=['EMA_20', 'Vol_SMA_20', col_atr])
        if df.empty: return None

        ultimo = df.iloc[-1]
        vol_atual = float(ultimo['Volume'])
        vol_sma20 = float(ultimo['Vol_SMA_20'])
        atr = float(ultimo[col_atr])
        ema20 = float(ultimo['EMA_20'])

        rvol = vol_atual / vol_sma20 if vol_sma20 > 0 else 0.0
        max_5d = float(df['High'].iloc[-6:-1].max())
        minimo_hoje = float(ultimo['Low'])
        maximo_hoje = float(ultimo['High'])

        cond_rvol = rvol >= 2.0
        cond_rompimento = maximo_hoje >= max_5d
        cond_tendencia = preco > ema20

        if cond_rvol and cond_rompimento and cond_tendencia:
            estado = "MOMENTUM BURST - Explosão de Volume e Rompimento"
            
            entrada_gatilho = round(maximo_hoje * 1.002, 2)
            stop_loss = round(min(minimo_hoje * 0.99, entrada_gatilho - (atr * 1.5)), 2)
            
            risco = entrada_gatilho - stop_loss
            alvo_tp = round(entrada_gatilho + (risco * 2.0), 2)

            if max_52s and max_52s > 0 and alvo_tp > max_52s:
                alvo_tp = round(max_52s, 2)

            if alvo_tp <= entrada_gatilho:
                alvo_tp = round(entrada_gatilho + (risco * 1.5), 2)

            qtd_calc = round(vol_diaria_usd / risco, 2) if risco > 0 else 0.0
            val_calc = entrada_gatilho * qtd_calc
            valor_investir = f"~{val_calc:.2f} USD"

            def limpa(v):
                try: return round(float(v), 2)
                except: return "N/A"

            linha_comboio = (
                f"{ticker},Nome: {nome_empresa},Setor: {setor},Preço: {limpa(preco)},"
                f"RVOL: {limpa(rvol)}x (🚀 EXPLOSÃO DE VOLUME),"
                f"Gatilho Compra (Buy Stop): {limpa(entrada_gatilho)},"
                f"Stop Loss: {limpa(stop_loss)},Alvo TP: {limpa(alvo_tp)},"
                f"Estado: {estado},Qtd: {qtd_calc},ValorInvestir: {valor_investir},Earnings: {alerta_earnings},"
                f"Data: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
            )

            return {"ticker": ticker, "comboio_str": linha_comboio}

        return None
    except Exception as e:
        print(f"[ERRO] Falha ao processar ativo {ativo_info.get('ticker')}: {e}")
        return None

# ===================================================================
# 6. EXECUÇÃO PRINCIPAL E RELATÓRIO
# ===================================================================
def executar_motor():
    if not ativos_sheets: sys.exit(0)

    ativos_acionados = []
    total_analisados = 0
    
    for ativo_info in ativos_sheets:
        ticker = ativo_info.get("ticker")
        if not ticker or ticker == "#N/A": continue
        
        total_analisados += 1
        res = analisar_momentum_burst(ativo_info)
        if res: ativos_acionados.append(res)

    prompt_ia = """MODO ESTRATÉGICO: MOTOR 18 - MOMENTUM BURST & VOLUME SURGE
O teu mandato é auditar oportunidades de curto prazo (Hit and Run) focadas em explosões institucionais de volume."""

    bloco = f"⚡ RELATÓRIO MOTOR 18 - MOMENTUM BURST 🚀\n\n{prompt_ia}\n\n--------------------------------------------------\n"

    if bloco_posicoes_ativas:
        bloco += "GESTÃO DE POSIÇÕES ATIVAS (ATIVA_M18):\n\n"
        bloco += bloco_posicoes_ativas
        bloco += "--------------------------------------------------\n\n"

    if not ativos_acionados:
        bloco += "[SEM NOVOS SINAIS] - Nenhum novo ativo apresenta explosão de volume e momento hoje.\n"
    else:
        bloco += "NOVOS ALVOS DE MOMENTUM BURST:\n\n"
        for item in ativos_acionados:
            bloco += item["comboio_str"] + "\n"

    with open("comboio_momentumburst_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco)

    enviar_email(bloco)

    # ===================================================================
    # 7. NOTIFICAÇÃO TELEGRAM DEBUG (CONTROLADA PELA FLAG DE CONFIGS)
    # ===================================================================
    debug_telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

    if debug_telegram_ativado:
        print("A enviar notificação de Debug para o Telegram via função modular...")
        total_acionados = len(ativos_acionados)
        mensagem_debug = (
            f"18 ⚡ *MOTOR 18 (MOMENTUM BURST)*\n\n"
            f"🔍 [DEBUG] Execução concluída com sucesso.\n"
            f"📊 Ativos analisados: *{total_analisados}* | Acionados: *{total_acionados}*\n"
            f"✉️ Relatório de momentum burst gerado e enviado por e-mail."
        )
        enviar_alerta(mensagem_debug)

if __name__ == "__main__":
    executar_motor()
