# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR 19: VOLATILITY SQUEEZE BREAKOUT
# ===================================================================================
# Descrição Geral:
# Identifica ativos líderes (RS >= 70) em consolidação apertada (Squeeze entre Bandas
# de Bollinger e Canais de Keltner) prontos para rompimento de curto prazo
# (Hit and Run | Alvo 1.5R | Time-Stop 72h), auditando as posições ATIVA_M19.
# ===================================================================================

import pandas as pd
import yfinance as yf
import pandas_ta as ta
import numpy as np
from datetime import datetime, timedelta
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
    print("[INFO] Fim de semana detetado. O Motor Squeeze Breakout vai descansar.")
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

def parse_data_abertura(data_abertura_str):
    if not data_abertura_str:
        return None
    formatos = ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")
    for fmt in formatos:
        try:
            return datetime.strptime(str(data_abertura_str).strip(), fmt).replace(tzinfo=ZoneInfo("Europe/Lisbon"))
        except ValueError:
            continue
    return None

def calcular_dias_uteis(data_abertura_str):
    """Calcula quantos dias úteis (seg-sex) passaram desde a data na Coluna A."""
    dt_inicio = parse_data_abertura(data_abertura_str)
    if dt_inicio is None:
        return None
    dt_agora = datetime.now(ZoneInfo("Europe/Lisbon"))
    dias_uteis = 0
    cursor = dt_inicio
    while cursor.date() < dt_agora.date():
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            dias_uteis += 1
    return dias_uteis

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
                print("[ERRO] O Webhook não retornou um JSON válido.")
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

def verificar_regime_mercado():
    """Bloqueia novas entradas de squeeze breakout se o SPY estiver abaixo da SMA200 ou em queda."""
    try:
        df_spy = yf.download("SPY", period="1y", interval="1d", progress=False, session=session)
        if df_spy.empty or len(df_spy) < 200:
            return True, "Dados SPY insuficientes (autorizado por defeito)."
        if isinstance(df_spy.columns, pd.MultiIndex):
            df_spy.columns = df_spy.columns.droplevel(1)
        
        close_hoje = float(df_spy['Close'].iloc[-1])
        close_ontem = float(df_spy['Close'].iloc[-2])
        sma200 = float(df_spy['Close'].rolling(200).mean().iloc[-1])
        ema20 = float(df_spy['Close'].ewm(span=20, adjust=False).mean().iloc[-1])
        var_dia = ((close_hoje - close_ontem) / close_ontem) * 100

        if close_hoje < sma200:
            return False, f"SPY (${close_hoje:.2f}) abaixo da SMA200 (${sma200:.2f}). Mercado em regime baixista."
        if close_hoje < ema20 and var_dia <= -0.5:
            return False, f"SPY (${close_hoje:.2f}) abaixo da EMA20 (${ema20:.2f}) com pressão vendedora ({var_dia:+.2f}%)."
        if var_dia <= -1.0:
            return False, f"SPY em queda forte hoje ({var_dia:.2f}% <= -1.00%)."
        return True, f"SPY favorável (${close_hoje:.2f} > SMA200 | EMA20: ${ema20:.2f} | Var: {var_dia:+.2f}%)."
    except Exception as e:
        return True, f"Aviso SPY: {e}"

def enviar_email(conteudo):
    print("\nA enviar relatório detalhado do Motor 19 por e-mail...")
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] EMAIL_USER ou EMAIL_PASS não definidos.")
        return False

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = f"⚡ tradingRelatorioIA US - MOTOR 19 SQUEEZE BREAKOUT ({datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')})"
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

def obter_setor_yf(ticker):
    """Fallback para obter o setor diretamente do yfinance caso falhe no Sheets"""
    try:
        t = yf.Ticker(ticker, session=session)
        setor = t.info.get('sector')
        return setor if setor else "Desconhecido"
    except Exception:
        return "Desconhecido"

# ===================================================================
# 3. CARGA DE DADOS E PARAMETRIZAÇÃO DE RISCO (LIDA DO NOVO CONFIGS)
# ===================================================================
ativos_sheets, posicoes_ativas_dict, configs_dict = buscar_dados_completos()

capital = limpar_float(configs_dict.get("CAPITAL_TOTAL_CONTA")) or 10400.00
pct_risco = (
    limpar_float(configs_dict.get("RISCO_POR_TRADE")) or 
    limpar_float(configs_dict.get("RISCO_SWING_PCT")) or 
    0.0025
)
risco_fixo_usd = limpar_float(configs_dict.get("RISCO_MAXIMO_USD"))

