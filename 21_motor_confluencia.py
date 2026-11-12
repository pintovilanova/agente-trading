# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR 21: CONFLUÊNCIA SUPREMA
# ===================================================================================
# Descrição Geral:
# O modelo "Sniper". Exige confluência absoluta:
# 1. Filtro de Mercado (SPY > EMA 20 diária)
# 2. Força Relativa de Elite (RS Score >= 75)
# 3. Pullback à EMA 20 (Motor 20)
# 4. Squeeze de Volatilidade (Motor 19)
# 5. Entrada Institucional Silenciosa (RVOL >= 1.5) (Motor 18)
# Risco/Retorno fixado agressivamente em 3:1.
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

# ===================================================================
# BYPASS SESSÃO YAHOO FINANCE (PARA GITHUB ACTIONS)
# ===================================================================
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

from F01_notificador_telegram import enviar_alerta

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O Motor Confluência vai descansar.")
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
# 2. FILTRO GERAL DE MERCADO (S&P 500)
# ===================================================================
def mercado_em_alta():
    try:
        df_spy = yf.download("SPY", period="3mo", interval="1d", progress=False, session=session)
        if df_spy.empty: return True # Em caso de falha, permite avançar assumindo risco
        if isinstance(df_spy.columns, pd.MultiIndex): df_spy.columns = df_spy.columns.droplevel(1)
        
        df_spy['EMA_20'] = df_spy['Close'].ewm(span=20, adjust=False).mean()
        preco_spy = float(df_spy['Close'].iloc[-1])
        ema_spy = float(df_spy['EMA_20'].iloc[-1])
        
        return preco_spy > ema_spy
    except Exception as e:
        print(f"[AVISO] Falha ao verificar filtro SPY: {e}")
        return True

# ===================================================================
# 3. FUNÇÕES DE REDE E CARGA DE DADOS
# ===================================================================
def buscar_dados_completos():
    print("A carregar Watchlist, Posições Ativas e Configs a partir do Google Sheets...")
    if not WEBHOOK_URL: return [], {}, {}
    try:
        url_alvo = WEBHOOK_URL if "?" in WEBHOOK_URL else f"{WEBHOOK_URL}?aba=Analise Compra"
        resp = requests.get(url_alvo, timeout=15)
        if resp.status_code == 200:
            dados = resp.json()
            if isinstance(dados, dict):
                return dados.get("ativos", []), dados.get("posicoesAtivas", {}) or dados.get("posicoes", {}), dados.get("configs", {})
        return [], {}, {}
    except Exception as e:
        print(f"[ERRO CRÍTICO] Sheets: {e}")
        return [], {}, {}

def enviar_email(conteudo):
    print("\nA enviar relatório detalhado do Motor 21 por e-mail...")
    if not EMAIL_USER or not EMAIL_PASS: return False
    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = f"⚡ tradingRelatorioIA US - MOTOR 21 CONFLUÊNCIA SUPREMA ({datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')})"
    msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
    
    for tentativa in range(3):
        try:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
            server.quit()
            return True
        except Exception:
            if tentativa < 2: time.sleep(5)
    return False

ativos_sheets, posicoes_ativas_dict, configs_dict = buscar_dados_completos()

try:
    capital = float(configs_dict.get("CAPITAL_TOTAL_CONTA", 10400.00))
    pct_risco = limpar_float(configs_dict.get("RISCO_SWING_PCT")) or 0.01
except (ValueError, TypeError):
    capital, pct_risco = 10400.00, 0.01

vol_diaria_usd = capital * pct_risco

