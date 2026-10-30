# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR HOLY GRAIL (PULLBACKS DE LIDERANÇA)
# ===================================================================================
# Descrição Geral:
# Implementa a estratégia "Holy Grail" (popularizada por Linda Raschke/David Ryan).
# Procura ativos com Força Relativa de Elite (RS >= 80) e forte tendência direcional
# (ADX > 25), que estão a sofrer um pullback natural de curto prazo, tocando na 
# Média Móvel Exponencial (EMA) de 20 ou 21 dias, com forte contração de volume,
# auditando em simultâneo as posições ativas em carteira (ATIVA_M10 / ATIVA_SWING)
# com base na lógica dinâmica de EMA20 e ATR.
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
import json
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import warnings
warnings.filterwarnings("ignore")
import random

# Importação da função modular de notificação do Telegram
from F01_notificador_telegram import enviar_alerta

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O Motor Holy Grail vai descansar.")
    #sys.exit(0)

# ===================================================================
# 1. CONFIGURAÇÕES E CREDENCIAIS
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

MIN_RS_SCORE_HOLY_GRAIL = 80.0  # Exigência extrema: Só pullbacks em líderes absolutos

def limpar_float(val):
    """Converte com segurança valores numéricos (mesmo com vírgulas) para float."""
    if val is None: return None
    try:
        val_str = str(val).replace(",", ".").strip()
        if val_str == "" or val_str.lower() in ["nan", "n/a", "none"]: return None
        return float(val_str)
    except (ValueError, TypeError):
        return None