vol_diaria_usd = risco_fixo_usd if (risco_fixo_usd and risco_fixo_usd > 0) else (capital * pct_risco)
print(f"[CONFIG] Capital Total: ${capital:,.2f} | Orçamento Risco/Trade: ${vol_diaria_usd:,.2f} USD\n")

# ===================================================================
# 4. AUDITAR POSIÇÕES EM CARTEIRA (ALVO 1.5R + BE +0.8R + TIME-STOP 72H)
# ===================================================================
bloco_posicoes_ativas = ""
alerta_timestop_ativo = False

def obter_dados_posicao_m19(ticker, dt_abertura=None):
    preco_atual = 0.0
    atr_atual = 0.0
    maxima_desde_abertura = 0.0

    try:
        df_pos = yf.download(ticker, period="1mo", interval="1d", progress=False, session=session)
        if not df_pos.empty:
            if isinstance(df_pos.columns, pd.MultiIndex):
                df_pos.columns = df_pos.columns.droplevel(1)
            df_pos = df_pos.dropna(subset=['Close', 'High', 'Low'])
            if len(df_pos) >= 14:
                df_pos.ta.atr(length=14, append=True)
                cols_atr = [c for c in df_pos.columns if str(c).startswith('ATRr_') or str(c).startswith('ATR_') or str(c).startswith('ATRe_')]
                if cols_atr:
                    atr_atual = round(float(df_pos[cols_atr[0]].iloc[-1]), 2)
                preco_atual = round(float(df_pos['Close'].iloc[-1]), 2)
    except Exception as e:
        print(f"[AVISO] Falha ao obter dados diários para {ticker}: {e}")

    try:
        df_intra = yf.download(ticker, period="5d", interval="1m", prepost=True, progress=False, session=session)
        if not df_intra.empty:
            if isinstance(df_intra.columns, pd.MultiIndex):
                df_intra.columns = df_intra.columns.get_level_values(0)
            df_intra = df_intra.dropna(subset=['Close', 'High'])
            if not df_intra.empty:
                ultimo_rt = float(df_intra['Close'].iloc[-1])
                if ultimo_rt > 0:
                    preco_atual = round(ultimo_rt, 2)
                if dt_abertura is not None:
                    idx_lisbon = df_intra.index.tz_convert("Europe/Lisbon") if df_intra.index.tzinfo else df_intra.index.tz_localize("UTC").tz_convert("Europe/Lisbon")
                    df_pos_abertura = df_intra[idx_lisbon >= dt_abertura]
                    if not df_pos_abertura.empty:
                        maxima_desde_abertura = round(float(df_pos_abertura['Close'].max()), 2)
    except Exception as e:
        print(f"[AVISO] Falha ao extrair intraday para {ticker}: {e}")

    if preco_atual <= 0:
        try:
            t = yf.Ticker(ticker, session=session)
            fast = t.fast_info
            p_pre = getattr(fast, 'pre_market_price', None)
            p_last = getattr(fast, 'last_price', None)
            if p_pre and not np.isnan(p_pre) and p_pre > 0:
                preco_atual = round(float(p_pre), 2)
            elif p_last and not np.isnan(p_last) and p_last > 0:
                preco_atual = round(float(p_last), 2)
        except Exception:
            pass

    maxima_efetiva = max(maxima_desde_abertura, preco_atual)
    return preco_atual, atr_atual, maxima_efetiva