# ===================================================================
# 3B. AUDITAR POSIÇÕES EM CARTEIRA (CORRIGIDO: PREÇO ATUAL VS STOP)
# ===================================================================
bloco_posicoes_ativas = ""
for chave_pos, info in posicoes_ativas_dict.items():
    if not isinstance(info, dict): continue
    status = str(info.get("status", "")).strip().upper()
    
    if status == "ATIVA_M21":
        try:
            ticker = "AI" if chave_pos.lower() in ["c3.ai", "c3"] else chave_pos.strip().upper()
            
            df_pos = yf.download(ticker, period="1mo", interval="1d", progress=False, session=session)
            if not df_pos.empty:
                if isinstance(df_pos.columns, pd.MultiIndex):
                    df_pos.columns = df_pos.columns.droplevel(1)
                
                stop = limpar_float(info.get("stopAtual")) or limpar_float(info.get("stopLoss")) or 0.0
                alvo_tp = limpar_float(info.get("alvoTp")) or limpar_float(info.get("takeProfit")) or 0.0
                
                try:
                    df_intra = yf.download(ticker, period="2d", interval="1m", prepost=True, progress=False, session=session)
                    if isinstance(df_intra.columns, pd.MultiIndex):
                        df_intra.columns = df_intra.columns.droplevel(1)
                    preco_atual = round(float(df_intra['Close'].iloc[-1]), 2)
                    maxima_hoje = round(float(df_intra['High'].max()), 2)
                except Exception:
                    preco_atual = round(float(df_pos['Close'].iloc[-1]), 2)
                    maxima_hoje = round(float(df_pos['High'].iloc[-1]), 2)
                
                entrada = limpar_float(info.get("precoEntrada")) or preco_atual
                qtd = info.get("quantidade", "N/A")
                maxima_efetiva = max(maxima_hoje, preco_atual)
                
                # ATUALIZAÇÃO: Cálculo automático de TP 3R e Trailing Stop Break-Even
                risco_inicial = entrada - stop if entrada > stop else 0.0
                
                # Motor 21 é Sniper, alvo padrão é 3R
                if alvo_tp <= 0 and risco_inicial > 0:
                    alvo_tp = round(entrada + (risco_inicial * 3.0), 2)
                
                # Se o preço efetivo avançou mais de 1R (no motor 21 exige-se mais margem para não ser stopado à toa no ruído), 
                # recomenda subir o stop para Break-Even (+0.05% para comissões)
                sugestao_stop = stop
                if risco_inicial > 0 and maxima_efetiva >= (entrada + (risco_inicial * 1.0)):
                    be_calculado = round(entrada * 1.0005, 2)
                    if be_calculado > stop:
                        sugestao_stop = be_calculado
                
                if alvo_tp > 0 and maxima_efetiva >= alvo_tp:
                    acao = f"🎯 ALVO ALCANÇADO (TP em ${alvo_tp})! Recomendado FECHAR POSIÇÃO com Lucro (WIN)."
                elif stop > 0 and preco_atual <= stop:
                    acao = f"🚨 STOP LOSS ATINGIDO (${stop})! Recomendado LIQUIDAR POSIÇÃO (LOSS)."
                elif sugestao_stop > stop:
                    acao = f"🛡️ PROTEGER POSIÇÃO. +1R Atingido! Sobe o Stop para Break-Even: ${sugestao_stop} | Alvo TP: ${alvo_tp}."
                else:
                    acao = f"⏳ MANTER POSIÇÃO (Confluência Suprema). Alvo TP: ${alvo_tp} | Stop: ${stop}."
                
                bloco_posicoes_ativas += (
                    f"📌 [{status}] {ticker} ({chave_pos}) | Qtd: {qtd} | Entrada: ${entrada} | "
                    f"Atual: ${preco_atual} | {acao}\n"
                )
        except Exception as e:
            print(f"[ERRO] Falha ao auditar posição ativa {chave_pos}: {e}")

