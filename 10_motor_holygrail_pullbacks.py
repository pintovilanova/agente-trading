# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR HOLY GRAIL (PULLBACKS DE LIDERANÇA)
# ===================================================================================
# Descrição Geral:
# Implementa a estratégia "Holy Grail" (Linda Raschke / David Ryan):
#   - Liderança Institucional: RS Score >= 80 (>= 85 em regime corretivo)
#   - Tendência Robusta: EMA 20 > EMA 50 > SMA 200 e ADX(14) > 25
#   - Pullback Saudável: Mínima toca a zona da EMA 20 com seca de volume (< 80% SMA50)
#   - Gatilho: Ordem BUY STOP acima da máxima das últimas 2 sessões
#   - Auditoria Dinâmica: Monitoriza posições ATIVA_M10 / ATIVA_SWING (EMA20 - ATR)
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
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import warnings
warnings.filterwarnings("ignore")

from F01_notificador_telegram import enviar_alerta

# ===================================================================
# BYPASS SESSÃO YAHOO FINANCE (PARA GITHUB ACTIONS)
# ===================================================================
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O Motor Holy Grail vai descansar.")
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

MIN_RS_SCORE_HOLY_GRAIL = 80.0

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
# 2. FUNÇÕES DE REDE, REGIME MACRO & PREÇO TEMPO REAL
# ===================================================================
def verificar_regime_mercado_hg():
    """
    Avalia o regime do SPY para Pullbacks Holy Grail:
    - Expansão (SPY > EMA20 > SMA200): RS >= 80 | Fator Lote 1.0 (0.5 se VIX > 23)
    - Corretivo (SMA200 < SPY <= EMA20): RS >= 85 | Fator Lote 0.5 (0.35 se VIX > 23)
    - Baixista / Queda <= -1.50% / VIX > 30: Bloqueia novas entradas (mantém gestão)
    """
    regime_default = {
        "autorizado": True,
        "modo": "EXPANSAO",
        "rs_min": MIN_RS_SCORE_HOLY_GRAIL,
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

        if close_hoje < sma200:
            return {
                "autorizado": False,
                "modo": "BAIXISTA",
                "rs_min": 85.0,
                "fator_risco": 0.0,
                "msg": f"SPY (${close_hoje:.2f}) abaixo da SMA200 (${sma200:.2f}). Regime Baixista{tag_vix}."
            }
        if var_dia <= -1.50:
            return {
                "autorizado": False,
                "modo": "QUEDA_DIARIA",
                "rs_min": 85.0,
                "fator_risco": 0.0,
                "msg": f"SPY em queda acentuada hoje ({var_dia:.2f}% <= -1.50%){tag_vix}. Pullbacks bloqueados."
            }
        if vix_atual is not None and vix_atual > 30.0:
            return {
                "autorizado": False,
                "modo": "PANICO_VIX",
                "rs_min": 85.0,
                "fator_risco": 0.0,
                "msg": f"VIX em pânico sistémico ({vix_atual:.2f} > 30.00)."
            }

        if close_hoje < ema20:
            fator = 0.35 if (vix_atual is not None and vix_atual > 23.0) else 0.50
            return {
                "autorizado": True,
                "modo": "CORRETIVO",
                "rs_min": 85.0,
                "fator_risco": fator,
                "msg": (
                    f"SPY em pullback/lateral (${close_hoje:.2f} < EMA20 ${ema20:.2f} | SMA200 ${sma200:.2f} | "
                    f"Var: {var_dia:+.2f}%{tag_vix}) — Holy Grail Tático: RS >= 85 e Lote {int(fator*100)}%."
                )
            }

        fator = 0.50 if (vix_atual is not None and vix_atual > 23.0) else 1.0
        return {
            "autorizado": True,
            "modo": "EXPANSAO",
            "rs_min": MIN_RS_SCORE_HOLY_GRAIL,
            "fator_risco": fator,
            "msg": (
                f"SPY em Expansão (${close_hoje:.2f} > EMA20 ${ema20:.2f} > SMA200 ${sma200:.2f} | "
                f"Var: {var_dia:+.2f}%{tag_vix}) — RS >= 80 | Lote {int(fator*100)}%."
            )
        }
    except Exception as e:
        regime_default["msg"] = f"Aviso SPY: {e}"
        return regime_default

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

def enviar_email(conteudo):
    print("\nA enviar email do Holy Grail Pullbacks para o Agente IA...")
    if not EMAIL_USER or not EMAIL_PASS: return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = f"🏆 tradingRelatorioIA US - HOLY GRAIL PULLBACKS ({datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')})"
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
            print(f"[ERRO] Tentativa {tentativa + 1}: {e}")
            if tentativa < 2: time.sleep(5)

# ===================================================================
# 3. EXECUÇÃO PRINCIPAL
# ===================================================================
def executar_motor():
    ativos_sheets, posicoes_ativas_dict, configs_dict = buscar_dados_completos()
    if not ativos_sheets and not posicoes_ativas_dict:
        print("[AVISO] Nenhum dado retornado do Google Sheets.")
        sys.exit(0)

    regime_macro = verificar_regime_mercado_hg()

    capital = limpar_float(configs_dict.get("CAPITAL_TOTAL_CONTA")) or 10400.00
    vol_anual = limpar_float(configs_dict.get("ALVO_VOLATILIDADE_ANUAL")) or 0.05
    risco_fixo_usd = limpar_float(configs_dict.get("RISCO_MAXIMO_USD"))

    vol_diaria_usd = (capital * vol_anual) / 16.0
    risco_base_usd = risco_fixo_usd if (risco_fixo_usd and risco_fixo_usd > 0) else vol_diaria_usd
    risco_ajustado_usd = round(risco_base_usd * regime_macro["fator_risco"], 2) if regime_macro["autorizado"] else 0.0

    print(f"[CONFIG] Capital: ${capital:,.2f} | Risco Base: ${risco_base_usd:.2f} | Risco Ajustado ({regime_macro['modo']}): ${risco_ajustado_usd:.2f} USD")
    print(f"[MACRO] {regime_macro['msg']}\n")

    # Mapeamento de setores e posições realmente ativas (ignora posições FECHADA)
    mapa_setores_watchlist = {}
    for item in ativos_sheets:
        t_item = str(item.get("ticker", "")).strip().upper().replace(".", "-")
        s_item = str(item.get("setor") or item.get("setorAtivo") or item.get("sector") or "").strip()
        if t_item and s_item and s_item not in ["Desconhecido", "N/A", "NONE"]:
            mapa_setores_watchlist[t_item] = s_item

    tickers_ativos_set = set()
    setores_ocupados = set()
    for chave_pos, info in posicoes_ativas_dict.items():
        if isinstance(info, dict) and str(info.get("status", "")).strip().upper().startswith("ATIVA"):
            t_pos = "AI" if chave_pos.lower() in ["c3.ai", "c3"] else chave_pos.strip().upper().replace(".", "-")
            tickers_ativos_set.add(t_pos)
            setor_pos = str(info.get("setor") or mapa_setores_watchlist.get(t_pos, "")).strip()
            if setor_pos and setor_pos not in ["Desconhecido", "N/A", "NONE"]:
                setores_ocupados.add(setor_pos.lower())

    # ===================================================================
    # 4. AUDITAR POSIÇÕES EM CARTEIRA (LÓGICA DINÂMICA DE EMA20 E ATR)
    # ===================================================================
    bloco_posicoes_ativas = ""
    alerta_gestao_urgente = False
    qtd_posicoes_auditadas = 0

    for ticker_raw, info in posicoes_ativas_dict.items():
        if not isinstance(info, dict): continue
        status = str(info.get("status", "")).strip().upper()
        if status in ["ATIVA_M10", "ATIVA_SWING"]:
            qtd_posicoes_auditadas += 1
            ticker_clean = "BRK-B" if ticker_raw == "BRK-A" else ticker_raw.strip().upper().replace(".", "-")
            try:
                time.sleep(random.uniform(0.3, 0.7))
                # Usa 6mo para garantir que a EMA_50 tem histórico suficiente para convergir
                df_pos = yf.download(ticker_clean, period="6mo", interval="1d", progress=False, session=session)
                if not df_pos.empty and len(df_pos) >= 30:
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
                    
                    preco_fecho = round(float(ultimo_pos['Close']), 2)
                    maxima_hoje = round(float(ultimo_pos['High']), 2)
                    minima_hoje = round(float(ultimo_pos['Low']), 2)
                    preco_atual = obter_preco_tempo_real(ticker_clean, preco_fecho)

                    try:
                        df_intra = yf.download(ticker_clean, period="2d", interval="1m", prepost=True, progress=False, session=session)
                        if not df_intra.empty:
                            if isinstance(df_intra.columns, pd.MultiIndex):
                                df_intra.columns = df_intra.columns.droplevel(1)
                            preco_atual = round(float(df_intra['Close'].iloc[-1]), 2)
                            maxima_hoje = max(maxima_hoje, round(float(df_intra['High'].iloc[-100:].max()), 2))
                            minima_hoje = min(minima_hoje, round(float(df_intra['Low'].iloc[-100:].min()), 2))
                    except Exception:
                        pass
                    
                    entrada = limpar_float(info.get("precoEntrada")) or preco_atual
                    qtd = info.get("quantidade", "N/A")
                    maxima_efetiva = max(maxima_hoje, preco_atual)
                    minima_efetiva = min(minima_hoje, preco_atual)
                    
                    trailing_sugerido = round(ema20_atual - atr_atual, 2)
                    
                    if alvo_tp > 0 and maxima_efetiva >= alvo_tp:
                        acao = f"🎯 ALVO ALCANÇADO (TP em ${alvo_tp})! Recomendado FECHAR POSIÇÃO com Lucro (WIN)."
                        alerta_gestao_urgente = True
                    elif stop_atual > 0 and minima_efetiva <= stop_atual:
                        acao = f"🚨 STOP LOSS ATINGIDO (${stop_atual})! Recomendado LIQUIDAR POSIÇÃO (LOSS)."
                        alerta_gestao_urgente = True
                    elif preco_atual < ema50_atual:
                        acao = f"⚠️ ALERTA TÉCNICO: Preço (${preco_atual}) abaixo da EMA50 (${ema50_atual}). Deterioração da tendência, considerar fechar."
                        alerta_gestao_urgente = True
                    elif trailing_sugerido > stop_atual:
                        acao = f"📈 GESTÃO DINÂMICA: Subir Stop Loss para o novo Trailing baseado na EMA20 (${trailing_sugerido})."
                        alerta_gestao_urgente = True
                    else:
                        acao = f"⏳ MANTER POSIÇÃO (Holy Grail). Preço acima da EMA20 (${ema20_atual}) | Stop Atual: ${stop_atual}."
                    
                    bloco_posicoes_ativas += (
                        f"📌 [POSIÇÃO ATIVA - {status}] {ticker_clean} | Qtd: {qtd} | Entrada: ${entrada} | "
                        f"Preço Atual: ${preco_atual} | EMA20: ${ema20_atual} | EMA50: ${ema50_atual} | Trailing Sugerido: ${trailing_sugerido} | "
                        f"AÇÃO: {acao}\n"
                    )
            except Exception as e:
                print(f"[ERRO] Falha ao auditar posição ativa {ticker_clean}: {e}")

    # ===================================================================
    # 5. MOTOR MATEMÁTICO: HOLY GRAIL (PULLBACK À EMA20)
    # ===================================================================
    def analisar_holy_grail(ativo_info):
        try:
            ticker = str(ativo_info.get("ticker", "")).strip().upper().replace(".", "-")
            nome_empresa = ativo_info.get("nome", "N/A")
            setor = str(ativo_info.get("setor") or ativo_info.get("setorAtivo") or ativo_info.get("sector") or "Desconhecido").strip()
            rs_score = ativo_info.get("rs_score", "N/A")

            if not ticker or ticker == "#N/A" or ticker == "NONE": return None
            if ticker in tickers_ativos_set: return None 
            if ticker == "BRK-A": ticker = "BRK-B"

            if setor not in ["Desconhecido", "N/A", "", "NONE"] and setor.lower() in setores_ocupados:
                return None

            val_rs_num = limpar_float(rs_score)
            if val_rs_num is None or val_rs_num < regime_macro["rs_min"]:
                return None

            time.sleep(random.uniform(0.4, 0.9))

            alerta_earnings = "OK"
            max_52s = None
            try:
                ticker_obj = yf.Ticker(ticker, session=session)
                info_dados = ticker_obj.info
                if setor in ["Desconhecido", "N/A", "", "NONE"]:
                    setor = info_dados.get('sector', setor)
                max_52s = info_dados.get('fiftyTwoWeekHigh', None)

                calendario = ticker_obj.calendar
                if isinstance(calendario, dict) and 'Earnings Date' in calendario and len(calendario['Earnings Date']) > 0:
                    proxima_data = calendario['Earnings Date'][0]
                    if hasattr(proxima_data, 'date'): proxima_data = proxima_data.date()
                    dias_restantes = (proxima_data - datetime.now(ZoneInfo("Europe/Lisbon")).date()).days
                    if 0 <= dias_restantes <= 3:
                        alerta_earnings = f"PERIGO (em {dias_restantes} dias)"
            except Exception:
                pass

            # Veto duro no Python para Earnings iminentes, setores ocupados ou REITs
            if alerta_earnings.startswith("PERIGO"):
                return None
            if setor not in ["Desconhecido", "N/A", "", "NONE"] and setor.lower() in setores_ocupados:
                return None
            if setor and any(termo in str(setor).lower() for termo in ["real estate", "reit", "mortgage"]):
                return None

            df = pd.DataFrame()
            for tentativa_yf in range(3):
                try:
                    df = yf.download(ticker, period="1y", interval="1d", progress=False, session=session, timeout=15)
                    if not df.empty and len(df) >= 200:
                        break
                except Exception:
                    time.sleep(2)

            if df.empty or len(df) < 200: return None
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
            df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])
            if len(df) < 200: return None

            preco = float(df['Close'].iloc[-1])
            vol_sma50_check = float(df['Volume'].rolling(window=50).mean().iloc[-1])
            # Liquidez institucional: Preço >= $10 e Volume Médio 50d >= 300k
            if preco < 10.00 or vol_sma50_check < 300000: return None

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
            seca_volume = vol_atual < (vol_sma50 * 0.80)

            if trend_alta and pullback_valido and seca_volume:
                preco_rt = obter_preco_tempo_real(ticker, preco)
                maximo_hoje = float(ultimo['High'])
                maximo_ontem = float(df['High'].iloc[-2])
                
                entrada_gatilho = round(max(maximo_hoje, maximo_ontem) * 1.002, 2)

                # Se em pré-abertura o preço já disparou > 2.5% acima do gatilho, não perseguir
                if preco_rt > entrada_gatilho * 1.025:
                    return None

                stop_loss = round(min(minimo_hoje * 0.99, ema20 - atr), 2)
                risco = entrada_gatilho - stop_loss
                if risco <= 0: return None

                alvo_tp = round(entrada_gatilho + (risco * 2.5), 2) 

                if max_52s and max_52s > 0:
                    if alvo_tp > max_52s:
                        alvo_tp = round(max_52s, 2)
                        
                if alvo_tp <= entrada_gatilho + (risco * 1.3):
                    alvo_tp = round(entrada_gatilho + (risco * 1.5), 2)
                
                # Dimensionamento pelo RISCO REAL (Gatilho - Stop) respeitando o regime macro
                qtd_calc = round(risco_ajustado_usd / risco, 2)
                if qtd_calc <= 0: return None

                qtd_acoes = qtd_calc
                val_calc = entrada_gatilho * qtd_acoes
                valor_investir = f"~${val_calc:.2f} USD"
                estado = f"HOLY GRAIL PULLBACK - Retração à EMA20 ({regime_macro['modo']})"
                
                def limpa(v): 
                    try: return round(float(v), 2)
                    except Exception: return "N/A"
                
                linha_comboio = (
                    f"{ticker},Nome: {nome_empresa},Setor: {setor},Preço: {limpa(preco_rt)},"
                    f"RS Score: {rs_score} (🔥 ELITE - Liderança Pura),"
                    f"ADX(14): {limpa(adx)},EMA20: {limpa(ema20)},"
                    f"Gatilho Compra (Buy Stop): {limpa(entrada_gatilho)},"
                    f"Stop Loss: {limpa(stop_loss)},Alvo TP: {limpa(alvo_tp)},"
                    f"Estado: {estado},Qtd: {qtd_acoes},ValorInvestir: {valor_investir},Earnings: {alerta_earnings},"
                    f"Data: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
                )

                return {
                    "ticker": ticker,
                    "setor": setor,
                    "adx": adx,
                    "rs": val_rs_num,
                    "comboio_str": linha_comboio
                }
            return None
        except Exception as e:
            print(f"[ERRO] Falha ao processar ativo {ativo_info.get('ticker')}: {e}")
            return None

    candidatos_hg = []
    total_analisados = 0
    if regime_macro["autorizado"]:
        for ativo_info in ativos_sheets:
            ticker = ativo_info.get("ticker")
            if not ticker or ticker == "#N/A": continue
            total_analisados += 1
            res = analisar_holy_grail(ativo_info)
            if res: candidatos_hg.append(res)

    # Ordena pela maior força direcional (ADX) e limita a 1 pullback por setor livre
    candidatos_hg = sorted(candidatos_hg, key=lambda k: (k['rs'], k['adx']), reverse=True)
    ativos_acionados = []
    setores_novos_usados = set()
    for item in candidatos_hg:
        s_key = item["setor"].lower()
        if s_key not in setores_novos_usados:
            ativos_acionados.append(item)
            if s_key not in ["desconhecido", "n/a", ""]:
                setores_novos_usados.add(s_key)

    prompt_ia = """MODO ESTRATÉGICO: PULLBACKS DE LIDERANÇA (HOLY GRAIL - LINDA RASCHKE)
O teu mandato é auditar ações de força relativa ELITE (RS >= 80) que sofreram um recuo (pullback) de curto prazo à Média Móvel Exponencial (EMA) de 20 períodos, apresentando seca de volume e tendência principal robusta (ADX forte).

REGRAS ESTRITAS:
1. Recomenda SEMPRE ordens pendentes "Buy Stop" no Gatilho de Compra estipulado (confirmação da retomada da tendência).
2. Respeita a gestão dinâmica das posições ativas (ATIVA_M10 / ATIVA_SWING): o Stop Loss nunca desce; se o Trailing Sugerido (EMA20 - ATR) for superior ao Stop Atual, instrui a subida imediata do Stop.
3. LEMBRETE OPERACIONAL: Assim que uma ordem Buy Stop for executada na corretora, altera o estado no Google Sheets para 'ATIVA_M10' para iniciar o rastreio dinâmico pela EMA20."""
    
    bloco = (
        f"📊 RELATÓRIO PULLBACKS DE LIDERANÇA (HOLY GRAIL) 🏆\n"
        f"🌐 Filtro Macro: {regime_macro['msg']}\n"
        f"💰 Risco Configurado por Trade: ${risco_ajustado_usd:.2f} USD (Base: ${risco_base_usd:.2f} | Fator: {int(regime_macro['fator_risco']*100)}%)\n\n"
        f"{prompt_ia}\n\n--------------------------------------------------\n"
    )
    
    if bloco_posicoes_ativas:
        bloco += "GESTÃO DE POSIÇÕES ATIVAS (ATIVA_M10 / ATIVA_SWING):\n\n"
        bloco += bloco_posicoes_ativas
        bloco += "--------------------------------------------------\n\n"

    if not regime_macro["autorizado"]:
        bloco += f"🛡️ [MODO DEFENSIVO] Novas entradas Holy Grail bloqueadas hoje ({regime_macro['msg']}).\n"
    elif not ativos_acionados:
        bloco += "[SEM SINAIS PULLBACK] - Nenhum ativo de Elite encontra-se num ponto ótimo de retração à EMA20 hoje.\n"
    else:
        bloco += "ALVOS DE COMPRA EM PULLBACK:\n\n"
        for item in ativos_acionados:
            bloco += item["comboio_str"] + "\n"
            
    with open("comboio_holygrail_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco)
        
    enviar_email(bloco)

    # ===================================================================
    # 6. NOTIFICAÇÃO TELEGRAM (DEBUG, NOVO SINAL OU ALERTA DE POSIÇÃO ATIVA)
    # ===================================================================
    debug_telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

    if debug_telegram_ativado or len(ativos_acionados) > 0 or alerta_gestao_urgente:
        print("A enviar notificação para o Telegram via função modular...")
        total_acionados = len(ativos_acionados)
        mensagem_debug = (
            f"10 🏆 *MOTOR HOLY GRAIL (PULLBACKS)*\n\n"
            f"🔍 Execução concluída ({regime_macro['modo']}).\n"
            f"📊 Ativos analisados: *{total_analisados}* | Novos Pullbacks: *{total_acionados}* | Em Gestão: *{qtd_posicoes_auditadas}*\n"
            f"✉️ Relatório e auditoria enviados por e-mail."
        )
        enviar_alerta(mensagem_debug)

if __name__ == "__main__":
    executar_motor()
