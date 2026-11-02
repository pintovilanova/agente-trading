# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR 17: 2-DAY RSI DROP & REBOUND (HIT & RUN)
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
    print("[INFO] Fim de semana detetado. O Motor 17 vai descansar.")
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

def enviar_email(assunto, conteudo):
    print(f"\nA enviar e-mail ('{assunto}')...")
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] EMAIL_USER ou EMAIL_PASS não configurados. E-mail não enviado.")
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
        print("[SUCESSO] Email enviado com sucesso!")
        return True
    except Exception as e:
        print(f"[ERRO EMAIL] Falha ao enviar e-mail: {e}")
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
# 4. AUDITAR POSIÇÕES EM CARTEIRA (ESTRITO: ATIVA_M17 - PRE-MARKET FORÇADO & EMA5)
# ===================================================================
bloco_posicoes_ativas = ""

def obter_preco_realtime_premarket(ticker):
    """
    Usa o motor intraday do yfinance para descarregar o gráfico de 1 minuto 
    com a flag prepost=True. Apanha a última transação de Pre-Market/After-Hours.
    """
    try:
        # period="5d" garante que apanha a sessão atual mesmo após fim de semana
        df_rt = yf.download(ticker, period="5d", interval="1m", prepost=True, progress=False)
        if not df_rt.empty:
            if isinstance(df_rt.columns, pd.MultiIndex):
                df_rt.columns = df_rt.columns.get_level_values(0)
            
            ultimo_preco_premarket = float(df_rt['Close'].dropna().iloc[-1])
            if ultimo_preco_premarket > 0:
                return round(ultimo_preco_premarket, 2)
    except Exception as e:
        print(f"[AVISO] Falha ao extrair intraday pre-market para {ticker}: {e}")
        
    # Fallback via fast_info
    try:
        t = yf.Ticker(ticker)
        fast = t.fast_info
        p_pre = getattr(fast, 'pre_market_price', None)
        p_last = getattr(fast, 'last_price', None)
        
        if p_pre and not np.isnan(p_pre) and p_pre > 0:
            return round(float(p_pre), 2)
        elif p_last and not np.isnan(p_last) and p_last > 0:
            return round(float(p_last), 2)
    except Exception:
        pass
        
    return 0.0

def obter_dados_posicao_m17(ticker):
    """Obtém o preço em tempo real (Pre-Market forçado) e calcula a EMA5 diária"""
    preco_atual = 0.0
    ema5_atual = 0.0
    
    # 1. CAMADA BASE DIÁRIA: Garante o cálculo da EMA5
    try:
        df_pos = yf.download(ticker, period="1mo", interval="1d", progress=False)
        if not df_pos.empty:
            if isinstance(df_pos.columns, pd.MultiIndex):
                df_pos.columns = df_pos.columns.droplevel(1)
            
            df_pos = df_pos.dropna(subset=['Close'])
            if len(df_pos) >= 5:
                df_pos['EMA5'] = df_pos['Close'].ewm(span=5, adjust=False).mean()
                ema5_atual = round(float(df_pos['EMA5'].iloc[-1]), 2)
                preco_atual = round(float(df_pos['Close'].iloc[-1]), 2)
    except Exception as e:
        print(f"[AVISO] Falha ao obter dados diários para {ticker}: {e}")

    # 2. CAMADA PRE-MARKET FORÇADA
    preco_realtime = obter_preco_realtime_premarket(ticker)
    if preco_realtime > 0:
        preco_atual = preco_realtime

    return preco_atual, ema5_atual