# ===================================================================
# 4. MOTOR MATEMÁTICO: A CONFLUÊNCIA DOS 3 PILARES
# ===================================================================
def analisar_confluencia_suprema(ativo_info):
    try:
        # FILTRO 1: FORÇA RELATIVA DE ELITE (RS SCORE >= 75)
        rs_score_raw = ativo_info.get("rs_score", 0)
        try: rs_score = float(str(rs_score_raw).replace(",", ".").strip())
        except: rs_score = 0.0

        if rs_score < 75.0: return None

        ticker = str(ativo_info.get("ticker", "")).strip().upper()
        if not ticker or ticker == "#N/A": return None
        if ticker in posicoes_ativas_dict: return None
        if ticker == "BRK-A": ticker = "BRK-B"

        df = pd.DataFrame()
        for _ in range(3):
            try:
                df = yf.download(ticker, period="6mo", interval="1d", progress=False, timeout=15, session=session)
                if not df.empty and len(df) >= 50: break
            except: time.sleep(2)

        if df.empty or len(df) < 50: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
        df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])

        preco = float(df['Close'].iloc[-1])
        if preco < 5.00: return None

        # INDICADORES TÉCNICOS
        df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['Vol_SMA_20'] = df['Volume'].rolling(window=20).mean()
        
        # Bollinger Bands
        df['STD_20'] = df['Close'].rolling(window=20).std()
        df['BB_Upper'] = df['EMA_20'] + (df['STD_20'] * 2.0)
        df['BB_Lower'] = df['EMA_20'] - (df['STD_20'] * 2.0)
        
        # Keltner Channels e ATR
        df.ta.atr(length=20, mamode="rma", append=True)
        col_atr = [c for c in df.columns if str(c).startswith('ATRr_') or str(c).startswith('ATR_')][0]
        df['KC_Upper'] = df['EMA_20'] + (df[col_atr] * 1.5)
        df['KC_Lower'] = df['EMA_20'] - (df[col_atr] * 1.5)

        df = df.dropna(subset=['EMA_20', 'SMA_50', 'BB_Upper', 'KC_Upper', col_atr])
        if df.empty: return None

        ultimo = df.iloc[-1]
        ema20 = float(ultimo['EMA_20'])
        sma50 = float(ultimo['SMA_50'])
        bb_upper, bb_lower = float(ultimo['BB_Upper']), float(ultimo['BB_Lower'])
        kc_upper, kc_lower = float(ultimo['KC_Upper']), float(ultimo['KC_Lower'])
        atr = float(ultimo[col_atr])
        vol_atual = float(ultimo['Volume'])
        vol_sma20 = float(ultimo['Vol_SMA_20'])
        
        minimo_hoje = float(ultimo['Low'])
        fecho_hoje = float(ultimo['Close'])
        maximo_hoje = float(ultimo['High'])

        # LÓGICA DE CONFLUÊNCIA ABSOLUTA:
        # A. Tendência (Motor 20)
        tendencia_alta = ema20 > sma50
        toque_ema20 = (minimo_hoje <= ema20) and (fecho_hoje >= ema20)
        
        # B. Compressão (Motor 19)
        em_squeeze = (bb_upper <= kc_upper) and (bb_lower >= kc_lower)
        
        # C. Acumulação Institucional (Motor 18 - RVOL >= 1.5 para apanhar o momento)
        rvol = vol_atual / vol_sma20 if vol_sma20 > 0 else 0.0
        volume_anomalo = rvol >= 1.5

        if tendencia_alta and toque_ema20 and em_squeeze and volume_anomalo:
            entrada_gatilho = round(maximo_hoje * 1.002, 2)
            stop_loss = round(entrada_gatilho - (atr * 1.5), 2)
            
            risco = entrada_gatilho - stop_loss
            # ASSIMETRIA 3:1 (A Grande Diferença do Motor 21)
            alvo_tp = round(entrada_gatilho + (risco * 3.0), 2)

            qtd_calc = round(vol_diaria_usd / risco, 2) if risco > 0 else 0.0
            val_calc = entrada_gatilho * qtd_calc

            return {
                "ticker": ticker,
                "preco_atual": round(preco, 2),
                "gatilho": entrada_gatilho,
                "stop_loss": stop_loss,
                "alvo_tp": alvo_tp,
                "qtd_acoes": qtd_calc,
                "valor_investir": round(val_calc, 2),
                "rvol": round(rvol, 2),
                "estado_confluencia": "💎 CONFLUÊNCIA SUPREMA (Pullback + Squeeze + Volume Institucional)"
            }
        return None
    except Exception as e:
        print(f"[ERRO] Falha ao processar ativo {ativo_info.get('ticker')}: {e}")
        return None

