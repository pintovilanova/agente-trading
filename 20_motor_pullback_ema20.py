# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR 20: PULLBACK À EMA 20
# ===================================================================================
# Descrição Geral:
# Identifica ativos com forte Força Relativa (RS Score > 60) e tendência de alta
# (EMA 20 > SMA 50) que realizam um pullback cirúrgico de defesa junto à EMA 20,
# auditando em simultâneo as posições ativas em carteira (estritamente ATIVA_M20).
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

from F01_notificador_telegram import enviar_alerta

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O Motor Pullback EMA 20 vai descansar.")
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
# 2. FUNÇÕES DE REDE E CONFIGS
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
                print(f"[ERRO] O Webhook não retornou um JSON válido.")
                return [], {}, {}

            if isinstance(dados, dict):
                ativos = dados.get("ativos", [])
                posicoes = dados.get("posicoesAtivas", {}) or dados.get("posicoes", {})
                configs = dados.get("configs", {})
                return ativos, posicoes, configs
            elif isinstance(dados, list):
                return dados, {}, {}
        return [], {}, {}
    except Exception as e:
        print(f"[ERRO CRÍTICO] Sheets: {e}")
        return [], {}, {}

def enviar_email(conteudo):
    print("\nA enviar relatório detalhado do Motor 20 por e-mail...")
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] EMAIL_USER ou EMAIL_PASS não definidos.")
        return False

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = f"⚡ tradingRelatorioIA US - MOTOR 20 PULLBACK EMA 20 ({datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')})"
    msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
    
    for tentativa in range(3):
        try:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
            server.quit()
            print("[SUCESSO] Email enviado com sucesso!")
            return True
        except Exception as e:
            print(f"[ERRO EMAIL] Falha na tentativa {tentativa + 1}: {e}")
            if tentativa < 2: time.sleep(5)
    return False

# ===================================================================
# 3. CARGA DE DADOS E PARAMETRIZAÇÃO DE RISCO
# ===================================================================
ativos_sheets, posicoes_ativas_dict, configs_dict = buscar_dados_completos()

try:
    capital = float(configs_dict.get("CAPITAL_TOTAL_CONTA", 10400.00))
    pct_risco = limpar_float(configs_dict.get("RISCO_SWING_PCT")) or limpar_float(configs_dict.get("RISCO_POR_TRADE")) or 0.01
except (ValueError, TypeError):
    capital, pct_risco = 10400.00, 0.01

vol_diaria_usd = capital * pct_risco
print(f"[CONFIG] Capital Total: ${capital:,.2f} | Risco/Trade: {pct_risco*100:.1f}% (${vol_diaria_usd:,.2f} USD)\n")

# ===================================================================
# 4. AUDITAR POSIÇÕES EM CARTEIRA (ESTRITO: ATIVA_M20)
# ===================================================================
bloco_posicoes_ativas = ""
for chave_pos, info in posicoes_ativas_dict.items():
    if not isinstance(info, dict): continue
    status = str(info.get("status", "")).strip().upper()
    
    if status == "ATIVA_M20":
        try:
            ticker = "AI" if chave_pos.lower() in ["c3.ai", "c3"] else chave_pos.strip().upper()
            
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
                
                if alvo_tp > 0 and preco_atual >= alvo_tp:
                    acao = f"🎯 ALVO ALCANÇADO (TP em ${alvo_tp})! Recomendado FECHAR POSIÇÃO com Lucro (WIN)."
                elif stop > 0 and minima_hoje <= stop:
                    acao = f"🚨 STOP LOSS ATINGIDO (${stop})! Recomendado LIQUIDAR POSIÇÃO (LOSS)."
                else:
                    acao = f"⏳ MANTER POSIÇÃO (Pullback EMA 20). Alvo TP: ${alvo_tp} | Stop: ${stop}."
                
                bloco_posicoes_ativas += (
                    f"📌 [{status}] {ticker} ({chave_pos}) | Qtd: {qtd} | Entrada: ${entrada} | "
                    f"Atual: ${preco_atual} | {acao}\n"
                )
        except Exception as e:
            print(f"[ERRO] Falha ao auditar posição ativa {chave_pos}: {e}")

