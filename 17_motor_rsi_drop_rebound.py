# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR 17: 2-DAY RSI DROP & REBOUND (CONFIRMADO)
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
    print("[INFO] Fim de semana detetado. O Motor 17 vai descansar.")
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
                print(f"[DIAGNÓSTICO SHEETS] Ativos: {len(ativos)} | Posições recebidas: {len(posicoes)}")
                for k, v in posicoes.items():
                    if isinstance(v, dict):
                        print(f"   -> Posição '{k}': status='{v.get('status')}' | dataAbertura='{v.get('dataAbertura')}'")
                return ativos, posicoes, configs
            elif isinstance(dados, list):
                return dados, {}, {}
        return [], {}, {}
    except Exception as e:
        print(f"[ERRO CRÍTICO] Sheets: {e}")
        return [], {}, {}

def verificar_regime_mercado():
    """
    Avalia o regime do SPY e devolve parâmetros adaptativos para Mean Reversion:
    - Expansão (SPY > EMA20): TP 1.5R | RS >= 70 | RSI(2) <= 8.0 | Fator Lote 1.0 (0.5 se VIX > 23)
    - Corretivo/Lateral (SMA200 < SPY <= EMA20): TP 1.0R | RS >= 80 | RSI(2) <= 8.0 | Fator Lote 0.5 (0.35 se VIX > 23)
    - Reversão Baixista (SPY < SMA200, mas sem crash <= -2.0% nem VIX > 32): TP 1.0R | RS >= 85 | RSI(2) <= 5.0 | Fator Lote 0.35
    - Crash / Pânico Extremo (Var <= -2.0% ou VIX > 32): Bloqueio total (0%)
    """
    regime_default = {
        "autorizado": True,
        "modo": "EXPANSAO",
        "tp_mult": 1.5,
        "rs_min": 70.0,
        "rsi2_max": 8.0,
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

        if var_dia <= -2.0:
            return {
                "autorizado": False,
                "modo": "CRASH",
                "tp_mult": 1.0,
                "rs_min": 85.0,
                "rsi2_max": 5.0,
                "fator_risco": 0.0,
                "msg": f"SPY em queda extrema/crash hoje ({var_dia:.2f}% <= -2.00%){tag_vix}."
            }
        if vix_atual is not None and vix_atual > 32.0:
            return {
                "autorizado": False,
                "modo": "PANICO_VIX",
                "tp_mult": 1.0,
                "rs_min": 85.0,
                "rsi2_max": 5.0,
                "fator_risco": 0.0,
                "msg": f"VIX em pânico sistémico extremo ({vix_atual:.2f} > 32.00)."
            }

        # Exceção Tática de Mean Reversion: SPY abaixo da SMA200, mas sem pânico extremo nem crash diário
        if close_hoje < sma200:
            return {
                "autorizado": True,
                "modo": "REVERSAO_BAIXISTA",
                "tp_mult": 1.0,
                "rs_min": 85.0,
                "rsi2_max": 5.0,
                "fator_risco": 0.35,
                "msg": (
                    f"SPY abaixo da SMA200 (${close_hoje:.2f} < ${sma200:.2f} | Var: {var_dia:+.2f}%{tag_vix}) — "
                    f"Modo Ressalto Defensivo: apenas líderes (RS >= 85 & > SMA200), RSI(2) <= 5.0, Alvo 1.0R e Lote 35%."
                )
            }

        # Regime Corretivo / Lateral (SPY acima da SMA200 mas abaixo da EMA20)
        if close_hoje < ema20:
            fator = 0.35 if (vix_atual is not None and vix_atual > 23.0) else 0.50
            return {
                "autorizado": True,
                "modo": "CORRETIVO",
                "tp_mult": 1.0,
                "rs_min": 80.0,
                "rsi2_max": 8.0,
                "fator_risco": fator,
                "msg": (
                    f"SPY em pullback/lateral (${close_hoje:.2f} < EMA20 ${ema20:.2f} | SMA200 ${sma200:.2f} | "
                    f"Var: {var_dia:+.2f}%{tag_vix}) — Modo Tático: Alvo 1.0R, RS >= 80 e Lote {int(fator*100)}%."
                )
            }

        # Regime em Expansão (SPY > EMA20 > SMA200)
        fator = 0.50 if (vix_atual is not None and vix_atual > 23.0) else 1.0
        return {
            "autorizado": True,
            "modo": "EXPANSAO",
            "tp_mult": 1.5,
            "rs_min": 70.0,
            "rsi2_max": 8.0,
            "fator_risco": fator,
            "msg": (
                f"SPY em Expansão (${close_hoje:.2f} > EMA20 ${ema20:.2f} > SMA200 ${sma200:.2f} | "
                f"Var: {var_dia:+.2f}%{tag_vix}) — Alvo 1.5R | Lote {int(fator*100)}%."
            )
        }
    except Exception as e:
        regime_default["msg"] = f"Aviso SPY: {e}"
        return regime_default

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
        print("[SUCESSO] Email enviado com sucesso!")
        return True
    except Exception as e:
        print(f"[ERRO EMAIL] Falha ao enviar e-mail: {e}")
        return False

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

# Mapeia setores já ocupados por posições ativas para evitar stops em cadeia no mesmo setor
mapa_setores_watchlist = {}
for item in ativos_sheets:
    t_item = str(item.get("ticker", "")).strip().upper()
    s_item = str(item.get("setor") or item.get("setorAtivo") or item.get("sector") or item.get("Setor") or "").strip()
    if t_item and s_item and s_item not in ["Desconhecido", "N/A", "NONE"]:
        mapa_setores_watchlist[t_item] = s_item

setores_ocupados = set()
for chave_pos, info in posicoes_ativas_dict.items():
    if isinstance(info, dict) and str(info.get("status", "")).strip().upper().startswith("ATIVA"):
        t_pos = "AI" if chave_pos.lower() in ["c3.ai", "c3"] else chave_pos.strip().upper()
        setor_pos = str(info.get("setor") or mapa_setores_watchlist.get(t_pos, "")).strip()
        if setor_pos and setor_pos not in ["Desconhecido", "N/A", "NONE"]:
            setores_ocupados.add(setor_pos.lower())

if setores_ocupados:
    print(f"[PROTEÇÃO SETORIAL] Setores já com posição ativa (bloqueados para novas entradas): {', '.join(sorted(setores_ocupados))}\n")

# ===================================================================
# 4. AUDITAR POSIÇÕES EM CARTEIRA (ALVO DINÂMICO + BE +0.8R + TIME-STOP 72H)
# ===================================================================
bloco_posicoes_ativas = ""
alerta_timestop_ativo = False

def obter_dados_posicao_m17(ticker, dt_abertura=None):
    preco_atual = 0.0
    ema5_atual = 0.0
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
                df_pos['EMA5'] = df_pos['Close'].ewm(span=5, adjust=False).mean()
                df_pos.ta.atr(length=14, append=True)
                cols_atr = [c for c in df_pos.columns if str(c).startswith('ATRr_') or str(c).startswith('ATR_') or str(c).startswith('ATRe_')]
                if cols_atr:
                    atr_atual = round(float(df_pos[cols_atr[0]].iloc[-1]), 2)
                ema5_atual = round(float(df_pos['EMA5'].iloc[-1]), 2)
                preco_atual = round(float(df_pos['Close'].iloc[-1]), 2)
                minima_vela_anterior = round(float(df_pos['Low'].iloc[-2]), 2) if len(df_pos) >= 2 else round(float(df_pos['Low'].iloc[-1]), 2)
    except Exception as e:
        print(f"[AVISO] Falha ao obter dados diários para {ticker}: {e}")

    try:
        df_rt = yf.download(ticker, period="5d", interval="1m", prepost=True, progress=False, session=session)
        if not df_rt.empty:
            if isinstance(df_rt.columns, pd.MultiIndex):
                df_rt.columns = df_rt.columns.get_level_values(0)
            df_rt = df_rt.dropna(subset=['Close', 'High'])
            if not df_rt.empty:
                ultimo_rt = float(df_rt['Close'].iloc[-1])
                if ultimo_rt > 0:
                    preco_atual = round(ultimo_rt, 2)
                if dt_abertura is not None:
                    idx_lisbon = df_rt.index.tz_convert("Europe/Lisbon") if df_rt.index.tzinfo else df_rt.index.tz_localize("UTC").tz_convert("Europe/Lisbon")
                    df_pos_abertura = df_rt[idx_lisbon >= dt_abertura]
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
    return preco_atual, ema5_atual, atr_atual, maxima_efetiva, minima_vela_anterior

for chave_pos, info in posicoes_ativas_dict.items():
    if not isinstance(info, dict): continue
    status = str(info.get("status", "")).strip().upper()
    
    if status == "ATIVA_M17":
        try:
            ticker = "AI" if chave_pos.lower() in ["c3.ai", "c3"] else chave_pos.strip().upper()
            
            data_abertura = info.get("dataAbertura", "")
            dt_abertura = parse_data_abertura(data_abertura)
            dias_uteis = calcular_dias_uteis(data_abertura)
            tag_tempo = f" | {dias_uteis}d úteis" if dias_uteis is not None else ""
            
            preco_atual, ema5_dinamica, atr_calc, maxima_efetiva, min_anterior = obter_dados_posicao_m17(ticker, dt_abertura)
            
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
            alvo_dinamico = round(entrada + (risco_inicial * mult_r_ativo), 2) if risco_inicial > 0 else ema5_dinamica
            
            if tp_sheets > (entrada * 1.005):
                if regime_macro["modo"] != "EXPANSAO" and alvo_dinamico > 0 and alvo_dinamico < tp_sheets:
                    alvo_efetivo = alvo_dinamico
                    label_alvo = f"${alvo_efetivo} (TP Tático 1.0R | Original: ${tp_sheets})"
                else:
                    alvo_efetivo = tp_sheets
                    label_alvo = f"${alvo_efetivo}"
            elif ema5_dinamica > (entrada + (risco_inicial * 0.8)) and (alvo_dinamico <= 0 or ema5_dinamica <= alvo_dinamico):
                alvo_efetivo = ema5_dinamica
                label_alvo = f"${alvo_efetivo} (EMA5)"
            else:
                alvo_efetivo = alvo_dinamico
                label_alvo = f"${alvo_efetivo} (TP {mult_r_ativo:.1f}R)"
                
            qtd = info.get("quantidade", "N/A")

            be_calculado = round(entrada * 1.0005, 2)
            patamar_lucro_be = entrada + (risco_inicial * 0.8)
            em_lucro_protegido = (
                (stop >= entrada) or 
                (risco_inicial > 0 and maxima_efetiva >= patamar_lucro_be and preco_atual > entrada)
            )

            sugestao_stop = stop
            if em_lucro_protegido and be_calculado > stop:
                sugestao_stop = be_calculado

            trailing_extensao = max(sugestao_stop, round(min_anterior * 0.998, 2)) if (min_anterior > 0 and min_anterior < preco_atual) else sugestao_stop

            if alvo_efetivo > 0 and preco_atual >= alvo_efetivo:
                acao = f"🎯 ALVO ALCANÇADO ({label_alvo})! Recomendado FECHAR POSIÇÃO com Lucro (WIN)."
            elif stop > 0 and preco_atual <= stop:
                acao = f"🚨 STOP LOSS ATINGIDO (${stop})! Recomendado LIQUIDAR POSIÇÃO (LOSS)."
            elif dias_uteis is not None and dias_uteis >= 3:
                if em_lucro_protegido and preco_atual >= patamar_lucro_be:
                    acao = (
                        f"🚀 EXTENSÃO DE VENCEDOR ({dias_uteis}d úteis > 72h, mas em lucro >= +0.8R)! "
                        f"MANTER rumo a {label_alvo} com Trailing Stop elevado para ${trailing_extensao}."
                    )
                else:
                    alerta_timestop_ativo = True
                    acao = (
                        f"⏰ TIME-STOP ATINGIDO ({dias_uteis}d úteis > 72h, sem impulso >= +0.8R)! "
                        f"Recomendado FECHAR A MERCADO (${preco_atual}) antes de varrer o Stop (${stop})."
                    )
            elif dias_uteis == 2:
                if em_lucro_protegido:
                    acao = f"🛡️ JANELA 48h + LUCRO PROTEGIDO (+0.8R)! Sobe Stop p/ BE: ${sugestao_stop} | Pode estender além de 72h rumo a {label_alvo}."
                elif preco_atual < entrada:
                    acao = f"⚠️ ÚLTIMO DIA (48h) EM NEGATIVO (${preco_atual} < ${entrada}). Se não recuperar no fecho, encerrar antecipadamente para poupar risco | Stop: ${stop}."
                else:
                    acao = f"⚠️ ÚLTIMO DIA DA JANELA (48h). Se não arrancar hoje rumo a {label_alvo}, preparar saída no fecho | Stop: ${stop}."
            elif sugestao_stop > stop and preco_atual > entrada:
                acao = f"🛡️ PROTEGER POSIÇÃO{tag_tempo}. +0.8R Atingido! Sobe o Stop para Break-Even: ${sugestao_stop} | Alvo: {label_alvo}."
            else:
                acao = f"⏳ MANTER POSIÇÃO (RSI Rebound{tag_tempo}). Alvo: {label_alvo} | Stop: ${stop}."
            
            bloco_posicoes_ativas += (
                f"📌 [{status}] {ticker} ({chave_pos}) | Qtd: {qtd} | Entrada: ${entrada} | "
                f"Atual: ${preco_atual} | {acao}\n"
            )
        except Exception as e:
            print(f"[ERRO] Falha ao auditar posição ativa {chave_pos}: {e}")

# ===================================================================
# 5. MOTOR MATEMÁTICO V3: 2-DAY RSI DROP COM ALVO ADAPTATIVO AO REGIME SPY
# ===================================================================
def analisar_rsi_drop(ativo_info, regime):
    try:
        rs_score = limpar_float(ativo_info.get("rs_score")) or 0.0
        if rs_score < regime["rs_min"]:
            return None

        ticker = str(ativo_info.get("ticker", "")).strip().upper()
        if not ticker or ticker == "#N/A" or ticker == "NONE": return None
        if ticker in posicoes_ativas_dict: return None
        if ticker == "BRK-A": ticker = "BRK-B"

        setor_inicial = str(
            ativo_info.get("setor") or 
            ativo_info.get("setorAtivo") or 
            ativo_info.get("sector") or 
            ativo_info.get("Setor") or "Desconhecido"
        ).strip()

        if setor_inicial != "Desconhecido" and setor_inicial.lower() in setores_ocupados:
            return None

        df = yf.download(ticker, period="1y", interval="1d", progress=False, session=session)
        if df.empty or len(df) < 200: return None
        
        if isinstance(df.columns, pd.MultiIndex): 
            df.columns = df.columns.droplevel(1)
            
        df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])
        if len(df) < 200: return None

        df.ta.rsi(length=2, append=True)
        df.ta.sma(length=200, append=True)
        df.ta.sma(length=50, append=True)
        df.ta.atr(length=14, append=True)
        df['EMA5'] = df['Close'].ewm(span=5, adjust=False).mean()

        cols_rsi = [c for c in df.columns if str(c).startswith('RSI_2')]
        cols_sma200 = [c for c in df.columns if str(c).startswith('SMA_200')]
        cols_sma50 = [c for c in df.columns if str(c).startswith('SMA_50')]
        cols_atr = [c for c in df.columns if str(c).startswith('ATRr_') or str(c).startswith('ATR_') or str(c).startswith('ATRe_')]

        if not cols_rsi or not cols_sma200 or not cols_sma50 or not cols_atr:
            return None

        df = df.dropna(subset=[cols_rsi[0], cols_sma200[0], cols_sma50[0], cols_atr[0]])
        if df.empty: return None

        ultimo = df.iloc[-1]
        preco = float(ultimo['Close'])
        maxima_dia = float(ultimo['High'])
        minima_dia = float(ultimo['Low'])
        rsi2 = float(ultimo[cols_rsi[0]])
        sma200 = float(ultimo[cols_sma200[0]])
        sma50 = float(ultimo[cols_sma50[0]])
        atr = float(ultimo[cols_atr[0]])
        ema5 = float(ultimo['EMA5'])

        if preco > sma200 and sma50 > sma200 and rsi2 <= regime["rsi2_max"]:
            entrada_gatilho = round(maxima_dia * 1.002, 2)
            stop_loss = round(min(minima_dia * 0.995, entrada_gatilho - (atr * 1.5)), 2)
            risco = entrada_gatilho - stop_loss
            if risco <= 0:
                return None

            # Alvo dinâmico: 1.5R em Expansão | 1.0R em Corretivo ou Reversão Baixista
            tp_mult = regime["tp_mult"]
            alvo_tp = round(entrada_gatilho + (risco * tp_mult), 2)
            
            # Dimensionamento fracionado exato pelo risco ajustado
            qtd_calc = round(vol_diaria_usd / risco, 2)
            if qtd_calc <= 0:
                return None
            val_calc = entrada_gatilho * qtd_calc

            nome_empresa = (
                ativo_info.get("nome") or 
                ativo_info.get("nomeEmpresa") or 
                ativo_info.get("name") or "N/A"
            )
            setor = setor_inicial

            if nome_empresa == "N/A" or setor == "Desconhecido":
                try:
                    t_obj = yf.Ticker(ticker, session=session)
                    info_t = t_obj.info
                    if nome_empresa == "N/A":
                        nome_empresa = info_t.get("longName") or info_t.get("shortName") or "N/A"
                    if setor == "Desconhecido":
                        setor = info_t.get("sector") or "Desconhecido"
                except Exception:
                    pass

            if setor != "Desconhecido" and setor.lower() in setores_ocupados:
                return None

            return {
                "ticker": ticker,
                "nome_empresa": nome_empresa,
                "setor": setor,
                "preco_atual": round(preco, 2),
                "ema5": round(ema5, 2),
                "rsi2": round(rsi2, 2),
                "gatilho": entrada_gatilho,
                "stop_loss": stop_loss,
                "alvo_tp": alvo_tp,
                "tp_mult": tp_mult,
                "qtd_acoes": qtd_calc,
                "valor_investir": round(val_calc, 2),
                "rs_score": rs_score
            }
        return None
    except Exception as e:
        print(f"[ERRO] Falha ao analisar RSI Drop em {ativo_info.get('ticker')}: {e}")
        return None

