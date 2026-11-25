# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR 21: CONFLUÊNCIA SUPREMA
# ===================================================================================
# Descrição Geral:
# O modelo "Sniper". Exige confluência absoluta:
# 1. Filtro de Mercado (SPY + ^VIX) com modo Seletivo de Elite em regime baixista
# 2. Força Relativa de Elite (RS Score >= 75 Expansão | >= 80 Cautela | >= 85 Baixista Seletivo)
# 3. Pullback à Zona da EMA 20 em Tendência Primária (EMA 20 > SMA 50 > SMA 200)
# 4. Squeeze de Volatilidade (BB dentro de KC ou Pré-Squeeze apertado)
# 5. Entrada Institucional Silenciosa (RVOL >= 1.35x vs média dos 20 dias anteriores)
# Assimetria Sniper (2.5R Expansão / 2.0R Defensivo) | Break-Even +1.0R | Time-Stop 96h.
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
    print("[INFO] Fim de semana detetado. O Motor Confluência vai descansar.")
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

def obter_preco_tempo_real(ticker_str, fallback_close):
    try:
        t = yf.Ticker(ticker_str, session=session)
        fast = t.fast_info
        for attr in ('pre_market_price', 'post_market_price', 'last_price'):
            val = getattr(fast, attr, None)
            if val is not None and not np.isnan(val) and float(val) > 0:
                return round(float(val), 2)
    except Exception:
        pass
    return round(float(fallback_close), 2)

def obter_setor_yf(ticker):
    try:
        t = yf.Ticker(ticker, session=session)
        setor = t.info.get('sector')
        return setor if setor else "Desconhecido"
    except Exception:
        return "Desconhecido"