# ===================================================================
# 5. EXECUÇÃO PRINCIPAL E RELATÓRIO
# ===================================================================
def executar_motor():
    if not ativos_sheets: sys.exit(0)
    
    # 1. Verifica Filtro Macro (Se o mercado estiver fraco, notifica e regista, mas envia sempre os alertas)
    if not mercado_em_alta():
        aviso_defensivo = "✅ [MERCADO FRACO] O SPY encontra-se abaixo da EMA 20. O Motor 21 bloqueou novos sinais para proteger capital (Modo Defensivo).\n"
        print(aviso_defensivo)
        
        # Gravação do ficheiro para o Orquestrador
        with open("comboio_confluencia_temp.txt", "w", encoding="utf-8") as f:
            f.write(aviso_defensivo)
            
        # Envio forçado de E-mail
        enviar_email(aviso_defensivo)
        
        # Envio forçado para o Telegram
        enviar_alerta("21 ⚡ *MOTOR 21 (CONFLUÊNCIA SUPREMA)*\n\n🛡️ *MODO DEFENSIVO ATIVO*\nO SPY está abaixo da EMA 20. Novas entradas bloqueadas.")
        
        sys.exit(0)

    alertas_confluencia = []
    
    for ativo_info in ativos_sheets:
        if not ativo_info.get("ticker") or ativo_info.get("ticker") == "#N/A": continue
        res = analisar_confluencia_suprema(ativo_info)
        if res: alertas_confluencia.append(res)

    data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M")
    bloco_texto = f"⚡ RELATÓRIO DETALHADO - MOTOR 21: CONFLUÊNCIA SUPREMA ({data_hoje})\n==================================================================\n\n"

    if bloco_posicoes_ativas:
        bloco_texto += f"📌 GESTÃO DE POSIÇÕES ATIVAS:\n{bloco_posicoes_ativas}\n--------------------------------------------------\n\n"
    else:
        bloco_texto += "📌 GESTÃO DE POSIÇÕES ATIVAS: Nenhuma posição ativa detetada para este motor.\n--------------------------------------------------\n\n"

    if alertas_confluencia:
        bloco_texto += f"🎯 SINAIS DE ALTA PROBABILIDADE (SNIPER) ({len(alertas_confluencia)}):\n\n"
        for a in alertas_confluencia:
            info_ativo = next((item for item in ativos_sheets if str(item.get("ticker","")).strip().upper() == a['ticker']), {})
            bloco_texto += (
                f"💎 [{a['ticker']}] - {info_ativo.get('nome', 'N/A')} ({info_ativo.get('setor', 'Desconhecido')})\n"
                f"    - 📊 Contexto Técnico: {a['estado_confluencia']}\n"
                f"    - ⚙️ Tática: Breakout Sniper Assímetrico\n"
                f"    - 📋 Tipo de Ordem: BUY STOP (Gatilho: ${a['gatilho']})\n"
                f"    - 🔢 Risco/Retorno (3:1): Stop Loss: ${a['stop_loss']} | Alvo: ${a['alvo_tp']}\n"
                f"    - 💰 Dimensionamento: Qtd: {a['qtd_acoes']} | Investimento: ~${a['valor_investir']} USD\n"
                f"    - 📈 Métricas de Força: RS Score >= 75 | RVOL: {a['rvol']}x\n"
                f"--------------------------------------------------\n"
            )
    else:
        bloco_texto += "✅ Nenhum ativo atingiu a perfeição técnica exigida pelo Motor 21 hoje. O capital permanece seguro.\n"

    enviar_email(bloco_texto)

    with open("comboio_confluencia_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco_texto)

    # Notificação no Telegram
    enviar_alerta(f"21 ⚡ *MOTOR 21 (CONFLUÊNCIA)*\n\n🔍 Execução Concluída.\n🎯 Acionados: *{len(alertas_confluencia)}*")

if __name__ == "__main__":
    executar_motor()