# ===================================================================
# 2. FUNÇÕES DE REDE (LEITURA COMPLETA DO SHEETS)
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
    print("\nA enviar email do Holy Grail Pullbacks para o Agente IA...")
    if not EMAIL_USER or not EMAIL_PASS: return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = "🏆 tradingRelatorioIA US - HOLY GRAIL PULLBACKS"
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
# 3. EXECUÇÃO PRINCIPAL
# ===================================================================
def executar_motor():
    ativos_sheets, posicoes_ativas_dict, configs_dict = buscar_dados_completos()
    if not ativos_sheets and not posicoes_ativas_dict:
        print("[AVISO] Nenhum dado retornado do Google Sheets.")
        sys.exit(0)

    try:
        capital = float(configs_dict.get("CAPITAL_TOTAL_CONTA", 10400.00))
        vol_anual = float(configs_dict.get("ALVO_VOLATILIDADE_ANUAL", 0.05))
    except (ValueError, TypeError):
        capital, vol_anual = 10400.00, 0.05

    vol_diaria_usd = (capital * vol_anual) / 16.0
    print(f"[CONFIG] Orçamento Diário de Volatilidade: ${vol_diaria_usd:.2f}\n")

    # ===================================================================
    # 4. AUDITAR POSIÇÕES EM CARTEIRA (LÓGICA DINÂMICA DE EMA20 E ATR)
    # ===================================================================
    bloco_posicoes_ativas = ""
    for ticker, info in posicoes_ativas_dict.items():
        status = str(info.get("status", "")).strip().upper()
        if status in ["ATIVA_M10", "ATIVA_SWING"]:
            try:
                df_pos = yf.download(ticker, period="2mo", interval="1d", progress=False)
                if not df_pos.empty:
                    if isinstance(df_pos.columns, pd.MultiIndex):
                        df_pos.columns = df_pos.columns.droplevel(1)
                    
                    df_pos['EMA_20'] = df_pos['Close'].ewm(span=20, adjust=False).mean()
                    df_pos['EMA_50'] = df_pos['Close'].ewm(span=50, adjust=False).mean()
                    df_pos.ta.atr(length=14, append=True)
                    
                    col_atr = [c for c in df_pos.columns if str(c).startswith('ATRr_') or str(c).startswith('ATR_')][0]
                    
                    ultimo_pos = df_pos.iloc[-1]
                    ema20_atual = round(float(ultimo_pos['EMA_20']), 2)
                    ema50_atual = round(float(ultimo_pos['EMA_50']), 2)
                    atr_atual = round(float(ultimo_pos[col_atr]), 2)
                    
                    stop_atual = limpar_float(info.get("stopAtual")) or limpar_float(info.get("stopLoss")) or 0.0
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
                    
                    trailing_sugerido = round(ema20_atual - atr_atual, 2)
                    
                    if alvo_tp > 0 and maxima_efetiva >= alvo_tp:
                        acao = f"🎯 ALVO ALCANÇADO (TP em ${alvo_tp})! Recomendado FECHAR POSIÇÃO com Lucro (WIN)."
                    elif stop_atual > 0 and minima_hoje <= stop_atual:
                        acao = f"🚨 STOP LOSS ATINGIDO (${stop_atual})! Recomendado LIQUIDAR POSIÇÃO (LOSS)."
                    elif preco_atual < ema50_atual:
                        acao = f"⚠️ ALERTA TÉCNICO: Preço (${preco_atual}) abaixo da EMA50 (${ema50_atual}). Deterioração da tendência, considerar fechar."
                    elif trailing_sugerido > stop_atual:
                        acao = f"📈 GESTÃO DINÂMICA: Subir Stop Loss para o novo Trailing baseado na EMA20 (${trailing_sugerido})."
                    else:
                        acao = f"⏳ MANTER POSIÇÃO (Holy Grail). Preço acima da EMA20 (${ema20_atual}) | Stop Atual: ${stop_atual}."
                    
                    bloco_posicoes_ativas += (
                        f"📌 [POSIÇÃO ATIVA - {status}] {ticker} | Qtd: {qtd} | Entrada: ${entrada} | "
                        f"Preço Atual: ${preco_atual} | EMA20: ${ema20_atual} | Trailing Sugerido: ${trailing_sugerido} | "
                        f"AÇÃO: {acao}\n"
                    )
            except Exception as e:
                print(f"[ERRO] Falha ao auditar posição ativa {ticker}: {e}")

    # ===================================================================
    # 5. MOTOR MATEMÁTICO: HOLY GRAIL (PULLBACK À EMA20)
    # ===================================================================
    def analisar_holy_grail(ativo_info):
        try:
            ticker = str(ativo_info.get("ticker", "")).strip().upper()
            nome_empresa = ativo_info.get("nome", "N/A")
            setor = str(ativo_info.get("setor", "Desconhecido")).strip()
            rs_score = ativo_info.get("rs_score", "N/A")

            if not ticker or ticker == "#N/A" or ticker == "NONE": return None
            if ticker in posicoes_ativas_dict: return None 
            if ticker == "BRK-A": ticker = "BRK-B"

            val_rs_num = limpar_float(rs_score)
            if val_rs_num is None or val_rs_num < MIN_RS_SCORE_HOLY_GRAIL:
                return None

            time.sleep(random.uniform(0.8, 1.8))

            alerta_earnings = "OK"
            max_52s = None
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
            for tentativa_yf in range(3):
                try:
                    df = yf.download(ticker, period="1y", interval="1d", progress=False, timeout=15)
                    if not df.empty and len(df) >= 100:
                        break
                except Exception:
                    time.sleep(2)

            if df.empty or len(df) < 100: return None
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
            df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])

            preco = float(df['Close'].iloc[-1])
            if preco < 5.00: return None

            df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
            df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
            df['SMA_200'] = df['Close'].rolling(window=200).mean()
            
            adx_df = df.ta.adx(length=14)
            if adx_df is not None and not adx_df.empty:
                df = pd.concat([df, adx_df], axis=1)
            else:
                return None
                
            df.ta.atr(length=14, append=True)
            df['Vol_SMA_50'] = df['Volume'].rolling(window=50).mean()

            col_adx = [c for c in df.columns if str(c).startswith('ADX_')][0]
            col_atr = [c for c in df.columns if str(c).startswith('ATRr_') or str(c).startswith('ATR_')][0]
            
            df = df.dropna(subset=['EMA_20', 'EMA_50', 'SMA_200', col_adx, col_atr])
            if df.empty: return None

            ultimo = df.iloc[-1]
            ema20 = float(ultimo['EMA_20'])
            ema50 = float(ultimo['EMA_50'])
            sma200 = float(ultimo['SMA_200'])
            adx = float(ultimo[col_adx])
            atr = float(ultimo[col_atr])
            vol_sma50 = float(ultimo['Vol_SMA_50'])
            vol_atual = float(ultimo['Volume'])

            trend_alta = (ema20 > ema50) and (ema50 > sma200) and (adx > 25.0)
            minimo_hoje = float(ultimo['Low'])
            zona_inferior = ema20 * 0.985 
            zona_superior = ema20 * 1.025 
            
            pullback_valido = (minimo_hoje >= zona_inferior) and (minimo_hoje <= zona_superior) and (preco > ema50)
            seca_volume = vol_atual < (vol_sma50 * 0.8)

            if trend_alta and pullback_valido and seca_volume:
                estado = "HOLY GRAIL PULLBACK - Retração à EMA20"
                maximo_hoje = float(ultimo['High'])
                maximo_ontem = float(df['High'].iloc[-2])
                
                entrada_gatilho = round(max(maximo_hoje, maximo_ontem) * 1.002, 2)
                stop_loss = round(min(minimo_hoje * 0.99, ema20 - atr), 2)
                
                risco = entrada_gatilho - stop_loss
                alvo_tp = round(entrada_gatilho + (risco * 2.5), 2) 

                if max_52s and max_52s > 0:
                    if alvo_tp > max_52s:
                        alvo_tp = round(max_52s, 2)
                        
                if alvo_tp <= entrada_gatilho:
                    alvo_tp = round(entrada_gatilho + (risco * 1.5), 2)
                
                if atr > 0:
                    qtd_calc = round(vol_diaria_usd / atr, 2)
                else:
                    qtd_calc = round(vol_diaria_usd / risco, 2) if risco > 0 else 0
                    
                if qtd_calc <= 0: return None

                qtd_acoes = qtd_calc
                val_calc = entrada_gatilho * qtd_acoes
                valor_investir = f"~{val_calc:.2f} USD"
                
                def limpa(v): 
                    try: return round(float(v), 2)
                    except: return "N/A"
                
                linha_comboio = (
                    f"{ticker},Nome: {nome_empresa},Setor: {setor},Preço: {limpa(preco)},"
                    f"RS Score: {rs_score} (🔥 ELITE - Liderança Pura),"
                    f"ADX(14): {limpa(adx)},EMA20: {limpa(ema20)},"
                    f"Gatilho Compra (Buy Stop): {limpa(entrada_gatilho)},"
                    f"Stop Loss: {limpa(stop_loss)},Alvo TP: {limpa(alvo_tp)},"
                    f"Estado: {estado},Qtd: {qtd_acoes},ValorInvestir: {valor_investir},Earnings: {alerta_earnings},"
                    f"Data: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
                )

                return {"ticker": ticker, "comboio_str": linha_comboio}
            return None
        except Exception as e:
            print(f"[ERRO] Falha ao processar ativo {ativo_info.get('ticker')}: {e}")
            return None

    ativos_acionados = []
    total_analisados = 0
    for ativo_info in ativos_sheets:
        ticker = ativo_info.get("ticker")
        if not ticker or ticker == "#N/A": continue
        total_analisados += 1
        res = analisar_holy_grail(ativo_info)
        if res: ativos_acionados.append(res)

    prompt_ia = """MODO ESTRATÉGICO: PULLBACKS DE LIDERANÇA (HOLY GRAIL - LINDA RASCHKE)
O teu mandato é auditar ações de força relativa ELITE (RS >= 80) que sofreram um recuo (pullback) de curto prazo à Média Móvel Exponencial (EMA) de 20 períodos, apresentando seca de volume e tendência principal robusta (ADX forte)."""
    
    bloco = f"📊 RELATÓRIO PULLBACKS DE LIDERANÇA (HOLY GRAIL) 🏆\n\n{prompt_ia}\n\n--------------------------------------------------\n"
    
    if bloco_posicoes_ativas:
        bloco += "GESTÃO DE POSIÇÕES ATIVAS (ATIVA_M10 / ATIVA_SWING):\n\n"
        bloco += bloco_posicoes_ativas
        bloco += "--------------------------------------------------\n\n"

    if not ativos_acionados:
        bloco += "[SEM SINAIS PULLBACK] - Nenhum ativo de Elite encontra-se num ponto ótimo de retração à EMA20 hoje.\n"
    else:
        bloco += "ALVOS DE COMPRA EM PULLBACK:\n\n"
        for item in ativos_acionados:
            bloco += item["comboio_str"] + "\n"
            
    with open("comboio_holygrail_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco)
        
    enviar_email(bloco)

    # ===================================================================
    # 6. NOTIFICAÇÃO TELEGRAM DEBUG (CONTROLADA PELA FLAG DE CONFIGS)
    # ===================================================================
    debug_telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

    if debug_telegram_ativado:
        print("A enviar notificação de Debug para o Telegram via função modular...")
        total_acionados = len(ativos_acionados)
        mensagem_debug = (
            f"10 🏆 *MOTOR HOLY GRAIL (PULLBACKS)*\n\n"
            f"🔍 [DEBUG] Execução concluída com sucesso.\n"
            f"📊 Ativos analisados: *{total_analisados}* | Acionados: *{total_acionados}*\n"
            f"✉️ Relatório e auditoria enviados por e-mail."
        )
        enviar_alerta(mensagem_debug)

if __name__ == "__main__":
    executar_motor()