# ===================================================================
# 2. FILTRO GERAL DE MERCADO (S&P 500 + VIX)
# ===================================================================
def verificar_regime_mercado():
    """
    Matriz Macro de 4 Estados para entradas Sniper (Confluência Suprema):
    - Expansão (SPY > EMA20 > SMA200 & VIX <= 25): RS >= 75 | Alvo 2.5R | Lote 100%
    - Expansão Cautela (SPY > EMA20 > SMA200 & 25 < VIX <= 32): RS >= 80 | Alvo 2.0R | Lote 50%
    - Corretivo / Pullback Macro (SMA200 < SPY <= EMA20 & VIX <= 32): RS >= 82 | Alvo 2.0R | Lote 45%
    - Baixista Seletivo (SPY < SMA200 & VIX <= 32): RS >= 85 | Alvo 2.0R | Lote 30%
    - Bloqueado (queda diária <= -2.00% ou VIX > 32): Sem novas entradas
    """
    regime_default = {
        "autorizado": True,
        "modo": "EXPANSAO",
        "tp_mult": 2.5,
        "rs_min": 75.0,
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
        ema20 = float(df_spy['Close'].ewm(span=20, adjust=False).mean().iloc[-1])
        sma200 = float(df_spy['Close'].rolling(200).mean().iloc[-1])
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

        if var_dia <= -2.00:
            return {
                "autorizado": False,
                "modo": "QUEDA_DIARIA",
                "tp_mult": 2.0,
                "rs_min": 85.0,
                "fator_risco": 0.0,
                "msg": f"SPY em queda forte hoje ({var_dia:.2f}% <= -2.00%){tag_vix}. Entradas Sniper bloqueadas."
            }
        if vix_atual is not None and vix_atual > 32.0:
            return {
                "autorizado": False,
                "modo": "PANICO_VIX",
                "tp_mult": 2.0,
                "rs_min": 85.0,
                "fator_risco": 0.0,
                "msg": f"VIX em pânico sistémico ({vix_atual:.2f} > 32.00). Entradas Sniper bloqueadas."
            }

        if close_hoje < sma200:
            return {
                "autorizado": True,
                "modo": "BAIXISTA_SELETIVO",
                "tp_mult": 2.0,
                "rs_min": 85.0,
                "fator_risco": 0.30,
                "msg": (
                    f"SPY abaixo da SMA200 (${close_hoje:.2f} < ${sma200:.2f}{tag_vix}) — "
                    f"Sniper Seletivo de Elite: apenas líderes RS >= 85 em tendência própria (> EMA20 > SMA50 > SMA200), TP 2.0R e Lote 30%."
                )
            }

        if close_hoje < ema20:
            fator = 0.35 if (vix_atual is not None and vix_atual > 25.0) else 0.45
            return {
                "autorizado": True,
                "modo": "CORRETIVO_SELETIVO",
                "tp_mult": 2.0,
                "rs_min": 82.0,
                "fator_risco": fator,
                "msg": (
                    f"SPY em pullback (${close_hoje:.2f} < EMA20 ${ema20:.2f} | SMA200 ${sma200:.2f}{tag_vix}) — "
                    f"Sniper Tático: RS >= 82 | TP 2.0R | Lote {int(fator*100)}%."
                )
            }

        if vix_atual is not None and vix_atual > 25.0:
            return {
                "autorizado": True,
                "modo": "EXPANSAO_CAUTELA",
                "tp_mult": 2.0,
                "rs_min": 80.0,
                "fator_risco": 0.50,
                "msg": (
                    f"SPY em tendência (${close_hoje:.2f} > EMA20 ${ema20:.2f} > SMA200 ${sma200:.2f} | "
                    f"Var: {var_dia:+.2f}%{tag_vix}) — Cautela VIX: RS >= 80 | TP 2.0R | Lote 50%."
                )
            }

        return {
            "autorizado": True,
            "modo": "EXPANSAO",
            "tp_mult": 2.5,
            "rs_min": 75.0,
            "fator_risco": 1.0,
            "msg": (
                f"SPY em tendência (${close_hoje:.2f} > EMA20 ${ema20:.2f} > SMA200 ${sma200:.2f} | "
                f"Var: {var_dia:+.2f}%{tag_vix}) — RS >= 75 | TP 2.5R | Lote 100%."
            )
        }
    except Exception as e:
        print(f"[AVISO] Falha ao verificar filtro SPY: {e}")
        regime_default["msg"] = f"Aviso SPY: {e}"
        return regime_default

# ===================================================================
# 3. FUNÇÕES DE REDE E CARGA DE DADOS
# ===================================================================
def buscar_dados_completos():
    print("A carregar Watchlist, Posições Ativas e Configs a partir do Google Sheets...")
    if not WEBHOOK_URL: return [], {}, {}
    try:
        url_alvo = WEBHOOK_URL if "?" in WEBHOOK_URL else f"{WEBHOOK_URL}?aba=Analise Compra"
        resp = requests.get(url_alvo, timeout=20)
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

print(f"[CONFIG] Capital Total: ${capital:,.2f} | Risco Base: ${risco_base_usd:,.2f} | Risco Ajustado ({regime_macro['modo']}): ${vol_diaria_usd:,.2f} USD")
print(f"[MACRO] {regime_macro['msg']}\n")

# Mapeamento de setores e posições realmente ativas (ignora posições FECHADA)
mapa_setores_watchlist = {}
for item in ativos_sheets:
    t_item = str(item.get("ticker", "")).strip().upper().replace(".", "-")
    s_item = str(item.get("setor") or item.get("setorAtivo") or item.get("sector") or "").strip()
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

# ===================================================================
# 3B. AUDITAR POSIÇÕES EM CARTEIRA (ALVO DINÂMICO + BE +1.0R + TIME-STOP 96H)
# ===================================================================
bloco_posicoes_ativas = ""
alerta_timestop_ativo = False
alerta_gestao_urgente = False
qtd_posicoes_auditadas = 0

def obter_dados_posicao_m21(ticker, dt_abertura=None):
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
        preco_atual = obter_preco_tempo_real(ticker, 0.0)

    maxima_efetiva = max(maxima_desde_abertura, preco_atual)
    return preco_atual, atr_atual, maxima_efetiva, minima_vela_anterior

for chave_pos, info in posicoes_ativas_dict.items():
    if not isinstance(info, dict): continue
    status = str(info.get("status", "")).strip().upper()
    
    if status == "ATIVA_M21":
        qtd_posicoes_auditadas += 1
        try:
            ticker = "AI" if chave_pos.lower() in ["c3.ai", "c3"] else chave_pos.strip().upper().replace(".", "-")
            if ticker == "BRK-A": ticker = "BRK-B"
            
            data_abertura = info.get("dataAbertura", "")
            dt_abertura = parse_data_abertura(data_abertura)
            dias_uteis = calcular_dias_uteis(data_abertura)
            tag_tempo = f" | {dias_uteis}d úteis" if dias_uteis is not None else ""
            
            preco_atual, atr_calc, maxima_efetiva, min_anterior = obter_dados_posicao_m21(ticker, dt_abertura)
            
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
                    label_alvo = f"${alvo_tp} (TP Tático {mult_r_ativo:.1f}R | Original: ${tp_sheets})"
                else:
                    alvo_tp = tp_sheets
                    label_alvo = f"${alvo_tp}"
            elif risco_inicial > 0:
                alvo_tp = alvo_dinamico
                label_alvo = f"${alvo_tp} (TP {mult_r_ativo:.1f}R)"
            else:
                alvo_tp = 0.0
                label_alvo = "N/A"
                
            qtd = info.get("quantidade", "N/A")
            
            # Proteção Break-Even aos +1.0R
            be_calculado = round(entrada * 1.001, 2)
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
            
            if alvo_tp > 0 and preco_atual >= alvo_tp:
                acao = f"🎯 ALVO ALCANÇADO ({label_alvo})! Recomendado FECHAR POSIÇÃO com Lucro (WIN)."
                alerta_gestao_urgente = True
            elif stop > 0 and preco_atual <= stop:
                acao = f"🚨 STOP LOSS ATINGIDO (${stop})! Recomendado LIQUIDAR POSIÇÃO (LOSS)."
                alerta_gestao_urgente = True
            elif dias_uteis is not None and dias_uteis >= 4:
                if em_lucro_protegido and preco_atual >= patamar_lucro_1r:
                    acao = (
                        f"🚀 EXTENSÃO DE VENCEDOR ({dias_uteis}d úteis > 96h, mas em lucro >= +1.0R)! "
                        f"MANTER rumo a {label_alvo} com Trailing Stop elevado para ${trailing_extensao}."
                    )
                    if trailing_extensao > stop:
                        alerta_gestao_urgente = True
                else:
                    alerta_timestop_ativo = True
                    alerta_gestao_urgente = True
                    acao = (
                        f"⏰ TIME-STOP ATINGIDO ({dias_uteis}d úteis > 96h, sem impulso >= +1.0R)! "
                        f"Recomendado FECHAR A MERCADO (${preco_atual}) antes de varrer o Stop (${stop})."
                    )
            elif dias_uteis == 3:
                if em_lucro_protegido:
                    acao = f"🛡️ JANELA SNIPER 72h->96h + LUCRO PROTEGIDO (+1.0R)! Sobe Stop p/ BE: ${sugestao_stop} | Pode estender além de 96h rumo a {label_alvo}."
                    if sugestao_stop > stop:
                        alerta_gestao_urgente = True
                elif preco_atual < entrada:
                    acao = f"⚠️ ÚLTIMO DIA SNIPER (4.º dia) EM NEGATIVO (${preco_atual} < ${entrada}). Se não recuperar no fecho, encerrar antecipadamente para poupar risco | Stop: ${stop}."
                else:
                    acao = f"⚠️ ÚLTIMO DIA DA JANELA SNIPER (4.º dia). Se não arrancar rumo a {label_alvo}, preparar saída no fecho | Stop: ${stop}."
            elif sugestao_stop > stop and preco_atual > entrada:
                acao = f"🛡️ PROTEGER POSIÇÃO{tag_tempo}. +1.0R Atingido! Sobe o Stop para Break-Even: ${sugestao_stop} | Alvo: {label_alvo}."
                alerta_gestao_urgente = True
            else:
                acao = f"⏳ MANTER POSIÇÃO (Confluência Suprema{tag_tempo}). Alvo: {label_alvo} | Stop: ${stop}."
            
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
        # FILTRO 1: FORÇA RELATIVA DE ELITE (RS >= 75 Expansão | >= 80 Cautela | >= 82 Corretivo | >= 85 Baixista)
        rs_score = limpar_float(ativo_info.get("rs_score")) or 0.0
        if rs_score < regime_macro["rs_min"]:
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
            ativo_info.get("Setor") or ""
        ).strip()

        if setor and setor.lower() not in ["desconhecido", "n/a", "none", "#n/a"] and setor.lower() in setores_ocupados:
            return None

        time.sleep(random.uniform(0.4, 1.0))

        # Verificar setor e earnings iminentes (<= 3 dias)
        alerta_earnings = "OK"
        try:
            ticker_obj = yf.Ticker(ticker, session=session)
            if not setor or setor.lower() in ["desconhecido", "n/a", "", "none", "#n/a"]:
                setor = ticker_obj.info.get('sector') or obter_setor_yf(ticker)

            calendario = ticker_obj.calendar
            if isinstance(calendario, dict) and 'Earnings Date' in calendario and len(calendario['Earnings Date']) > 0:
                proxima_data = calendario['Earnings Date'][0]
                if hasattr(proxima_data, 'date'): proxima_data = proxima_data.date()
                dias_restantes = (proxima_data - datetime.now(ZoneInfo("Europe/Lisbon")).date()).days
                if 0 <= dias_restantes <= 3:
                    alerta_earnings = f"PERIGO (em {dias_restantes} dias)"
        except Exception:
            if not setor or setor.lower() in ["desconhecido", "n/a", "", "none", "#n/a"]:
                setor = obter_setor_yf(ticker)

        if "PERIGO" in alerta_earnings:
            return None
        if setor and setor.lower() not in ["desconhecido", "n/a", "none", "#n/a"] and setor.lower() in setores_ocupados:
            return None
        if setor and any(termo in setor.lower() for termo in ["real estate", "reit", "mortgage"]):
            return None

        df = pd.DataFrame()
        for _ in range(3):
            try:
                df = yf.download(ticker, period="1y", interval="1d", progress=False, timeout=15, session=session)
                if not df.empty and len(df) >= 200: break
            except Exception:
                time.sleep(2)

        if df.empty or len(df) < 200: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
        df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])
        if len(df) < 200: return None

        preco = float(df['Close'].iloc[-1])
        if preco < 10.00: return None

        # INDICADORES TÉCNICOS
        df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        df['Vol_SMA_20_Prev'] = df['Volume'].shift(1).rolling(window=20).mean()
        
        # Bollinger Bands (SMA 20)
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        df['STD_20'] = df['Close'].rolling(window=20).std()
        df['BB_Upper'] = df['SMA_20'] + (df['STD_20'] * 2.0)
        df['BB_Lower'] = df['SMA_20'] - (df['STD_20'] * 2.0)
        
        # Keltner Channels e ATR
        df.ta.atr(length=20, mamode="rma", append=True)
        col_atr = [c for c in df.columns if str(c).startswith('ATRr_') or str(c).startswith('ATR_')][0]
        df['KC_Upper'] = df['EMA_20'] + (df[col_atr] * 1.5)
        df['KC_Lower'] = df['EMA_20'] - (df[col_atr] * 1.5)

        df = df.dropna(subset=['EMA_20', 'SMA_50', 'SMA_200', 'BB_Upper', 'KC_Upper', 'Vol_SMA_20_Prev', col_atr])
        if df.empty: return None

        ultimo = df.iloc[-1]
        ema20 = float(ultimo['EMA_20'])
        sma50 = float(ultimo['SMA_50'])
        sma200 = float(ultimo['SMA_200'])
        bb_upper, bb_lower = float(ultimo['BB_Upper']), float(ultimo['BB_Lower'])
        kc_upper, kc_lower = float(ultimo['KC_Upper']), float(ultimo['KC_Lower'])
        atr = float(ultimo[col_atr])
        vol_atual = float(ultimo['Volume'])
        vol_sma20_prev = float(ultimo['Vol_SMA_20_Prev'])
        
        if vol_sma20_prev < 300000:
            return None

        minimo_hoje = float(ultimo['Low'])
        fecho_hoje = float(ultimo['Close'])
        maximo_hoje = float(ultimo['High'])

        # LÓGICA DE CONFLUÊNCIA ABSOLUTA:
        # A. Tendência Alinhada & Pullback na Zona da EMA 20
        tendencia_alta = (ema20 > sma50) and (sma50 > sma200)
        toque_ema20 = (minimo_hoje <= ema20 * 1.012) and (fecho_hoje >= ema20 * 0.992)
        
        # B. Compressão (BB dentro de KC ou Pré-Squeeze apertado <= 105% da largura KC)
        bb_width = bb_upper - bb_lower
        kc_width = kc_upper - kc_lower
        em_squeeze = ((bb_upper <= kc_upper) and (bb_lower >= kc_lower)) or (bb_width <= kc_width * 1.05)
        
        # C. Acumulação Institucional (RVOL >= 1.35x vs média dos 20 dias anteriores)
        rvol = vol_atual / vol_sma20_prev if vol_sma20_prev > 0 else 0.0
        volume_anomalo = rvol >= 1.35

        if tendencia_alta and toque_ema20 and em_squeeze and volume_anomalo:
            preco_rt = obter_preco_tempo_real(ticker, preco)
            entrada_gatilho = round(maximo_hoje * 1.002, 2)

            # Não perseguir se já abriu esticado > 2.5% acima do gatilho ou caiu > 1.5% abaixo do fecho
            if preco_rt > entrada_gatilho * 1.025 or preco_rt < preco * 0.985:
                return None

            stop_loss = round(min(minimo_hoje * 0.995, entrada_gatilho - (atr * 1.5)), 2)
            risco = entrada_gatilho - stop_loss
            if risco <= 0:
                return None

            # Assimetria Sniper M21: 2.5R em Expansão | 2.0R em modos defensivos
            tp_mult = regime_macro["tp_mult"]
            alvo_tp = round(entrada_gatilho + (risco * tp_mult), 2)

            qtd_calc = round(vol_diaria_usd / risco, 2)
            if qtd_calc <= 0:
                return None

            val_calc = entrada_gatilho * qtd_calc

            return {
                "ticker": ticker,
                "nome_empresa": nome_empresa,
                "setor": setor,
                "preco_atual": preco_rt,
                "gatilho": entrada_gatilho,
                "stop_loss": stop_loss,
                "alvo_tp": alvo_tp,
                "tp_mult": tp_mult,
                "qtd_acoes": qtd_calc,
                "valor_investir": round(val_calc, 2),
                "rvol": round(rvol, 2),
                "rs_score": rs_score,
                "estado_confluencia": "💎 CONFLUÊNCIA SUPREMA (Pullback EMA20 + Squeeze + Volume Institucional)"
            }
        return None
    except Exception as e:
        print(f"[ERRO] Falha ao processar ativo {ativo_info.get('ticker')}: {e}")
        return None

