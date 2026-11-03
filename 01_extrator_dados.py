# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - EXTRATOR DE DADOS & US BREAKOUTS
# ===================================================================================

import os
import sys
import time
import random
import json
import smtplib
import requests
import pandas as pd
import yfinance as yf
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from zoneinfo import ZoneInfo
import warnings
warnings.filterwarnings("ignore")

from F01_notificador_telegram import enviar_alerta

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O Extrator de Dados vai descansar.")

# ===================================================================
# 1. CONFIGURAÇÕES E CREDENCIAIS
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
EMAIL_USER = os.environ.get('EMAIL_USER')
EMAIL_PASS = os.environ.get('EMAIL_PASS')

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
# 2. FUNÇÕES DE REDE
# ===================================================================
def buscar_dados_completos():
    print("A carregar a Watchlist, Posições Ativas e Configurações a partir do Google Sheets...")
    if not WEBHOOK_URL: 
        print("[ERRO] WEBHOOK_URL não configurado nas variáveis de ambiente.")
        return [], {}, {}
    try:
        url_alvo = WEBHOOK_URL if "?" in WEBHOOK_URL else f"{WEBHOOK_URL}?aba=Analise Compra"
        resp = requests.get(url_alvo, timeout=15)
        if resp.status_code == 200:
            dados = resp.json()
            if isinstance(dados, dict):
                ativos = dados.get("ativos", [])
                posicoes = dados.get("posicoesAtivas", {}) or dados.get("posicoes", {})
                configs = dados.get("configs", {})
                return ativos, posicoes, configs
            elif isinstance(dados, list):
                return dados, {}, {}
        return [], {}, {}
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha ao conectar ao Sheets: {e}")
        return [], {}, {}

def enviar_email(assunto, conteudo):
    print(f"\nA enviar e-mail ('{assunto}')...")
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] EMAIL_USER ou EMAIL_PASS não configurados.")
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_USER
        msg['Subject'] = assunto
        msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
        server.quit()
        print("[SUCESSO] E-mail enviado com sucesso!")
        return True
    except Exception as e:
        print(f"[ERRO] Falha ao enviar e-mail: {e}")
        return False

# ===================================================================
# 3. CARGA DE DADOS
# ===================================================================
ativos_sheets, posicoes_ativas_dict, configs_dict = buscar_dados_completos()
print(f"[SUCESSO] {len(ativos_sheets)} ativos carregados da Watchlist.")
print(f"[SUCESSO] {len(posicoes_ativas_dict)} posições ativas detetadas.\n")

# ===================================================================
# 4. AUDITAR POSIÇÕES EM CARTEIRA
# ===================================================================
bloco_posicoes_ativas = ""
for chave_pos, info in posicoes_ativas_dict.items():
    if not isinstance(info, dict): continue
    status = str(info.get("status", "")).strip().upper()
    
    if status and status != "FECHADA":
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
                
                if alvo_tp > 0 and maxima_efetiva >= alvo_tp:
                    acao = f"🎯 ALVO ALCANÇADO (TP em ${alvo_tp})! Recomendado FECHAR POSIÇÃO com Lucro (WIN)."
                elif stop > 0 and minima_hoje <= stop:
                    acao = f"🚨 STOP LOSS ATINGIDO (${stop})! Recomendado LIQUIDAR POSIÇÃO (LOSS)."
                else:
                    acao = f"⏳ MANTER POSIÇÃO. Alvo TP: ${alvo_tp} | Stop: ${stop}."
                
                bloco_posicoes_ativas += (
                    f"📌 [{status}] {ticker} ({chave_pos}) | Qtd: {qtd} | Entrada: ${entrada} | "
                    f"Preço Atual: ${preco_atual} | {acao}\n"
                )
        except Exception as e:
            print(f"[ERRO] Falha ao auditar posição ativa {chave_pos}: {e}")

# ===================================================================
# 5. VERIFICAÇÃO DE VETO MACRO (SPY)
# ===================================================================
print("A verificar Veto Macro (SPY)...")
veto_macro_ativo = False
motivo_veto = ""

try:
    df_spy = yf.download("SPY", period="5d", interval="1d", progress=False)
    if isinstance(df_spy.columns, pd.MultiIndex):
        df_spy.columns = df_spy.columns.droplevel(1)
        
    if not df_spy.empty and len(df_spy) >= 2:
        preco_spy = float(df_spy['Close'].iloc[-1])
        preco_spy_ontem = float(df_spy['Close'].iloc[-2])
        var_spy = ((preco_spy - preco_spy_ontem) / preco_spy_ontem) * 100
        
        if var_spy <= -1.50:
            veto_macro_ativo = True
            motivo_veto = f"SPY em Pânico: Caiu {var_spy:.2f}% (<= -1.50%). Abertura de novas posições bloqueada."
            print(f"[ALERTA MACRO] {motivo_veto}")
except Exception as e:
    print(f"[AVISO] Falha ao verificar filtro SPY: {e}")

# ===================================================================
# 6. RASTREIO DE ATIVOS US BREAKOUT (NOVA SECÇÃO)
# ===================================================================
bloco_us_breakouts = ""