for chave_pos, info in posicoes_ativas_dict.items():
    if not isinstance(info, dict): continue
    status = str(info.get("status", "")).strip().upper()
    
    if status == "ATIVA_M17":
        try:
            ticker = "AI" if chave_pos.lower() in ["c3.ai", "c3"] else chave_pos.strip().upper()
            
            # Obtém cotação (com Pre-Market forçado) e EMA5
            preco_atual, ema5_dinamica = obter_dados_posicao_m17(ticker)
            
            stop = limpar_float(info.get("stopAtual")) or limpar_float(info.get("stopLoss")) or 0.0
            entrada = limpar_float(info.get("precoEntrada")) or preco_atual
            
            # Leitura do TP fixo do Sheets ou fallback para EMA5
            tp_sheets = (
                limpar_float(info.get("alvoTp")) or 
                limpar_float(info.get("takeProfit")) or 
                limpar_float(info.get("alvo_tp")) or 
                0.0
            )
            
            alvo_efetivo = tp_sheets if tp_sheets > 0 else ema5_dinamica
            label_alvo = f"${alvo_efetivo}" if tp_sheets > 0 else f"${alvo_efetivo} (EMA5)"
            qtd = info.get("quantidade", "N/A")
            
            if preco_atual == 0.0:
                preco_atual = entrada

            if alvo_efetivo > 0 and preco_atual >= alvo_efetivo:
                acao = f"🎯 ALVO ALCANÇADO ({label_alvo})! Recomendado FECHAR POSIÇÃO com Lucro (WIN)."
            elif stop > 0 and preco_atual <= stop:
                acao = f"🚨 STOP LOSS ATINGIDO (${stop})! Recomendado LIQUIDAR POSIÇÃO (LOSS)."
            else:
                acao = f"⏳ MANTER POSIÇÃO (RSI Rebound). Alvo: {label_alvo} | Stop: ${stop}."
            
            bloco_posicoes_ativas += (
                f"📌 [{status}] {ticker} ({chave_pos}) | Qtd: {qtd} | Entrada: ${entrada} | "
                f"Atual: ${preco_atual} | {acao}\n"
            )
        except Exception as e:
            print(f"[ERRO] Falha ao auditar posição ativa {chave_pos}: {e}")

# ===================================================================
# 5. MOTOR MATEMÁTICO: 2-DAY RSI DROP & REBOUND
# ===================================================================
def analisar_rsi_drop(ativo_info):
    try:
        ticker = str(ativo_info.get("ticker", "")).strip().upper()
        if not ticker or ticker == "#N/A" or ticker == "NONE": return None
        if ticker in posicoes_ativas_dict: return None
        if ticker == "BRK-A": ticker = "BRK-B"

        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if df.empty or len(df) < 200: return None
        
        # Achatar MultiIndex se existir
        if isinstance(df.columns, pd.MultiIndex): 
            df.columns = df.columns.droplevel(1)
            
        df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])
        if len(df) < 200: return None

        # Cálculo dos Indicadores
        df.ta.rsi(length=2, append=True)
        df.ta.sma(length=200, append=True)
        df.ta.atr(length=14, append=True)

        # Mapeamento Seguro de Colunas
        cols_rsi = [c for c in df.columns if str(c).startswith('RSI_2')]
        cols_sma = [c for c in df.columns if str(c).startswith('SMA_200')]
        cols_atr = [c for c in df.columns if str(c).startswith('ATRr_') or str(c).startswith('ATR_') or str(c).startswith('ATRe_')]

        if not cols_rsi or not cols_sma or not cols_atr:
            return None

        col_rsi = cols_rsi[0]
        col_sma = cols_sma[0]
        col_atr = cols_atr[0]

        df = df.dropna(subset=[col_rsi, col_sma, col_atr])
        if df.empty: return None

        ultimo = df.iloc[-1]
        preco = float(ultimo['Close'])
        rsi2 = float(ultimo[col_rsi])
        sma200 = float(ultimo[col_sma])
        atr = float(ultimo[col_atr])

        # CONDIÇÕES: Preço acima da SMA200 (Tendência de Alta) E RSI(2) <= 10 (Sobrevendido Extremo)
        if preco > sma200 and rsi2 <= 10.0:
            entrada_gatilho = round(preco, 2)
            stop_loss = round(entrada_gatilho - (atr * 1.5), 2)
            risco = entrada_gatilho - stop_loss
            alvo_tp = round(entrada_gatilho + (risco * 2.0), 2)

            qtd_calc = round(vol_diaria_usd / risco, 2) if risco > 0 else 0.0
            val_calc = entrada_gatilho * qtd_calc

            return {
                "ticker": ticker,
                "preco_atual": round(preco, 2),
                "rsi2": round(rsi2, 2),
                "gatilho": entrada_gatilho,
                "stop_loss": stop_loss,
                "alvo_tp": alvo_tp,
                "qtd_acoes": qtd_calc,
                "valor_investir": round(val_calc, 2)
            }
        return None
    except Exception as e:
        print(f"[ERRO] Falha ao analisar RSI Drop em {ativo_info.get('ticker')}: {e}")
        return None

