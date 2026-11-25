# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR 20: PULLBACK À EMA 20
# ===================================================================================
# Descrição Geral:
# Identifica ativos líderes com tendência primária alinhada (EMA 20 > SMA 50 > SMA 200)
# que realizam um pullback de defesa na zona da EMA 20.
# Adapta-se ao regime do SPY:
#   - Expansão (SPY > EMA20): Alvo 1.75R | RS >= 65 | Lote 100% (60% se VIX > 25)
#   - Corretivo (SMA200 < SPY <= EMA20): Alvo 1.25R | RS >= 75 | Lote 60% (40% se VIX > 25)
#   - Baixista Seletivo (SPY < SMA200 e VIX <= 32): Alvo 1.25R | RS >= 85 | Lote 35%
#   - Queda <= -2.50% / VIX > 32: Bloqueia novas entradas
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
import traceback
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
    print("[INFO] Fim de semana detetado. O Motor Pullback EMA 20 vai descansar.")
    # sys.exit(0)

# ===================================================================
# 1. CONFIGURAÇÕES E CREDENCIAIS
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")

if EMAIL_USER:
    EMAIL_USER = EMAIL_USER.strip()
if EMAIL_PASS:
    EMAIL_PASS = EMAIL_PASS.strip()

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
        resp = requests.get(url_alvo, timeout=20)
        
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
    """
    Avalia o regime do SPY e devolve parâmetros adaptativos equilibrados para Pullbacks à EMA 20:
    - Expansão (SPY > EMA20): TP 1.75R | RS >= 65 | Fator Lote 1.0 (ou 0.60 se VIX > 25)
    - Corretivo/Lateral (SMA200 < SPY <= EMA20): TP 1.25R | RS >= 75 | Fator Lote 0.60 (ou 0.40 se VIX > 25)
    - Baixista Seletivo (SPY < SMA200 e VIX <= 32): TP 1.25R | RS >= 85 | Fator Lote 0.35
    - Crash <= -2.50% / VIX > 32: Bloqueia novas entradas
    """
    regime_default = {
        "autorizado": True,
        "modo": "EXPANSAO",
        "tp_mult": 1.75,
        "rs_min": 65.0,
        "fator_risco": 1.0,
        "msg": "Dados SPY insuficientes (autorizado por defeito em modo Expansão)."
    }
    try:
        df_spy = yf.download("SPY", period="1y", interval="1d", progress=False, session=session)
        if df_spy.empty or len(df_spy) < 200:
            return regime_default
        if isinstance(df_spy.columns, pd.MultiIndex):
            df_spy.columns = df_spy.columns.droplevel(1)
        
        close_hoje = float(df_spy['Close'].iloc[-1])
        close_ontem = float(df_spy['Close'].iloc[-2])
        sma200 = float(df_spy['Close'].rolling(200).mean().iloc[-1])
        ema20 = float(df_spy['Close'].ewm(span=20, adjust=False).mean().iloc[-1])
        var_dia = ((close_hoje - close_ontem) / close_ontem) * 100

        vix_atual = None
        try:
            df_vix = yf.download("^VIX", period="5d", interval="1d", progress=False, session=session)
            if not df_vix.empty:
                if isinstance(df_vix.columns, pd.MultiIndex):
                    df_vix.columns = df_vix.columns.droplevel(1)
                vix_atual = float(df_vix['Close'].iloc[-1])
        except Exception:
            pass

        tag_vix = f" | VIX: {vix_atual:.2f}" if vix_atual is not None else ""

        if var_dia <= -2.5:
            return {
                "autorizado": False,
                "modo": "CRASH",
                "tp_mult": 1.25,
                "rs_min": 85.0,
                "fator_risco": 0.0,
                "msg": f"SPY em queda extrema/crash hoje ({var_dia:.2f}% <= -2.50%){tag_vix}."
            }
        if vix_atual is not None and vix_atual > 32.0:
            return {
                "autorizado": False,
                "modo": "PANICO_VIX",
                "tp_mult": 1.25,
                "rs_min": 85.0,
                "fator_risco": 0.0,
                "msg": f"VIX em pânico sistémico ({vix_atual:.2f} > 32.00)."
            }

        # Regime Baixista Seletivo (SPY abaixo da SMA200 mas VIX <= 32)
        if close_hoje < sma200:
            return {
                "autorizado": True,
                "modo": "BAIXISTA_SELETIVO",
                "tp_mult": 1.25,
                "rs_min": 85.0,
                "fator_risco": 0.35,
                "msg": (
                    f"SPY abaixo da SMA200 (${close_hoje:.2f} < ${sma200:.2f}{tag_vix}) — "
                    f"Modo Seletivo de Elite: apenas líderes RS >= 85 em tendência própria (> EMA20 > SMA50 > SMA200), TP 1.25R e Lote 35%."
                )
            }

        # Regime Corretivo / Lateral (SPY acima da SMA200 mas abaixo da EMA20)
        if close_hoje < ema20:
            fator = 0.40 if (vix_atual is not None and vix_atual > 25.0) else 0.60
            return {
                "autorizado": True,
                "modo": "CORRETIVO",
                "tp_mult": 1.25,
                "rs_min": 75.0,
                "fator_risco": fator,
                "msg": (
                    f"SPY em pullback/lateral (${close_hoje:.2f} < EMA20 ${ema20:.2f} | SMA200 ${sma200:.2f} | "
                    f"Var: {var_dia:+.2f}%{tag_vix}) — Modo Tático: Alvo 1.25R, RS >= 75 e Lote {int(fator*100)}%."
                )
            }

        # Regime em Expansão (SPY > EMA20 > SMA200)
        fator = 0.60 if (vix_atual is not None and vix_atual > 25.0) else 1.0
        return {
            "autorizado": True,
            "modo": "EXPANSAO",
            "tp_mult": 1.75,
            "rs_min": 65.0,
            "fator_risco": fator,
            "msg": (
                f"SPY em Expansão (${close_hoje:.2f} > EMA20 ${ema20:.2f} > SMA200 ${sma200:.2f} | "
                f"Var: {var_dia:+.2f}%{tag_vix}) — Alvo 1.75R | RS >= 65 | Lote {int(fator*100)}%."
            )
        }
    except Exception as e:
        regime_default["msg"] = f"Aviso SPY: {e}"
        return regime_default

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