# ===================================================================
# 6. EXECUÇÃO PRINCIPAL E RELATÓRIO
# ===================================================================
def executar_motor():
    try:
        candidatos_rsi = []
        total_analisados = 0

        mercado_ok = regime_macro["autorizado"]
        msg_mercado = regime_macro["msg"]
        tp_mult_label = f"{regime_macro['tp_mult']:.1f}R"

        if mercado_ok and ativos_sheets:
            for ativo_info in ativos_sheets:
                ticker = ativo_info.get("ticker")
                if not ticker or ticker == "#N/A": continue
                total_analisados += 1
                res = analisar_rsi_drop(ativo_info, regime_macro)
                if res: candidatos_rsi.append(res)

        # Ordena por RS Score mais alto e RSI(2) mais extremo, limitando a 1 entrada por setor livre
        candidatos_rsi = sorted(candidatos_rsi, key=lambda x: (x['rs_score'], -x['rsi2']), reverse=True)
        alertas_rsi = []
        setores_novos_usados = set()
        for item in candidatos_rsi:
            s_key = item["setor"].lower()
            if s_key not in setores_novos_usados:
                alertas_rsi.append(item)
                if s_key not in ["desconhecido", "n/a", ""]:
                    setores_novos_usados.add(s_key)

        data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M")
        
        bloco_texto = (
            f"⚡ RELATÓRIO DETALHADO - MOTOR 17: 2-DAY RSI DROP CONFIRMADO ({data_hoje})\n"
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
        elif alertas_rsi:
            bloco_texto += f"🎯 SINAIS DE REVERSÃO CONFIRMADA DETETADOS ({len(alertas_rsi)}):\n\n"
            for a in alertas_rsi:
                bloco_texto += (
                    f"🔹 [{a['ticker']}] - {a['nome_empresa']} ({a['setor']})\n"
                    f"    - 📊 Contexto Técnico: RSI(2) em {a['rsi2']} (Sobrevendido Extremo <= {regime_macro['rsi2_max']} | EMA5: ${a['ema5']} | SMA50 > SMA200)\n"
                    f"    - ⚙️ Tática: Reversão à Média Adaptativa (Alvo {tp_mult_label} [{regime_macro['modo']}] | Time-Stop 72h)\n"
                    f"    - 📋 Tipo de Ordem: BUY STOP (Só ativa se romper máxima de hoje: ${a['gatilho']})\n"
                    f"    - 🔢 Dados Exatos: Gatilho Compra: ${a['gatilho']} | Stop Loss: ${a['stop_loss']} | Alvo TP ({tp_mult_label}): ${a['alvo_tp']}\n"
                    f"    - 💰 Dimensionamento: Qtd: {a['qtd_acoes']} | Valor a Investir: ~${a['valor_investir']} USD\n"
                    f"    - 📈 RS Score Institucional: {a['rs_score']}\n"
                    f"--------------------------------------------------\n"
                )
        else:
            bloco_texto += "✅ Nenhum novo sinal de RSI Drop confirmado detetado hoje.\n"

        with open("comboio_rsi_rebound_temp.txt", "w", encoding="utf-8") as f:
            f.write(bloco_texto)

        assunto_email = f"⚡🎯 tradingRelatorioIA US - MOTOR 17 RSI DROP ({datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')})"
        enviar_email(assunto_email, bloco_texto)

        debug_telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

        if debug_telegram_ativado or len(alertas_rsi) > 0 or alerta_timestop_ativo:
            print("A enviar notificação para o Telegram via função modular...")
            total_acionados = len(alertas_rsi)
            aviso_ts = "\n⏰ *ALERTA TIME-STOP:* Tens posição(ões) M17 expirada(s) (>72h sem impulso) para fechar!" if alerta_timestop_ativo else ""
            mensagem_telegram = (
                f"17 ⚡ *MOTOR 17 (RSI DROP CONFIRMADO)*\n\n"
                f"🔍 [STATUS] Execução concluída ({regime_macro['modo']} | Alvo {tp_mult_label}).\n"
                f"📊 Analisados: *{total_analisados}* | Gatilhos Buy Stop: *{total_acionados}*{aviso_ts}\n"
                f"💰 Risco/Trade: *${vol_diaria_usd:.2f}*\n"
                f"✉️ Relatório enviado por e-mail."
            )
            enviar_alerta(mensagem_telegram)
    except Exception as e:
        erro_str = f"[ERRO CRÍTICO M17] {e}\n{traceback.format_exc()}"
        print(erro_str)
        with open("comboio_rsi_rebound_temp.txt", "w", encoding="utf-8") as f:
            f.write(erro_str)

if __name__ == "__main__":
    executar_motor()