for chave_pos, info in posicoes_ativas_dict.items():
    if not isinstance(info, dict): continue
    status = str(info.get("status", "")).strip().upper()
    
    if status == "ATIVA_M19":
        try:
            ticker = "AI" if chave_pos.lower() in ["c3.ai", "c3"] else chave_pos.strip().upper()
            
            data_abertura = info.get("dataAbertura", "")
            dt_abertura = parse_data_abertura(data_abertura)
            dias_uteis = calcular_dias_uteis(data_abertura)
            tag_tempo = f" | {dias_uteis}d úteis" if dias_uteis is not None else ""
            
            preco_atual, atr_calc, maxima_efetiva = obter_dados_posicao_m19(ticker, dt_abertura)
            
            stop = limpar_float(info.get("stopAtual")) or limpar_float(info.get("stopLoss")) or 0.0
            entrada = limpar_float(info.get("precoEntrada")) or preco_atual
            
            if preco_atual == 0.0:
                preco_atual = entrada
                maxima_efetiva = entrada

            if stop <= 0 and atr_calc > 0 and entrada > 0:
                stop = round(entrada - (atr_calc * 1.5), 2)
            
            risco_inicial = entrada - stop if entrada > stop else (atr_calc * 1.5 if atr_calc > 0 else 0.0)
            
            tp_sheets = (
                limpar_float(info.get("alvoTp")) or 
                limpar_float(info.get("takeProfit")) or 
                limpar_float(info.get("alvo_tp")) or 
                0.0
            )
            
            if tp_sheets > (entrada * 1.005):
                alvo_tp = tp_sheets
                label_alvo = f"${alvo_tp}"
            elif risco_inicial > 0:
                alvo_tp = round(entrada + (risco_inicial * 1.5), 2)
                label_alvo = f"${alvo_tp} (TP 1.5R)"
            else:
                alvo_tp = 0.0
                label_alvo = "N/A"
                
            qtd = info.get("quantidade", "N/A")
            
            # Proteção Break-Even aos +0.8R
            sugestao_stop = stop
            if risco_inicial > 0 and maxima_efetiva >= (entrada + (risco_inicial * 0.8)) and preco_atual > entrada:
                be_calculado = round(entrada * 1.0005, 2)
                if be_calculado > stop:
                    sugestao_stop = be_calculado
            
            if alvo_tp > 0 and preco_atual >= alvo_tp:
                acao = f"🎯 ALVO ALCANÇADO ({label_alvo})! Recomendado FECHAR POSIÇÃO com Lucro (WIN)."
            elif stop > 0 and preco_atual <= stop:
                acao = f"🚨 STOP LOSS ATINGIDO (${stop})! Recomendado LIQUIDAR POSIÇÃO (LOSS)."
            elif dias_uteis is not None and dias_uteis >= 3:
                alerta_timestop_ativo = True
                acao = (
                    f"⏰ TIME-STOP ATINGIDO ({dias_uteis}d úteis > 72h)! Setup Squeeze Breakout expirado — "
                    f"Recomendado FECHAR A MERCADO (${preco_atual}) antes de varrer o Stop (${stop})."
                )
            elif dias_uteis == 2:
                if sugestao_stop > stop and preco_atual > entrada:
                    acao = f"⚠️ ÚLTIMO DIA (48h) + 🛡️ +0.8R! Sobe Stop p/ BE: ${sugestao_stop} | Fechar no fecho se não tocar {label_alvo}."
                else:
                    acao = f"⚠️ ÚLTIMO DIA DA JANELA (48h). Se não arrancar hoje rumo a {label_alvo}, preparar saída no fecho | Stop: ${stop}."
            elif sugestao_stop > stop and preco_atual > entrada:
                acao = f"🛡️ PROTEGER POSIÇÃO{tag_tempo}. +0.8R Atingido! Sobe o Stop para Break-Even: ${sugestao_stop} | Alvo: {label_alvo}."
            else:
                acao = f"⏳ MANTER POSIÇÃO (Squeeze Breakout{tag_tempo}). Alvo: {label_alvo} | Stop: ${stop}."
            
            bloco_posicoes_ativas += (
                f"📌 [{status}] {ticker} ({chave_pos}) | Qtd: {qtd} | Entrada: ${entrada} | "
                f"Atual: ${preco_atual} | {acao}\n"
            )
        except Exception as e:
            print(f"[ERRO] Falha ao auditar posição ativa {chave_pos}: {e}")