def obter_setor_yf(ticker):
    """Fallback para obter o setor diretamente do yfinance caso falhe no Sheets"""
    try:
        t = yf.Ticker(ticker, session=session)
        setor = t.info.get('sector')
        return setor if setor else "Desconhecido"
    except Exception:
        return "Desconhecido"

# ===================================================================
# 3. CARGA DE DADOS, REGIME MACRO E PARAMETRIZAÇÃO DE RISCO
# ===================================================================
ativos_sheets, posicoes_ativas_dict, configs_dict = buscar_dados_completos()
regime_macro = verificar_regime_mercado()

capital = limpar_float(configs_dict.get("CAPITAL_TOTAL_CONTA")) or 10400.00
pct_risco = (
    limpar_float(configs_dict.get("RISCO_POR_TRADE")) or 
    limpar_float(configs_dict.get("RISCO_SWING_PCT")) or 
    0.0025
)
risco_fixo_usd = limpar_float(configs_dict.get("RISCO_MAXIMO_USD"))

risco_base_usd = risco_fixo_usd if (risco_fixo_usd and risco_fixo_usd > 0) else (capital * pct_risco)
vol_diaria_usd = round(risco_base_usd * regime_macro["fator_risco"], 2) if regime_macro["autorizado"] else 0.0

print(f"[CONFIG] Capital Total: ${capital:,.2f} | Risco Base: ${risco_base_usd:,.2f} | Risco Ajustado Regime ({regime_macro['modo']}): ${vol_diaria_usd:,.2f} USD\n")

# Mapeia setores e posições realmente ativas (ignora posições FECHADA)
mapa_setores_watchlist = {}
for item in ativos_sheets:
    t_item = str(item.get("ticker", "")).strip().upper().replace(".", "-")
    s_item = str(item.get("setor") or item.get("setorAtivo") or item.get("sector") or item.get("Setor") or "").strip()
    if t_item and s_item and s_item.lower() not in ["desconhecido", "n/a", "none", "#n/a"]:
        mapa_setores_watchlist[t_item] = s_item