if not veto_macro_ativo and ativos_sheets:
    print("\nA iniciar rastreio técnico para US Breakouts...")
    
    for item in ativos_sheets:
        if isinstance(item, dict):
            ticker = item.get("ticker", "").strip().upper()
            nome = item.get("nome", ticker)
            setor = item.get("setor", "Desconhecido")
            rs_score = item.get("rsScore", "N/A")
            earnings = item.get("earnings", "OK")
        else:
            ticker = str(item).strip().upper()
            nome, setor, rs_score, earnings = ticker, "Desconhecido", "N/A", "OK"

        if not ticker or "." in ticker:  # Filtra ativos não-US (ex: .PA, .DE, .LS)
            continue

        try:
            df = yf.download(ticker, period="3mo", interval="1d", progress=False)
            if df.empty or len(df) < 20: continue
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)

            preco = round(float(df['Close'].iloc[-1]), 2)
            mm20 = df['Close'].rolling(20).mean().iloc[-1]
            dist_mm20 = round(((preco - mm20) / mm20) * 100, 2)
            ema9 = round(float(df['Close'].ewm(span=9).mean().iloc[-1]), 2)
            
            # Cálculo de ATR (14)
            high_low = df['High'] - df['Low']
            high_cp = (df['High'] - df['Close'].shift(1)).abs()
            low_cp = (df['Low'] - df['Close'].shift(1)).abs()
            tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
            atr = round(float(tr.rolling(14).mean().iloc[-1]), 2)
            vol_percent = round((atr / preco) * 100, 2)

            # Volume Relativo (RVOL)
            vol_media = df['Volume'].rolling(20).mean().iloc[-1]
            rvol = round(float(df['Volume'].iloc[-1] / vol_media), 2) if vol_media > 0 else 1.0

            # Condição de Breakout (Exemplo: Próximo ou acima da máxima de 20 dias com volume)
            max_20 = df['High'].iloc[-21:-1].max()
            if preco >= (max_20 * 0.98) and rvol >= 1.2:
                gatilho = round(max_20 * 1.005, 2)
                stop = round(gatilho - (2 * atr), 2)
                tp = round(gatilho + (4 * atr), 2)
                qtd = round(500 / (gatilho - stop), 2) if (gatilho - stop) > 0 else 1.0
                
                linha_breakout = (
                    f"{ticker},Nome: {nome},Setor: {setor},Preço: {preco},RS Score: {rs_score},"
                    f"Dist MM20: {dist_mm20}%,EMA9: {ema9},ATR: {atr} (Vol: {vol_percent}%),RVOL: {rvol},"
                    f"Estado: Aguardar Recuo,Entrada: {gatilho},Stop: {stop},Take-Profit: {tp},"
                    f"Qtd: {qtd},ValorInvestir: ~{round(qtd*gatilho, 2)} USD,Earnings: {earnings}\n"
                )
                bloco_us_breakouts += linha_breakout
        except Exception:
            continue

# ===================================================================
# 7. MONTAGEM DO FICHEIRO TEMPORÁRIO E RELATÓRIO
# ===================================================================
data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M")

bloco_texto = (
    f"⚡ RELATÓRIO EXTRATOR DE DADOS US ({data_hoje})\n"
    f"==================================================================\n\n"
)

if veto_macro_ativo:
    bloco_texto += f"🚨 [VETO MACRO ATIVADO]\n{motivo_veto}\n"
    bloco_texto += "⚠️ Novas compras suspensas hoje, mas a pipeline continua para auditar e gerir as POSIÇÕES ATIVAS em carteira.\n"
    bloco_texto += "--------------------------------------------------\n\n"
else:
    bloco_texto += "🟢 [MERCADO ESTÁVEL] Filtro do SPY dentro dos parâmetros normais. Pipeline autorizada.\n"
    bloco_texto += "--------------------------------------------------\n\n"

if bloco_posicoes_ativas:
    bloco_texto += f"📌 GESTÃO DE POSIÇÕES ATIVAS:\n{bloco_posicoes_ativas}\n--------------------------------------------------\n\n"
else:
    bloco_texto += "📌 GESTÃO DE POSIÇÕES ATIVAS: Nenhuma posição ativa detetada.\n--------------------------------------------------\n\n"

if veto_macro_ativo:
    bloco_texto += "✅ Análise de novas entradas da watchlist omitida devido ao Veto Macro.\n"
else:
    bloco_texto += "DADOS DOS ATIVOS ACIONADOS (US BREAKOUTS):\n\n"
    if bloco_us_breakouts:
        bloco_texto += bloco_us_breakouts
    else:
        bloco_texto += "[SEM SINAIS US BREAKOUT] Nenhum ativo atendeu aos critérios de breakout de volume hoje.\n\n"
    bloco_texto += f"--------------------------------------------------\nWatchlist auditada e pronta com {len(ativos_sheets)} ativos ativos.\n"

# ===================================================================
# 8. GRAVAÇÃO DO FICHEIRO E NOTIFICAÇÕES
# ===================================================================
print("A gravar ficheiro temporário 'comboio_temp.txt'...")
with open("comboio_temp.txt", "w", encoding="utf-8") as f:
    f.write(bloco_texto)

assunto_email = f"📥⚡ tradingRelatorioIA US - EXTRATOR DE DADOS 🛡️ ({datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')})"
enviar_email(assunto_email, bloco_texto)

debug_telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

if debug_telegram_ativado or veto_macro_ativo:
    print("A enviar notificação para o Telegram...")
    status_macro = "🚨 *VETO MACRO ATIVADO*" if veto_macro_ativo else "🟢 *MERCADO ESTÁVEL*"
    mensagem_telegram = (
        f"📥⚡ *EXTRATOR DE DADOS US*\n\n"
        f"🔍 [STATUS] Extração e auditoria concluídas.\n"
        f"📊 Estado Macro: {status_macro}\n"
        f"📈 Ativos na Watchlist: *{len(ativos_sheets)}* | Posições auditadas: *{len(posicoes_ativas_dict)}*\n"
        f"✉️ Relatório gerado e enviado por e-mail."
    )
    enviar_alerta(mensagem_telegram)

print("[SUCESSO] Extração e rastreio US concluídos com sucesso.")
sys.exit(0)