# ===================================================================
# 5. EXECUÇÃO PRINCIPAL E RELATÓRIO
# ===================================================================
def executar_motor():
    data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M")
    tp_mult_label = f"{regime_macro['tp_mult']:.1f}R"

    bloco_texto = (
        f"⚡ RELATÓRIO DETALHADO - MOTOR 21: CONFLUÊNCIA SUPREMA ({data_hoje})\n"
        f"==================================================================\n"
        f"🌐 Filtro Macro: {regime_macro['msg']}\n"
        f"💰 Risco Configurado por Trade: ${vol_diaria_usd:,.2f} USD (Base: ${risco_base_usd:,.2f} | Fator: {int(regime_macro['fator_risco']*100)}%)\n\n"
    )

    if bloco_posicoes_ativas:
        bloco_texto += f"📌 GESTÃO DE POSIÇÕES ATIVAS:\n{bloco_posicoes_ativas}\n--------------------------------------------------\n\n"
    else:
        bloco_texto += "📌 GESTÃO DE POSIÇÕES ATIVAS: Nenhuma posição ativa detetada para este motor.\n--------------------------------------------------\n\n"

    # 1. Verifica Filtro Macro (Mesmo em modo defensivo, envia antes a auditoria das posições ativas!)
    if not regime_macro["autorizado"]:
        aviso_defensivo = f"🛡️ [MODO DEFENSIVO] Novas entradas bloqueadas hoje ({regime_macro['msg']}).\n"
        print(aviso_defensivo)
        bloco_texto += aviso_defensivo
        
        with open("comboio_confluencia_temp.txt", "w", encoding="utf-8") as f:
            f.write(bloco_texto)
            
        enviar_email(bloco_texto)
        
        debug_telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]
        if debug_telegram_ativado or alerta_gestao_urgente:
            aviso_ts = "\n⏰ *ALERTA TIME-STOP:* Tens posição(ões) M21 expirada(s) (>96h sem impulso) para fechar!" if alerta_timestop_ativo else ""
            enviar_alerta(f"21 ⚡ *MOTOR 21 (CONFLUÊNCIA SUPREMA)*\n\n🛡️ *MODO DEFENSIVO ATIVO*\n{regime_macro['msg']}{aviso_ts}")
        return

    candidatos_confluencia = []
    total_analisados = 0
    
    if ativos_sheets:
        for ativo_info in ativos_sheets:
            if not ativo_info.get("ticker") or ativo_info.get("ticker") == "#N/A": continue
            total_analisados += 1
            res = analisar_confluencia_suprema(ativo_info)
            if res: candidatos_confluencia.append(res)

    # Ordena por RS Score e RVOL e limita a 1 entrada Sniper por setor livre
    candidatos_confluencia = sorted(candidatos_confluencia, key=lambda k: (k['rs_score'], k['rvol']), reverse=True)
    alertas_confluencia = []
    setores_novos_usados = set()
    for item in candidatos_confluencia:
        s_key = item["setor"].lower()
        if s_key not in setores_novos_usados:
            alertas_confluencia.append(item)
            if s_key not in ["desconhecido", "n/a", ""]:
                setores_novos_usados.add(s_key)

    if alertas_confluencia:
        bloco_texto += f"🎯 SINAIS DE ALTA PROBABILIDADE (SNIPER) ({len(alertas_confluencia)}):\n\n"
        for a in alertas_confluencia:
            bloco_texto += (
                f"💎 [{a['ticker']}] - {a['nome_empresa']} ({a['setor']})\n"
                f"    - 📊 Contexto Técnico: {a['estado_confluencia']}\n"
                f"    - ⚙️ Tática: Breakout Sniper Assimétrico (Alvo {tp_mult_label} [{regime_macro['modo']}] | BE +1.0R | Time-Stop Adaptativo 96h)\n"
                f"    - 📋 Tipo de Ordem: BUY STOP (Gatilho: ${a['gatilho']})\n"
                f"    - 🔢 Risco/Retorno ({tp_mult_label}): Stop Loss: ${a['stop_loss']} | Alvo ({tp_mult_label}): ${a['alvo_tp']}\n"
                f"    - 💰 Dimensionamento: Qtd: {a['qtd_acoes']} | Investimento: ~${a['valor_investir']} USD\n"
                f"    - 📈 Métricas de Força: RS Score: {a['rs_score']} | RVOL: {a['rvol']}x\n"
                f"--------------------------------------------------\n"
            )
        bloco_texto += "\n🔄 LEMBRETE OPERACIONAL: Assim que uma ordem Buy Stop for executada na corretora, altera o estado no Google Sheets para 'ATIVA_M21' para iniciar a gestão automática de Break-Even (+1.0R) e Time-Stop de 96h.\n"
    else:
        bloco_texto += "✅ Nenhum ativo atingiu a perfeição técnica exigida pelo Motor 21 hoje. O capital permanece seguro.\n"

    enviar_email(bloco_texto)

    with open("comboio_confluencia_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco_texto)

    # Notificação no Telegram
    debug_telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]
    if debug_telegram_ativado or len(alertas_confluencia) > 0 or alerta_gestao_urgente:
        aviso_ts = "\n⏰ *ALERTA TIME-STOP:* Tens posição(ões) M21 expirada(s) (>96h sem impulso) para fechar!" if alerta_timestop_ativo else ""
        enviar_alerta(
            f"21 ⚡ *MOTOR 21 (CONFLUÊNCIA)*\n\n"
            f"🔍 Execução Concluída ({regime_macro['modo']} | Alvo {tp_mult_label}).\n"
            f"📊 Analisados: *{total_analisados}* | Novos Sinais: *{len(alertas_confluencia)}* | Em Gestão: *{qtd_posicoes_auditadas}*{aviso_ts}\n"
            f"💰 Risco/Trade: *${vol_diaria_usd:.2f}*"
        )

if __name__ == "__main__":
    executar_motor()