# ===================================================================
# 5. MOTOR MATEMÁTICO: VOLATILITY SQUEEZE (RS >= 70 | ALVO 1.5R)
# ===================================================================
def analisar_squeeze(ativo_info):
    try:
        # FILTRO DE FORÇA RELATIVA (RS SCORE MÍNIMO >= 70)
        rs_score = limpar_float(ativo_info.get("rs_score")) or 0.0
        if rs_score < 70.0:
            return None

        ticker = str(ativo_info.get("ticker", "")).strip().upper()
        if not ticker or ticker == "#N/A" or ticker == "NONE": return None
        if ticker in posicoes_ativas_dict: return None
        if ticker == "BRK-A": ticker = "BRK-B"

        time.sleep(random.uniform(0.5, 1.2))

        df = pd.DataFrame()
        for _ in range(3):
            try:
                df = yf.download(ticker, period="1y", interval="1d", progress=False, timeout=15, session=session)
                if not df.empty and len(df) >= 200:
                    break
            except Exception:
                time.sleep(2)

        if df.empty or len(df) < 200: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
        df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])

        preco = float(df['Close'].iloc[-1])
        if preco < 10.00: return None

        # 1. Bollinger Bands (SMA 20, Desvio Padrão 2.0)
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        df['STD_20'] = df['Close'].rolling(window=20).std()
        df['BB_Upper'] = df['SMA_20'] + (df['STD_20'] * 2.0)
        df['BB_Lower'] = df['SMA_20'] - (df['STD_20'] * 2.0)

        # 2. Keltner Channels (EMA 20, ATR(20) com suavização RMA) e Tendência Primária
        df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        df.ta.atr(length=20, mamode="rma", append=True)
        
        col_atr = [c for c in df.columns if str(c).startswith('ATRr_') or str(c).startswith('ATR_')][0]
        
        df['KC_Upper'] = df['EMA_20'] + (df[col_atr] * 1.5)
        df['KC_Lower'] = df['EMA_20'] - (df[col_atr] * 1.5)

        df = df.dropna(subset=['BB_Upper', 'BB_Lower', 'KC_Upper', 'KC_Lower', 'SMA_200', col_atr])
        if df.empty: return None

        # 3. Registo histórico de Squeeze (BB dentro dos KC) e Filtro de Squeeze Recente (últimos 5 dias)
        df['Squeeze_On'] = (df['BB_Upper'] <= df['KC_Upper']) & (df['BB_Lower'] >= df['KC_Lower'])
        df['Squeeze_Recente'] = df['Squeeze_On'].rolling(window=5).sum() > 0

        ultimo = df.iloc[-1]
        kc_upper = float(ultimo['KC_Upper'])
        ema20 = float(ultimo['EMA_20'])
        sma200 = float(ultimo['SMA_200'])
        atr = float(ultimo[col_atr])
        maximo_hoje = float(ultimo['High'])
        minimo_hoje = float(ultimo['Low'])

        # Exige estrutura de tendência ascendente (Preço > EMA20 > SMA200)
        if not (preco > ema20 and ema20 > sma200):
            return None

        squeeze_on = bool(ultimo['Squeeze_On'])
        
        breakout_alta = (
            (preco > kc_upper) and 
            (float(df['Close'].iloc[-2]) <= float(df['KC_Upper'].iloc[-2])) and 
            bool(ultimo['Squeeze_Recente'])
        )

        # Filtro de exaustão: descarta se já esticou > 1 ATR acima do Keltner
        limite_exaustao = kc_upper + (atr * 1.0)
        if breakout_alta and preco > limite_exaustao:
            breakout_alta = False
            squeeze_on = False

        if breakout_alta or squeeze_on:
            entrada_gatilho = round(maximo_hoje * 1.002, 2)
            stop_loss = round(min(minimo_hoje * 0.995, entrada_gatilho - (atr * 1.5)), 2)
            
            risco = entrada_gatilho - stop_loss
            if risco <= 0:
                return None

            # Alvo realista Hit & Run M19: 1.5R
            alvo_tp = round(entrada_gatilho + (risco * 1.5), 2)

            qtd_calc = round(vol_diaria_usd / risco, 2)
            val_calc = entrada_gatilho * qtd_calc

            return {
                "ticker": ticker,
                "preco_atual": round(preco, 2),
                "gatilho": entrada_gatilho,
                "stop_loss": stop_loss,
                "alvo_tp": alvo_tp,
                "qtd_acoes": qtd_calc,
                "valor_investir": round(val_calc, 2),
                "estado_squeeze": "A ATIVAR (Breakout Detetado)" if breakout_alta else "EM COMPRESSÃO EXTREMA",
                "rs_score": rs_score
            }
        return None
    except Exception as e:
        print(f"[ERRO] Falha ao processar ativo {ativo_info.get('ticker')}: {e}")
        return None