# ===================================================================
# 6. EXECUÇÃO PRINCIPAL E RELATÓRIO
# ===================================================================
def executar_motor():
    alertas_rsi = []
    total_analisados = 0

    if ativos_sheets:
        for ativo_info in ativos_sheets:
            ticker = ativo_info.get("ticker")
            if not ticker or ticker == "#N/A": continue
            total_analisados += 1
            res = analisar_rsi_drop(ativo_info)
            if res: alertas_rsi.append(res)

    data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M")
    
    bloco_texto = (
        f"⚡ RELATÓRIO DETALHADO - MOTOR 17: 2-DAY RSI DROP & REBOUND ({data_hoje})\n"
        f"==================================================================\n\n"
    )

    if bloco_posicoes_ativas:
        bloco_texto += f"📌 GESTÃO DE POSIÇÕES ATIVAS:\n{bloco_posicoes_ativas}\n--------------------------------------------------\n\n"
    else:
        bloco_texto += "📌 GESTÃO DE POSIÇÕES ATIVAS: Nenhuma posição ativa detetada para este motor.\n--------------------------------------------------\n\n"

    if alertas_rsi:
        bloco_texto += f"🎯 SINAIS DE REVERSÃO À MÉDIA DETETADOS ({len(alertas_rsi)}):\n\n"
        for a in alertas_rsi:
            info_ativo = next((item for item in ativos_sheets if str(item.get("ticker","")).strip().upper() == a['ticker']), {})
            nome_empresa = info_ativo.get("nome") or "N/A"
            setor = info_ativo.get("setor") or "N/A"
            rs_score = info_ativo.get("rs_score", "N/A")

            bloco_texto += (
                f"🔹 [{a['ticker']}] - {nome_empresa} ({setor})\n"
                f"    - 📊 Contexto Técnico: RSI(2) em {a['rsi2']} (Sobrevendido Extremo sobre SMA200)\n"
                f"    - ⚙️ Tática: Reversão à Média Expressa (Hit & Run 48h-72h)\n"
                f"    - 📋 Tipo de Ordem: MARKET / LIMIT no fecho/abertura\n"
                f"    - 🔢 Dados Exatos: Entrada: ${a['gatilho']} | Stop Loss: ${a['stop_loss']} | Alvo TP: ${a['alvo_tp']}\n"
                f"    - 💰 Dimensionamento: Qtd: {a['qtd_acoes']} | Valor a Investir: ~${a['valor_investir']} USD\n"
                f"    - 📈 RS Score Institucional: {rs_score}\n"
                f"--------------------------------------------------\n"
            )
    else:
        bloco_texto += "✅ Nenhum novo sinal de RSI Drop detetado hoje.\n"

    # GRAVAÇÃO DO FICHEIRO TEMPORÁRIO
    with open("comboio_rsi_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco_texto)

    # ENVIO DE E-MAIL COM ÍCONES PADRONIZADOS
    assunto_email = f"⚡🎯 tradingRelatorioIA US - MOTOR 17 RSI DROP ({datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')})"
    enviar_email(assunto_email, bloco_texto)

    # 📌 NOTIFICAÇÃO TELEGRAM
    debug_telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

    if debug_telegram_ativado or len(alertas_rsi) > 0:
        print("A enviar notificação para o Telegram via função modular...")
        total_acionados = len(alertas_rsi)
        mensagem_telegram = (
            f"17 ⚡ *MOTOR 17 (RSI DROP & REBOUND)*\n\n"
            f"🔍 [STATUS] Execução concluída com sucesso.\n"
            f"📊 Ativos analisados: *{total_analisados}* | Acionados: *{total_acionados}*\n"
            f"✉️ Relatório de reversão à média gerado e enviado por e-mail."
        )
        enviar_alerta(mensagem_telegram)

if __name__ == "__main__":
    executar_motor()