tickers_ativos_set = set()
setores_ocupados = set()
for chave_pos, info in posicoes_ativas_dict.items():
    if isinstance(info, dict) and str(info.get("status", "")).strip().upper().startswith("ATIVA"):
        t_pos = "AI" if chave_pos.lower() in ["c3.ai", "c3"] else chave_pos.strip().upper().replace(".", "-")
        tickers_ativos_set.add(t_pos)
        setor_pos = str(info.get("setor") or mapa_setores_watchlist.get(t_pos, "")).strip()
        if setor_pos and setor_pos.lower() not in ["desconhecido", "n/a", "none", "#n/a"]:
            setores_ocupados.add(setor_pos.lower())

if setores_ocupados:
    print(f"[PROTEÇÃO SETORIAL] Setores já com posição ativa (bloqueados para novas entradas): {', '.join(sorted(setores_ocupados))}\n")

# ===================================================================
# 4. AUDITAR POSIÇÕES EM CARTEIRA (ALVO DINÂMICO + BE +1.0R + TIME-STOP 96H)
# ===================================================================
bloco_posicoes_ativas = ""
alerta_timestop_ativo = False

def obter_dados_posicao_m20(ticker, dt_abertura=None):
    preco_atual = 0.0
    atr_atual = 0.0
    maxima_desde_abertura = 0.0
    minima_vela_anterior = 0.0

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
                minima_vela_anterior = round(float(df_pos['Low'].iloc[-2]), 2) if len(df_pos) >= 2 else round(float(df_pos['Low'].iloc[-1]), 2)
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
    return preco_atual, atr_atual, maxima_efetiva, minima_vela_anterior

for chave_pos, info in posicoes_ativas_dict.items():
    if not isinstance(info, dict): continue
    status = str(info.get("status", "")).strip().upper()
    
    if status == "ATIVA_M20":
        try:
            ticker = "AI" if chave_pos.lower() in ["c3.ai", "c3"] else chave_pos.strip().upper().replace(".", "-")
            if ticker == "BRK-A": ticker = "BRK-B"
            
            data_abertura = info.get("dataAbertura", "")
            dt_abertura = parse_data_abertura(data_abertura)
            dias_uteis = calcular_dias_uteis(data_abertura)
            tag_tempo = f" | {dias_uteis}d úteis" if dias_uteis is not None else ""
            
            preco_atual, atr_calc, maxima_efetiva, min_anterior = obter_dados_posicao_m20(ticker, dt_abertura)
            
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
            
            mult_r_ativo = regime_macro["tp_mult"]
            alvo_dinamico = round(entrada + (risco_inicial * mult_r_ativo), 2) if risco_inicial > 0 else 0.0

            if tp_sheets > (entrada * 1.005):
                if regime_macro["modo"] != "EXPANSAO" and alvo_dinamico > 0 and alvo_dinamico < tp_sheets:
                    alvo_tp = alvo_dinamico
                    label_alvo = f"${alvo_tp} (TP Tático {mult_r_ativo:.2f}R | Original: ${tp_sheets})"
                else:
                    alvo_tp = tp_sheets
                    label_alvo = f"${alvo_tp}"
            elif risco_inicial > 0:
                alvo_tp = alvo_dinamico
                label_alvo = f"${alvo_tp} (TP {mult_r_ativo:.2f}R)"
            else:
                alvo_tp = 0.0
                label_alvo = "N/A"
                
            qtd = info.get("quantidade", "N/A")
            
            # Proteção Break-Even apenas aos +1.0R (dá espaço para o pullback retomar a tendência)
            be_calculado = round(entrada * 1.0005, 2)
            patamar_lucro_1r = entrada + (risco_inicial * 1.0)
            em_lucro_protegido = (
                (stop >= entrada) or 
                (risco_inicial > 0 and maxima_efetiva >= patamar_lucro_1r and preco_atual > entrada)
            )

            sugestao_stop = stop
            if em_lucro_protegido and be_calculado > stop:
                sugestao_stop = be_calculado

            # Trailing Stop dinâmico para extensão de vencedores
            trailing_extensao = max(sugestao_stop, round(min_anterior * 0.998, 2)) if (min_anterior > 0 and min_anterior < preco_atual) else sugestao_stop
            
            # Janela de 4 dias úteis (96h) para Pullback EMA 20
            if alvo_tp > 0 and preco_atual >= alvo_tp:
                acao = f"🎯 ALVO ALCANÇADO ({label_alvo})! Recomendado FECHAR POSIÇÃO com Lucro (WIN)."
            elif stop > 0 and preco_atual <= stop:
                acao = f"🚨 STOP LOSS ATINGIDO (${stop})! Recomendado LIQUIDAR POSIÇÃO (LOSS)."
            elif dias_uteis is not None and dias_uteis >= 4:
                if em_lucro_protegido and preco_atual >= patamar_lucro_1r:
                    acao = (
                        f"🚀 EXTENSÃO DE VENCEDOR ({dias_uteis}d úteis > 96h, mas em lucro >= +1.0R)! "
                        f"MANTER rumo a {label_alvo} com Trailing Stop elevado para ${trailing_extensao}."
                    )
                else:
                    alerta_timestop_ativo = True
                    acao = (
                        f"⏰ TIME-STOP ATINGIDO ({dias_uteis}d úteis > 96h, sem impulso >= +1.0R)! "
                        f"Recomendado FECHAR A MERCADO (${preco_atual}) antes de varrer o Stop (${stop})."
                    )
            elif dias_uteis == 3:
                if em_lucro_protegido:
                    acao = f"🛡️ JANELA 72h->96h + LUCRO PROTEGIDO (+1.0R)! Sobe Stop p/ BE: ${sugestao_stop} | Pode estender além de 96h rumo a {label_alvo}."
                elif preco_atual < entrada:
                    acao = f"⚠️ ÚLTIMO DIA (4.º dia) EM NEGATIVO (${preco_atual} < ${entrada}). Se não recuperar no fecho, encerrar antecipadamente para poupar risco | Stop: ${stop}."
                else:
                    acao = f"⚠️ ÚLTIMO DIA DA JANELA (4.º dia). Se não arrancar hoje rumo a {label_alvo}, preparar saída no fecho | Stop: ${stop}."
            elif sugestao_stop > stop and preco_atual > entrada:
                acao = f"🛡️ PROTEGER POSIÇÃO{tag_tempo}. +1.0R Atingido! Sobe o Stop para Break-Even: ${sugestao_stop} | Alvo: {label_alvo}."
            else:
                acao = f"⏳ MANTER POSIÇÃO (Pullback EMA 20{tag_tempo}). Alvo: {label_alvo} | Stop: ${stop}."
            
            bloco_posicoes_ativas += (
                f"📌 [{status}] {ticker} ({chave_pos}) | Qtd: {qtd} | Entrada: ${entrada} | "
                f"Atual: ${preco_atual} | {acao}\n"
            )
        except Exception as e:
            print(f"[ERRO] Falha ao auditar posição ativa {chave_pos}: {e}")