# ===================================================================
# 6. EXECUÇÃO PRINCIPAL E RELATÓRIO DETALHADO
# ===================================================================
def executar_motor():
    alertas_squeeze = []
    total_analisados = 0
    
    mercado_ok, msg_mercado = verificar_regime_mercado()

    if mercado_ok and ativos_sheets:
        for ativo_info in ativos_sheets:
            ticker = ativo_info.get("ticker")
            if not ticker or ticker == "#N/A": continue
            
            total_analisados += 1
            res = analisar_squeeze(ativo_info)
            if res: alertas_squeeze.append(res)

    data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M")
    
    bloco_texto = (
        f"⚡ RELATÓRIO DETALHADO - MOTOR 19: VOLATILITY SQUEEZE BREAKOUT ({data_hoje})\n"
        f"==================================================================\n"
        f"🌐 Filtro Macro: {msg_mercado}\n"
        f"💰 Risco Configurado por Trade: ${vol_diaria_usd:,.2f} USD\n\n"
    )

    if bloco_posicoes_ativas:
        bloco_texto += f"📌 GESTÃO DE POSIÇÕES ATIVAS:\n{bloco_posicoes_ativas}\n--------------------------------------------------\n\n"
    else:
        bloco_texto += "📌 GESTÃO DE POSIÇÕES ATIVAS: Nenhuma posição ativa detetada para este motor.\n--------------------------------------------------\n\n"

    if not mercado_ok:
        bloco_texto += f"🛡️ [MODO DEFENSIVO] Novas entradas bloqueadas hoje ({msg_mercado}).\n"
    elif alertas_squeeze:
        bloco_texto += f"🎯 NOVOS SINAIS DE EXPANSÃO DE VOLATILIDADE ({len(alertas_squeeze)}):\n\n"
        for a in alertas_squeeze:
            info_ativo = next((item for item in ativos_sheets if str(item.get("ticker","")).strip().upper() == a['ticker']), {})
            
            nome_empresa = info_ativo.get("nome") or info_ativo.get("nomeEmpresa") or info_ativo.get("name") or "N/A"
            
            setor = (
                info_ativo.get("setor") or 
                info_ativo.get("setorAtivo") or 
                info_ativo.get("sector") or 
                info_ativo.get("Setor")
            )
            
            if not setor or str(setor).strip().lower() in ["desconhecido", "n/a", "none", "#n/a", ""]:
                setor = obter_setor_yf(a['ticker'])

            bloco_texto += (
                f"🔹 [{a['ticker']}] - {nome_empresa} ({setor})\n"
                f"   - 📊 Contexto Técnico: {a['estado_squeeze']} (BB dentro de KC | EMA20 > SMA200)\n"
                f"   - ⚙️ Tática: Breakout Explosivo de Curto Prazo (Alvo 1.5R | Time-Stop 72h)\n"
                f"   - 📋 Tipo de Ordem: BUY STOP (Gatilho na quebra da máxima diária)\n"
                f"   - 🔢 Dados Exatos: Gatilho Compra: ${a['gatilho']} | Stop Loss: ${a['stop_loss']} | Alvo (1.5R): ${a['alvo_tp']}\n"
                f"   - 💰 Dimensionamento: Qtd: {a['qtd_acoes']} | Valor a Investir: ~${a['valor_investir']} USD\n"
                f"   - 📈 RS Score Institucional: {a['rs_score']}\n"
                f"--------------------------------------------------\n"
            )
    else:
        bloco_texto += "✅ Nenhum novo sinal de Squeeze / Breakout detetado hoje.\n"

    enviar_email(bloco_texto)

    with open("comboio_squeeze_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco_texto)

    # ===================================================================
    # 7. NOTIFICAÇÃO TELEGRAM (DEBUG OU ALERTA TIME-STOP)
    # ===================================================================
    debug_telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

    if debug_telegram_ativado or len(alertas_squeeze) > 0 or alerta_timestop_ativo:
        print("A enviar notificação para o Telegram via função modular...")
        total_acionados = len(alertas_squeeze)
        aviso_ts = "\n⏰ *ALERTA TIME-STOP:* Tens posição(ões) M19 expirada(s) (>72h) para fechar!" if alerta_timestop_ativo else ""
        mensagem_debug = (
            f"19 ⚡ *MOTOR 19 (SQUEEZE BREAKOUT)*\n\n"
            f"🔍 [STATUS] Execução concluída com sucesso.\n"
            f"📊 Analisados: *{total_analisados}* | Acionados: *{total_acionados}*{aviso_ts}\n"
            f"💰 Risco/Trade: *${vol_diaria_usd:.2f}*\n"
            f"✉️ Relatório de expansão de volatilidade gerado e enviado por e-mail."
        )
        enviar_alerta(mensagem_debug)

if __name__ == "__main__":
    executar_motor()