# ===================================================================
# 5. MOTOR MATEMÁTICO: PULLBACK À EMA 20
# ===================================================================
def analisar_pullback_ema20(ativo_info):
    try:
        # FILTRO DE FORÇA RELATIVA (RS SCORE MÍNIMO)
        rs_score_raw = ativo_info.get("rs_score", 0)
        try:
            rs_score = float(str(rs_score_raw).replace(",", ".").strip())
        except (ValueError, TypeError):
            rs_score = 0.0

        if rs_score < 60.0:
            return None

        ticker = str(ativo_info.get("ticker", "")).strip().upper()
        if not ticker or ticker == "#N/A" or ticker == "NONE": return None
        if ticker in posicoes_ativas_dict: return None
        if ticker == "BRK-A": ticker = "BRK-B"

        time.sleep(random.uniform(0.8, 1.8))

        df = pd.DataFrame()
        for _ in range(3):
            try:
                df = yf.download(ticker, period="6mo", interval="1d", progress=False, timeout=15)
                if not df.empty and len(df) >= 50:
                    break
            except Exception:
                time.sleep(2)

        if df.empty or len(df) < 50: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
        df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])

        preco = float(df['Close'].iloc[-1])
        if preco < 5.00: return None

        # Indicadores de Tendência
        df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df.ta.atr(length=14, append=True)

        col_atr = [c for c in df.columns if str(c).startswith('ATRr_') or str(c).startswith('ATR_')][0]
        df = df.dropna(subset=['EMA_20', 'SMA_50', col_atr])
        if df.empty: return None

        ultimo = df.iloc[-1]
        ema20 = float(ultimo['EMA_20'])
        sma50 = float(ultimo['SMA_50'])
        atr = float(ultimo[col_atr])
        
        minimo_hoje = float(ultimo['Low'])
        fecho_hoje = float(ultimo['Close'])
        maximo_hoje = float(ultimo['High'])

        # Condições do Setup: Tendência de alta (EMA 20 > SMA 50) + Toque na EMA 20 + Fecho acima
        tendencia_alta = ema20 > sma50
        toque_ema20 = (minimo_hoje <= ema20) and (fecho_hoje >= ema20)

        if tendencia_alta and toque_ema20:
            entrada_gatilho = round(maximo_hoje * 1.002, 2)
            stop_loss = round(entrada_gatilho - (atr * 1.5), 2)
            
            risco = entrada_gatilho - stop_loss
            alvo_tp = round(entrada_gatilho + (risco * 2.0), 2)

            if alvo_tp <= entrada_gatilho:
                alvo_tp = round(entrada_gatilho + (risco * 1.5), 2)

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
                "estado_pullback": "A ATIVAR (Pullback Detetado: Preço defendeu a EMA 20)"
            }
        return None
    except Exception as e:
        print(f"[ERRO] Falha ao processar ativo {ativo_info.get('ticker')}: {e}")
        return None

# ===================================================================
# 6. EXECUÇÃO PRINCIPAL E RELATÓRIO DETALHADO
# ===================================================================
def executar_motor():
    if not ativos_sheets: sys.exit(0)

    alertas_pullback = []
    total_analisados = 0
    
    for ativo_info in ativos_sheets:
        ticker = ativo_info.get("ticker")
        if not ticker or ticker == "#N/A": continue
        
        total_analisados += 1
        res = analisar_pullback_ema20(ativo_info)
        if res: alertas_pullback.append(res)

    data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M")
    
    bloco_texto = (
        f"⚡ RELATÓRIO DETALHADO - MOTOR 20: PULLBACK À EMA 20 ({data_hoje})\n"
        f"==================================================================\n\n"
    )

    if bloco_posicoes_ativas:
        bloco_texto += f"📌 GESTÃO DE POSIÇÕES ATIVAS:\n{bloco_posicoes_ativas}\n--------------------------------------------------\n\n"
    else:
        bloco_texto += "📌 GESTÃO DE POSIÇÕES ATIVAS: Nenhuma posição ativa detetada para este motor.\n--------------------------------------------------\n\n"

    if alertas_pullback:
        bloco_texto += f"🎯 NOVOS SINAIS DE PULLBACK À EMA 20 ({len(alertas_pullback)}):\n\n"
        for a in alertas_pullback:
            info_ativo = next((item for item in ativos_sheets if str(item.get("ticker","")).strip().upper() == a['ticker']), {})
            nome_empresa = info_ativo.get("nome", "N/A")
            setor = info_ativo.get("setor", "Desconhecido")
            rs_score = info_ativo.get("rs_score", "N/A")
            
            bloco_texto += (
                f"🔹 [{a['ticker']}] - {nome_empresa} ({setor})\n"
                f"   - 📊 Contexto Técnico: {a['estado_pullback']}\n"
                f"   - ⚙️ Tática: Continuação de Tendência (Hit & Run 48h-72h)\n"
                f"   - 📋 Tipo de Ordem: BUY STOP (Gatilho na quebra da máxima diária da vela de defesa)\n"
                f"   - 🔢 Dados Exatos: Gatilho Compra: ${a['gatilho']} | Stop Loss: ${a['stop_loss']} | Alvo: ${a['alvo_tp']}\n"
                f"   - 💰 Dimensionamento: Qtd: {a['qtd_acoes']} | Valor a Investir: ~${a['valor_investir']} USD\n"
                f"   - 📈 RS Score Institucional: {rs_score}\n"
                f"--------------------------------------------------\n"
            )
    else:
        bloco_texto += "✅ Nenhum novo sinal de Pullback à EMA 20 detetado hoje.\n"

    # Enviar o relatório por e-mail
    enviar_email(bloco_texto)

    # 📌 GRAVAR FICHEIRO TEMPORÁRIO PARA O LOOP GERAL / AGENTE IA
    with open("comboio_pullback_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco_texto)

    # ===================================================================
    # 7. NOTIFICAÇÃO TELEGRAM DEBUG
    # ===================================================================
    debug_telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

    if debug_telegram_ativado:
        print("A enviar notificação de Debug para o Telegram via função modular...")
        total_acionados = len(alertas_pullback)
        mensagem_debug = (
            f"20 ⚡ *MOTOR 20 (PULLBACK EMA 20)*\n\n"
            f"🔍 [DEBUG] Execução concluída com sucesso.\n"
            f"📊 Ativos analisados: *{total_analisados}* | Acionados: *{total_acionados}*\n"
            f"✉️ Relatório de pullback gerado e enviado por e-mail."
        )
        enviar_alerta(mensagem_debug)

if __name__ == "__main__":
    executar_motor()