# ===================================================================
# 5. MOTOR MATEMÁTICO: PULLBACK À EMA 20 (ALVO ADAPTATIVO AO REGIME SPY)
# ===================================================================
def analisar_pullback_ema20(ativo_info, regime):
    try:
        # FILTRO DE FORÇA RELATIVA DINÂMICO (RS >= 65 Expansão | RS >= 75 Corretivo | RS >= 85 Baixista Seletivo)
        rs_score = limpar_float(ativo_info.get("rs_score")) or 0.0
        if rs_score < regime["rs_min"]:
            return None

        ticker = str(ativo_info.get("ticker", "")).strip().upper().replace(".", "-")
        if not ticker or ticker == "#N/A" or ticker == "NONE": return None
        if ticker == "BRK-A": ticker = "BRK-B"
        if ticker in tickers_ativos_set: return None

        nome_empresa = ativo_info.get("nome") or ativo_info.get("nomeEmpresa") or ativo_info.get("name") or "N/A"
        setor = str(
            ativo_info.get("setor") or 
            ativo_info.get("setorAtivo") or 
            ativo_info.get("sector") or 
            ativo_info.get("Setor") or "Desconhecido"
        ).strip()

        if setor.lower() not in ["desconhecido", "n/a", "none", "#n/a", ""] and setor.lower() in setores_ocupados:
            return None

        time.sleep(random.uniform(0.4, 1.0))

        # Verificar setor e earnings iminentes (<= 3 dias)
        try:
            t_obj = yf.Ticker(ticker, session=session)
            if setor.lower() in ["desconhecido", "n/a", "none", "#n/a", ""]:
                setor = t_obj.info.get("sector") or obter_setor_yf(ticker)

            calendario = t_obj.calendar
            if isinstance(calendario, dict) and 'Earnings Date' in calendario and len(calendario['Earnings Date']) > 0:
                proxima_data = calendario['Earnings Date'][0]
                if hasattr(proxima_data, 'date'): proxima_data = proxima_data.date()
                dias_restantes = (proxima_data - datetime.now(ZoneInfo("Europe/Lisbon")).date()).days
                if 0 <= dias_restantes <= 3:
                    return None
        except Exception:
            if setor.lower() in ["desconhecido", "n/a", "none", "#n/a", ""]:
                setor = obter_setor_yf(ticker)

        if setor.lower() not in ["desconhecido", "n/a", "none", "#n/a", ""] and setor.lower() in setores_ocupados:
            return None
        if any(termo in setor.lower() for termo in ["real estate", "reit", "mortgage"]):
            return None

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
        if len(df) < 200: return None

        preco = float(df['Close'].iloc[-1])
        vol_sma20 = float(df['Volume'].rolling(20).mean().iloc[-1])
        if preco < 10.00 or vol_sma20 < 300000:
            return None

        # Indicadores de Tendência Completa
        df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        df.ta.atr(length=14, append=True)

        col_atr = [c for c in df.columns if str(c).startswith('ATRr_') or str(c).startswith('ATR_')][0]
        df = df.dropna(subset=['EMA_20', 'SMA_50', 'SMA_200', col_atr])
        if df.empty: return None

        ultimo = df.iloc[-1]
        ema20 = float(ultimo['EMA_20'])
        sma50 = float(ultimo['SMA_50'])
        sma200 = float(ultimo['SMA_200'])
        atr = float(ultimo[col_atr])
        
        minimo_hoje = float(ultimo['Low'])
        fecho_hoje = float(ultimo['Close'])
        maximo_hoje = float(ultimo['High'])

        # Alinhamento institucional completo + zona de defesa na EMA 20 (tolerância de 0.5% acima / 0.8% abaixo)
        tendencia_alta = (ema20 > sma50) and (sma50 > sma200)
        zona_defesa_ema20 = (minimo_hoje <= ema20 * 1.005) and (fecho_hoje >= ema20 * 0.992)

        if tendencia_alta and zona_defesa_ema20:
            entrada_gatilho = round(maximo_hoje * 1.002, 2)
            stop_loss = round(min(minimo_hoje * 0.995, entrada_gatilho - (atr * 1.5)), 2)
            
            risco = entrada_gatilho - stop_loss
            if risco <= 0:
                return None

            # Alvo Pullback EMA20 dinâmico: 1.75R em Expansão | 1.25R em Corretivo / Baixista Seletivo
            tp_mult = regime["tp_mult"]
            alvo_tp = round(entrada_gatilho + (risco * tp_mult), 2)

            qtd_calc = round(vol_diaria_usd / risco, 2)
            if qtd_calc <= 0:
                return None
            val_calc = entrada_gatilho * qtd_calc

            return {
                "ticker": ticker,
                "nome_empresa": nome_empresa,
                "setor": setor,
                "preco_atual": round(preco, 2),
                "gatilho": entrada_gatilho,
                "stop_loss": stop_loss,
                "alvo_tp": alvo_tp,
                "tp_mult": tp_mult,
                "qtd_acoes": qtd_calc,
                "valor_investir": round(val_calc, 2),
                "estado_pullback": "A ATIVAR (Pullback Detetado: Preço defendeu a zona da EMA 20 sobre SMA50/200)",
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
    try:
        candidatos_pullback = []
        total_analisados = 0
        
        mercado_ok = regime_macro["autorizado"]
        msg_mercado = regime_macro["msg"]
        tp_mult_label = f"{regime_macro['tp_mult']:.2f}R"

        if mercado_ok and ativos_sheets:
            for ativo_info in ativos_sheets:
                ticker = ativo_info.get("ticker")
                if not ticker or ticker == "#N/A": continue
                
                total_analisados += 1
                res = analisar_pullback_ema20(ativo_info, regime_macro)
                if res: candidatos_pullback.append(res)

        # Ordena por RS Score mais alto e limita a 1 entrada por setor livre
        candidatos_pullback = sorted(candidatos_pullback, key=lambda x: x['rs_score'], reverse=True)
        alertas_pullback = []
        setores_novos_usados = set()
        for item in candidatos_pullback:
            s_key = item["setor"].lower()
            if s_key not in setores_novos_usados:
                alertas_pullback.append(item)
                if s_key not in ["desconhecido", "n/a", ""]:
                    setores_novos_usados.add(s_key)

        data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M")
        
        bloco_texto = (
            f"⚡ RELATÓRIO DETALHADO - MOTOR 20: PULLBACK À EMA 20 ({data_hoje})\n"
            f"==================================================================\n"
            f"🌐 Filtro Macro: {msg_mercado}\n"
            f"💰 Risco Configurado por Trade: ${vol_diaria_usd:,.2f} USD (Base: ${risco_base_usd:,.2f} | Fator: {int(regime_macro['fator_risco']*100)}%)\n\n"
        )

        if bloco_posicoes_ativas:
            bloco_texto += f"📌 GESTÃO DE POSIÇÕES ATIVAS:\n{bloco_posicoes_ativas}\n--------------------------------------------------\n\n"
        else:
            bloco_texto += "📌 GESTÃO DE POSIÇÕES ATIVAS: Nenhuma posição ativa detetada para este motor.\n--------------------------------------------------\n\n"

        if not mercado_ok:
            bloco_texto += f"🛡️ [MODO DEFENSIVO] Novas entradas bloqueadas hoje ({msg_mercado}).\n"
        elif alertas_pullback:
            bloco_texto += f"🎯 NOVOS SINAIS DE PULLBACK À EMA 20 ({len(alertas_pullback)}):\n\n"
            for a in alertas_pullback:
                bloco_texto += (
                    f"🔹 [{a['ticker']}] - {a['nome_empresa']} ({a['setor']})\n"
                    f"   - 📊 Contexto Técnico: {a['estado_pullback']}\n"
                    f"   - ⚙️ Tática: Continuação de Tendência (Alvo {tp_mult_label} [{regime_macro['modo']}] | BE +1.0R | Time-Stop 96h)\n"
                    f"   - 📋 Tipo de Ordem: BUY STOP (Gatilho na quebra da máxima diária da vela de defesa)\n"
                    f"   - 🔢 Dados Exatos: Gatilho Compra: ${a['gatilho']} | Stop Loss: ${a['stop_loss']} | Alvo ({tp_mult_label}): ${a['alvo_tp']}\n"
                    f"   - 💰 Dimensionamento: Qtd: {a['qtd_acoes']} | Valor a Investir: ~${a['valor_investir']} USD\n"
                    f"   - 📈 RS Score Institucional: {a['rs_score']}\n"
                    f"--------------------------------------------------\n"
                )
        else:
            bloco_texto += "✅ Nenhum novo sinal de Pullback à EMA 20 detetado hoje.\n"

        enviar_email(bloco_texto)

        with open("comboio_pullback_temp.txt", "w", encoding="utf-8") as f:
            f.write(bloco_texto)

        # ===================================================================
        # 7. NOTIFICAÇÃO TELEGRAM (DEBUG OU ALERTA TIME-STOP)
        # ===================================================================
        debug_telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

        if debug_telegram_ativado or len(alertas_pullback) > 0 or alerta_timestop_ativo:
            print("A enviar notificação para o Telegram via função modular...")
            total_acionados = len(alertas_pullback)
            aviso_ts = "\n⏰ *ALERTA TIME-STOP:* Tens posição(ões) M20 expirada(s) (>96h sem impulso) para fechar!" if alerta_timestop_ativo else ""
            mensagem_debug = (
                f"20 ⚡ *MOTOR 20 (PULLBACK EMA 20)*\n\n"
                f"🔍 [STATUS] Execução concluída ({regime_macro['modo']} | Alvo {tp_mult_label}).\n"
                f"📊 Analisados: *{total_analisados}* | Acionados: *{total_acionados}*{aviso_ts}\n"
                f"💰 Risco/Trade: *${vol_diaria_usd:.2f}*\n"
                f"✉️ Relatório de pullback gerado e enviado por e-mail."
            )
            enviar_alerta(mensagem_debug)
    except Exception as e:
        erro_str = f"[ERRO CRÍTICO M20] {e}\n{traceback.format_exc()}"
        print(erro_str)
        with open("comboio_pullback_temp.txt", "w", encoding="utf-8") as f:
            f.write(erro_str)

if __name__ == "__main__":
    executar_motor()
