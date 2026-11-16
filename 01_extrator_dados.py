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
import pandas_ta as ta
import yfinance as yf
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from zoneinfo import ZoneInfo
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
# 2. FUNÇÕES DE REDE (LEITURA E ESCRITA NO GOOGLE SHEETS)
# ===================================================================
def buscar_dados_completos():
    print("A carregar a Watchlist, Posições Ativas e Configurações a partir do Google Sheets...")
    if not WEBHOOK_URL: 
        print("[ERRO] WEBHOOK_URL não configurado nas variáveis de ambiente.")
        return [], {}, {}
    try:
        url_alvo = WEBHOOK_URL if "?" in WEBHOOK_URL else f"{WEBHOOK_URL}?aba=Analise Compra"
        resp = requests.get(url_alvo, timeout=25)
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

def atualizar_sheets_colunas_todas(lista_dados):
    print(f"\nA enviar {len(lista_dados)} ativos para o Google Sheets (acao: 'atualizar_colunas_todas')...")
    if not WEBHOOK_URL:
        print("[ERRO] WEBHOOK_URL não configurado. Impossível escrever no Sheets.")
        return False
    if not lista_dados:
        print("[AVISO] Lista de dados vazia. Nada para enviar ao Sheets.")
        return False

    payload = {
        "acao": "atualizar_colunas_todas",
        "aba": "Analise Compra",
        "dados": lista_dados
    }

    try:
        resp = requests.post(
            WEBHOOK_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        if resp.status_code == 200:
            print(f"[SUCESSO] Google Sheets atualizado! Resposta: {resp.text[:200]}")
            return True
        else:
            print(f"[ERRO SHEETS] HTTP {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"[ERRO CRÍTICO SHEETS POST] Falha ao gravar no Sheets: {e}")
        return False

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
# 3. CARGA DE DADOS & PARÂMETROS DE CONFIGURAÇÃO
# ===================================================================
ativos_sheets, posicoes_ativas_dict, configs_dict = buscar_dados_completos()
print(f"[SUCESSO] {len(ativos_sheets)} ativos carregados da Watchlist.")
print(f"[SUCESSO] {len(posicoes_ativas_dict)} posições ativas detetadas.\n")

# Lê risco máximo e trailing multiplier da aba Configs (tal como no Apps Script)
risco_maximo_dolares = 25.00
multiplicador_trailing = 1.5
for k, v in configs_dict.items():
    k_low = str(k).lower()
    if "risco" in k_low:
        val = limpar_float(v)
        if val and val > 0: risco_maximo_dolares = val
    if "trailing" in k_low:
        val = limpar_float(v)
        if val and val > 0: multiplicador_trailing = val

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
                
                if alvo_tp > 0 and maxima_efetiva >= alvo_tp:
                    acao = f"🎯 ALVO ALCANÇADO (TP em ${alvo_tp})! Recomendado FECHAR POSIÇÃO com Lucro (WIN)."
                elif stop > 0 and preco_atual <= stop:
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
    df_spy = yf.download("SPY", period="1y", interval="1d", progress=False, session=session)
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
# 6. EXTRAÇÃO DE DADOS & GUILHOTINA MATEMÁTICA V2 (US WATCHLIST)
# ===================================================================
dados_para_sheets = []
bloco_ativos_acionados = ""

if ativos_sheets:
    print("\nA extrair indicadores técnicos para todos os ativos da Watchlist...")
    
    for item in ativos_sheets:
        if isinstance(item, dict):
            ticker_orig = str(item.get("ticker", "")).strip().upper()
            nome = item.get("nome", ticker_orig)
            rs_score = item.get("rs_score") or item.get("rsScore") or "N/A"
        else:
            ticker_orig = str(item).strip().upper()
            nome, rs_score = ticker_orig, "N/A"

        if not ticker_orig or ticker_orig == "#N/A":
            continue

        # Filtra ativos europeus (que têm sufixo .PA, .DE, .LS, etc., exceto BRK.A/BRK.B)
        if "." in ticker_orig and ticker_orig not in ["BRK.A", "BRK.B"]:
            continue

        ticker_yf = ticker_orig.replace(".", "-")

        try:
            time.sleep(random.uniform(0.25, 0.6))
            df = yf.download(ticker_yf, period="3mo", interval="1d", progress=False, session=session)
            if df.empty or len(df) < 20: continue
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
            df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])

            preco = round(float(df['Close'].iloc[-1]), 2)
            preco_anterior = float(df['Close'].iloc[-2])
            var_perc = ((preco - preco_anterior) / preco_anterior) * 100

            mm20 = float(df['Close'].rolling(20).mean().iloc[-1])
            val_dist_mm20 = ((preco - mm20) / mm20) * 100
            dist_mm20_str = f"{val_dist_mm20:.2f}%"
            
            # Momentum (14 períodos, igual ao valores[14] do teu Apps Script)
            val_momentum = round(float(preco - float(df['Close'].iloc[-15])), 2) if len(df) >= 15 else 0.0

            # RSI (14)
            df.ta.rsi(length=14, append=True)
            col_rsi = [c for c in df.columns if str(c).startswith('RSI_')][0]
            val_rsi = round(float(df[col_rsi].iloc[-1]), 2)

            # ADX (14)
            df.ta.adx(length=14, append=True)
            col_adx = [c for c in df.columns if str(c).startswith('ADX_')][0]
            val_adx = round(float(df[col_adx].iloc[-1]), 2)

            # ATR (14)
            df.ta.atr(length=14, append=True)
            col_atr = [c for c in df.columns if str(c).startswith('ATRr_') or str(c).startswith('ATR_')][0]
            atr = round(float(df[col_atr].iloc[-1]), 2)
            atr_perc = round((atr / preco) * 100, 2)

            # RVOL (20)
            vol_media = float(df['Volume'].rolling(20).mean().iloc[-1])
            val_rvol = round(float(df['Volume'].iloc[-1] / vol_media), 2) if vol_media > 0 else 1.0

            # ===============================================================
            # GUILHOTINA MATEMÁTICA V2 (Réplica exata do teu Apps Script)
            # ===============================================================
            recomendacao = "Observar"
            preco_entrada = "N/A"
            preco_stop = "N/A"
            preco_tp = "N/A"
            preco_be = "N/A"
            qtd_acoes = "N/A"
            multiplicador_atr = 1.0
            racio_tp = 1.2

            preco_caiu_hoje = preco < preco_anterior
            volume_despejo = val_rvol > 1.20

            if (preco_caiu_hoje and volume_despejo) or val_momentum <= 0.5:
                recomendacao = "Observar"
            elif var_perc > 0 and val_adx < 25:
                recomendacao = "Aguardar Recuo"
                preco_entrada = f"{(preco - (atr * 0.4)):.2f}"
                multiplicador_atr = 1.0
            elif (var_perc > 0 and val_adx >= 30 and val_rvol >= 1.20 and 
                  55.00 <= val_rsi <= 72.00 and 0.00 <= val_dist_mm20 <= 3.50 and val_momentum > 1.50):
                recomendacao = "Forca Consolidada"
                preco_entrada = f"{(preco - (atr * 0.1)):.2f}"
                multiplicador_atr = 1.3
            elif (val_adx >= 25 and val_rvol >= 1.00 and 
                  50.00 <= val_rsi <= 75.00 and -1.00 <= val_dist_mm20 <= 4.00 and val_momentum > 0.50):
                recomendacao = "Alerta Iminente"
                preco_entrada = f"{(preco - (atr * 0.2)):.2f}"
                multiplicador_atr = 1.2
            else:
                recomendacao = "Observar"

            if recomendacao != "Observar" and preco_entrada != "N/A":
                ent_num = float(preco_entrada)
                stop_num = ent_num - (atr * multiplicador_atr)
                preco_stop = f"{stop_num:.2f}"
                risco_por_acao = ent_num - stop_num
                if risco_por_acao > 0:
                    risco_alocado = risco_maximo_dolares
                    if val_rvol >= 3.00: risco_alocado += (risco_maximo_dolares * 0.5)
                    if val_adx >= 35.00: risco_alocado += (risco_maximo_dolares * 0.5)
                    tp_num = ent_num + (risco_por_acao * racio_tp)
                    preco_tp = f"{tp_num:.2f}"
                    qtd_acoes = f"{(risco_alocado / risco_por_acao):.2f}"
                    preco_be = f"{(ent_num + ((tp_num - ent_num) / 2)):.2f}"

            # Trailing Stop (Math.max com stop atual da carteira se existir)
            trailing_calc = preco - (atr * multiplicador_trailing)
            stop_carteira = 0.0
            if ticker_orig in posicoes_ativas_dict and isinstance(posicoes_ativas_dict[ticker_orig], dict):
                stop_carteira = limpar_float(posicoes_ativas_dict[ticker_orig].get("stopAtual")) or 0.0

            if stop_carteira > 0:
                trailing_final = max(trailing_calc, stop_carteira)
            else:
                piso_entrada = float(preco_stop) if preco_stop != "N/A" else 0.0
                trailing_final = max(trailing_calc, piso_entrada)
            preco_trailing = f"{trailing_final:.2f}"

            timestamp_str = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M:%S")

            # String "Comboio" exata para a Coluna S (19)
            comboio_str = (
                f"{ticker_orig},"
                f"Preço: {preco:.2f},"
                f"Dist MM20: {dist_mm20_str},"
                f"Momentum: {val_momentum:.2f},"
                f"RSI: {val_rsi:.2f},"
                f"ADX: {val_adx:.2f},"
                f"ATR: {atr:.2f} (Vol: {atr_perc:.2f}%),"
                f"RVOL: {val_rvol:.2f},"
                f"Estado: {recomendacao},"
                f"Entrada: {preco_entrada},"
                f"Stop: {preco_stop},"
                f"Take-Profit: {preco_tp},"
                f"Break-Even: {preco_be},"
                f"Qtd: {qtd_acoes},"
                f"Trailing: {preco_trailing},"
                f"Data: {timestamp_str}"
            )

            # Objeto exato esperado pelo doPost ("atualizar_colunas_todas")
            dados_para_sheets.append({
                "ticker": ticker_orig,
                "preco": preco,
                "momentum": val_momentum,
                "rsi": val_rsi,
                "adx": val_adx,
                "atr": atr,
                "time": timestamp_str,
                "comboio": comboio_str
            })

            if recomendacao in ["Forca Consolidada", "Alerta Iminente"]:
                bloco_ativos_acionados += f"{comboio_str} | Nome: {nome} | RS Score: {rs_score}\n"

        except Exception as e:
            print(f"[AVISO] Falha ao processar {ticker_orig}: {e}")
            continue

# ===================================================================
# 7. ESCRITA NO GOOGLE SHEETS + MONTAGEM DO RELATÓRIO
# ===================================================================
atualizar_sheets_colunas_todas(dados_para_sheets)

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
    if bloco_ativos_acionados:
        bloco_texto += bloco_ativos_acionados
    else:
        bloco_texto += "[SEM SINAIS US BREAKOUT] Nenhum ativo em Força Consolidada ou Alerta Iminente hoje.\n\n"
    bloco_texto += f"--------------------------------------------------\nWatchlist auditada e atualizada no Sheets ({len(dados_para_sheets)}/{len(ativos_sheets)} ativos).\n"

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
        f"📈 Sheets Atualizado: *{len(dados_para_sheets)}/{len(ativos_sheets)}* ativos (Colunas G, K, L, M, N, Q e S)\n"
        f"✉️ Relatório gerado e enviado por e-mail."
    )
    enviar_alerta(mensagem_telegram)

print("[SUCESSO] Extração e rastreio US concluídos com sucesso.")
sys.exit(0)
