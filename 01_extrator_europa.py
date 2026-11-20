# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR DE BREAKOUTS (EUROPA)
# ===================================================================================
from datetime import datetime
from zoneinfo import ZoneInfo
import yfinance as yf
import pandas_ta as ta
import pandas as pd
import requests
import os
import sys
import smtplib
import json
import numpy as np
import time
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import warnings
warnings.filterwarnings("ignore")

# Importação da função modular de notificação do Telegram
from F01_notificador_telegram import enviar_alerta

# ===================================================================
# BYPASS SESSÃO YAHOO FINANCE (PARA GITHUB ACTIONS)
# ===================================================================
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

# ===================================================================
# 0.1 TRAVA DE FIM DE SEMANA (Não corre ao Sábado e Domingo)
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O mercado está fechado. O Agente vai descansar.")
    # sys.exit(0)

hoje_e_sexta = "SIM" if dia_da_semana == 4 else "NÃO"

# ===================================================================
# 0. CONFIGURAÇÕES E CREDENCIAIS (Lidas do GitHub Secrets)
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")
NOME_ABA_EUROPA = "Analise Compra EU"

if EMAIL_USER:
    EMAIL_USER = EMAIL_USER.strip()
if EMAIL_PASS:
    EMAIL_PASS = EMAIL_PASS.strip()

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

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
# 1. FUNÇÕES DE REDE, CÂMBIO E REGIME MACRO (EUROPA + US)
# ===================================================================
def obter_taxas_cambio_usd():
    """Obtém taxas de conversão para converter risco USD na moeda local do ativo europeu."""
    taxas = {"USD": 1.0, "EUR": 1.10, "GBP": 1.28, "CHF": 1.15, "SEK": 0.095, "DKK": 0.147}
    pares = {"EUR": "EURUSD=X", "GBP": "GBPUSD=X", "CHF": "CHFUSD=X", "SEK": "SEKUSD=X", "DKK": "DKKUSD=X"}
    for moeda, par in pares.items():
        try:
            df_fx = yf.download(par, period="5d", interval="1d", progress=False, session=session)
            if not df_fx.empty:
                if isinstance(df_fx.columns, pd.MultiIndex):
                    df_fx.columns = df_fx.columns.droplevel(1)
                val = float(df_fx['Close'].dropna().iloc[-1])
                if val > 0:
                    taxas[moeda] = val
        except Exception:
            pass
    return taxas

def moeda_por_ticker_eu(ticker):
    if ticker.endswith(".L"):
        return "GBP"
    if ticker.endswith(".SW"):
        return "CHF"
    if ticker.endswith(".ST"):
        return "SEK"
    if ticker.endswith(".CO"):
        return "DKK"
    return "EUR"

def verificar_regime_mercado_europa():
    """
    Avalia o regime combinado Europa (^STOXX50E) + Global (SPY) + VIX:
    - Expansão: TP 2.0R | RS >= 70 | Fator Lote 1.0 (0.5 à sexta-feira ou VIX > 23)
    - Corretivo: TP 1.5R | RS >= 80 | Fator Lote 0.5 (0.35 à sexta-feira ou VIX > 23)
    - Baixista / Pânico: Bloqueia novas entradas europeias
    """
    regime_default = {
        "autorizado": True,
        "modo": "EXPANSAO",
        "tp_mult": 2.0,
        "rs_min": 70.0,
        "fator_risco": 0.5 if hoje_e_sexta == "SIM" else 1.0,
        "msg": "Dados macro insuficientes (autorizado em modo Expansão)."
    }
    try:
        df_eu = yf.download("^STOXX50E", period="1y", interval="1d", progress=False, session=session)
        if df_eu.empty or len(df_eu) < 200:
            df_eu = yf.download("FEZ", period="1y", interval="1d", progress=False, session=session)

        df_spy = yf.download("SPY", period="1y", interval="1d", progress=False, session=session)

        if df_eu.empty or len(df_eu) < 200 or df_spy.empty or len(df_spy) < 200:
            return regime_default

        if isinstance(df_eu.columns, pd.MultiIndex): df_eu.columns = df_eu.columns.droplevel(1)
        if isinstance(df_spy.columns, pd.MultiIndex): df_spy.columns = df_spy.columns.droplevel(1)

        eu_close = float(df_eu['Close'].iloc[-1])
        eu_prev = float(df_eu['Close'].iloc[-2])
        eu_sma200 = float(df_eu['Close'].rolling(200).mean().iloc[-1])
        eu_ema20 = float(df_eu['Close'].ewm(span=20, adjust=False).mean().iloc[-1])
        eu_var = ((eu_close - eu_prev) / eu_prev) * 100

        spy_close = float(df_spy['Close'].iloc[-1])
        spy_prev = float(df_spy['Close'].iloc[-2])
        spy_sma200 = float(df_spy['Close'].rolling(200).mean().iloc[-1])
        spy_ema20 = float(df_spy['Close'].ewm(span=20, adjust=False).mean().iloc[-1])
        spy_var = ((spy_close - spy_prev) / spy_prev) * 100

        vix_atual = None
        try:
            df_vix = yf.download("^VIX", period="5d", interval="1d", progress=False, session=session)
            if not df_vix.empty:
                if isinstance(df_vix.columns, pd.MultiIndex): df_vix.columns = df_vix.columns.droplevel(1)
                vix_atual = float(df_vix['Close'].iloc[-1])
        except Exception:
            pass

        tag_vix = f" | VIX: {vix_atual:.2f}" if vix_atual is not None else ""
        tag_sexta = " | Sexta-Feira (-50% Lote)" if hoje_e_sexta == "SIM" else ""

        if eu_var <= -1.50 or spy_var <= -1.50:
            return {
                "autorizado": False,
                "modo": "PANICO_DIARIO",
                "tp_mult": 1.5,
                "rs_min": 85.0,
                "fator_risco": 0.0,
                "msg": f"Queda acentuada nos índices (STOXX50E: {eu_var:+.2f}% | SPY: {spy_var:+.2f}%){tag_vix}."
            }

        if eu_close < eu_sma200 or spy_close < spy_sma200:
            return {
                "autorizado": False,
                "modo": "BAIXISTA",
                "tp_mult": 1.5,
                "rs_min": 85.0,
                "fator_risco": 0.0,
                "msg": (
                    f"Regime Baixista de Longo Prazo (STOXX50E: {eu_close:.0f} vs SMA200 {eu_sma200:.0f} | "
                    f"SPY: ${spy_close:.2f} vs SMA200 ${spy_sma200:.2f}){tag_vix}."
                )
            }

        if vix_atual is not None and vix_atual > 30.0:
            return {
                "autorizado": False,
                "modo": "PANICO_VIX",
                "tp_mult": 1.5,
                "rs_min": 85.0,
                "fator_risco": 0.0,
                "msg": f"VIX em pânico sistémico ({vix_atual:.2f} > 30.00)."
            }

        # Regime Corretivo / Lateral se Europa ou US perderam a EMA 20
        if eu_close < eu_ema20 or spy_close < spy_ema20:
            fator = 0.35 if (hoje_e_sexta == "SIM" or (vix_atual is not None and vix_atual > 23.0)) else 0.50
            return {
                "autorizado": True,
                "modo": "CORRETIVO",
                "tp_mult": 1.5,
                "rs_min": 80.0,
                "fator_risco": fator,
                "msg": (
                    f"Regime Corretivo/Lateral (STOXX50E: {eu_close:.0f} [{eu_var:+.2f}%] | "
                    f"SPY: ${spy_close:.2f} [{spy_var:+.2f}%]{tag_vix}{tag_sexta}) — Alvo 1.5R | RS >= 80 | Lote {int(fator*100)}%."
                )
            }

        fator = 0.50 if (hoje_e_sexta == "SIM" or (vix_atual is not None and vix_atual > 23.0)) else 1.0
        return {
            "autorizado": True,
            "modo": "EXPANSAO",
            "tp_mult": 2.0,
            "rs_min": 70.0,
            "fator_risco": fator,
            "msg": (
                f"Regime em Expansão (STOXX50E: {eu_close:.0f} > EMA20 > SMA200 | "
                f"SPY: ${spy_close:.2f} > EMA20 > SMA200{tag_vix}{tag_sexta}) — Alvo 2.0R | Lote {int(fator*100)}%."
            )
        }
    except Exception as e:
        regime_default["msg"] = f"Aviso Macro EU: {e}"
        return regime_default

def enviar_email_para_agente_ia(relatorio_texto, assunto="🇪🇺🎯 tradingRelatorioIA Europa 🛡️"):
    print(f"\nA enviar email para o Agente IA (Assunto: '{assunto}')...")
    
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] Credenciais de email em falta. A saltar envio.")
        return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = assunto
    msg.attach(MIMEText(relatorio_texto, 'plain', 'utf-8'))
    
    max_tentativas = 3
    for tentativa in range(max_tentativas):
        try:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
            server.quit()
            print(f"[SUCESSO] Email enviado na tentativa {tentativa + 1}!")
            break
        except Exception as e:
            print(f"[ERRO] Falha ao enviar o email (tentativa {tentativa + 1} de {max_tentativas}): {e}")
            if tentativa < max_tentativas - 1:
                time.sleep(5)
            else:
                print("[ERRO CRÍTICO] Falha definitiva no envio de email.")

# ===================================================================
# 2. BUSCAR A WATCHLIST, POSIÇÕES ATIVAS E CONFIGS (Google Sheets via Webhook)
# ===================================================================
print(f"A carregar a Watchlist, Posições Ativas e Configurações da Europa (Aba: {NOME_ABA_EUROPA})...")
ativos_data = []
posicoes_ativas = {}
configs = {}
try:
    url_get = f"{WEBHOOK_URL}?aba={NOME_ABA_EUROPA}"
    resposta_webhook = requests.get(url_get, timeout=20)
    if resposta_webhook.status_code == 200:
        dados_webhook = resposta_webhook.json()
        if isinstance(dados_webhook, dict) and "ativos" in dados_webhook:
            ativos_data = dados_webhook.get("ativos", [])
            posicoes_ativas = dados_webhook.get("posicoesAtivas", {}) or {}
            configs = dados_webhook.get("configs", {})
        elif isinstance(dados_webhook, list):
            ativos_data = dados_webhook

        print(f"[SUCESSO] {len(ativos_data)} ativos europeus carregados da Watchlist.")
        print(f"[SUCESSO] {len(posicoes_ativas)} posições ativas detetadas no Diário de Bordo.")
    else:
        print(f"[ERRO] Falha ao descarregar dados: {resposta_webhook.status_code}")
except Exception as e:
    print(f"[ERRO CRÍTICO] Falha de comunicação com Sheets: {e}")

# ===================================================================
# LEITURA DINÂMICA DAS CONFIGURAÇÕES DE RISCO & CÂMBIO
# ===================================================================
capital_total_conta = limpar_float(configs.get("CAPITAL_TOTAL_CONTA")) or 10400.00
alvo_volatilidade_anual = limpar_float(configs.get("ALVO_VOLATILIDADE_ANUAL")) or 0.05
risco_fixo_usd = limpar_float(configs.get("RISCO_MAXIMO_USD"))

volatilidade_alvo_diaria_usd = (capital_total_conta * alvo_volatilidade_anual) / 16.0
risco_base_usd = risco_fixo_usd if (risco_fixo_usd and risco_fixo_usd > 0) else volatilidade_alvo_diaria_usd
multiplicador_trailing_ts = limpar_float(configs.get("TRAILING_MULTIPLIER")) or 1.5

regime_macro = verificar_regime_mercado_europa()
taxas_fx_usd = obter_taxas_cambio_usd()

risco_ajustado_usd = round(risco_base_usd * regime_macro["fator_risco"], 2) if regime_macro["autorizado"] else 0.0
racio_tp_base = regime_macro["tp_mult"]

print(f"[CONFIG] Capital Total: ${capital_total_conta:,.2f} | Risco Base: ${risco_base_usd:.2f} | Risco Ajustado ({regime_macro['modo']}): ${risco_ajustado_usd:.2f} USD")
print(f"[MACRO] {regime_macro['msg']}\n")

# Proteção anti-correlação setorial
mapa_setores_watchlist = {}
for item in ativos_data:
    t_item = str(item.get("ticker", "")).strip().upper()
    s_item = str(item.get("setor") or item.get("setorAtivo") or item.get("sector") or "").strip()
    if t_item and s_item and s_item not in ["Europa", "Desconhecido", "N/A", "NONE"]:
        mapa_setores_watchlist[t_item] = s_item

setores_ocupados = set()
for chave_pos, info in posicoes_ativas.items():
    if isinstance(info, dict) and str(info.get("status", "")).strip().upper().startswith("ATIVA"):
        t_pos = chave_pos.strip().upper()
        setor_pos = str(info.get("setor") or mapa_setores_watchlist.get(t_pos, "")).strip()
        if setor_pos and setor_pos not in ["Europa", "Desconhecido", "N/A", "NONE"]:
            setores_ocupados.add(setor_pos.lower())

# ===================================================================
# 3. MOTOR MATEMÁTICO V3 (SEMPRE ATUALIZA SHEETS + FILTRA NOVOS SINAIS)
# ===================================================================
veto_macro_ativo = not regime_macro["autorizado"]
motivo_veto = regime_macro["msg"]
dados_temporarios = []

if ativos_data:
    for ativo_info in ativos_data:
        ticker = str(ativo_info.get("ticker", "")).strip().upper()
        nome_empresa = ativo_info.get("nome", "N/A")
        rs_score = ativo_info.get("rs_score", "N/A")
        setor = str(ativo_info.get("setor", "Europa")).strip()
        
        if not ticker or ticker == "#N/A" or ticker == "NONE":
            continue
        
        try:
            time.sleep(random.uniform(0.3, 0.7))
            df = yf.download(ticker, period="1y", interval="1d", progress=False, session=session)
            if df.empty:
                print(f"[AVISO] Sem dados para {ticker}.")
                continue
                
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)

            df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])
            if df.empty or len(df) < 50:
                continue

            alerta_earnings = "OK"
            try:
                ticker_obj = yf.Ticker(ticker, session=session)
                if setor in ["Europa", "Desconhecido", "N/A", "", "NONE"]:
                    setor_yf = ticker_obj.info.get('sector')
                    if setor_yf:
                        setor = setor_yf

                calendario = ticker_obj.calendar
                if isinstance(calendario, dict) and 'Earnings Date' in calendario and len(calendario['Earnings Date']) > 0:
                    proxima_data = calendario['Earnings Date'][0]
                    if hasattr(proxima_data, 'date'):
                        proxima_data = proxima_data.date()
                    
                    hoje = datetime.now(ZoneInfo("Europe/Lisbon")).date()
                    dias_restantes = (proxima_data - hoje).days
                    if 0 <= dias_restantes <= 3:
                        alerta_earnings = f"PERIGO (em {dias_restantes} dias)"
            except Exception:
                pass

            df.ta.rsi(length=14, append=True)
            df.ta.adx(length=14, append=True)
            df.ta.atr(length=14, append=True)
            df.ta.sma(length=200, append=True)
            df.ta.sma(length=20, append=True)
            df.ta.mom(length=14, append=True)
            df.ta.ema(length=9, append=True)

            media_volume_20 = df['Volume'].rolling(window=20).mean()
            df['RVOL'] = df['Volume'] / media_volume_20

            df = df.dropna(subset=['RSI_14', 'ADX_14', 'ATRr_14', 'SMA_20', 'EMA_9', 'MOM_14'])
            if df.empty: continue

            ultimo_dia = df.iloc[-1]
            dia_anterior = df.iloc[-2]

            preco = float(ultimo_dia['Close'])
            preco_anterior = float(dia_anterior['Close'])
            var_perc = ((preco - preco_anterior) / preco_anterior) * 100
            
            sma20 = float(ultimo_dia['SMA_20'])
            sma200 = float(ultimo_dia['SMA_200']) if 'SMA_200' in ultimo_dia and pd.notna(ultimo_dia['SMA_200']) else 0.0
            dist_mm20 = ((preco - sma20) / sma20) * 100
            
            ema9 = float(ultimo_dia['EMA_9'])
            ema9_anterior = float(dia_anterior['EMA_9'])
            
            cruzou_ema9 = (preco > ema9) and (preco_anterior <= ema9_anterior) if pd.notna(ema9) and pd.notna(ema9_anterior) else False
            acima_ema9 = preco > ema9 if pd.notna(ema9) else False

            rvol = float(ultimo_dia['RVOL'])
            adx = float(ultimo_dia['ADX_14'])
            rsi = float(ultimo_dia['RSI_14'])
            atr = float(ultimo_dia['ATRr_14'])
            momentum = float(ultimo_dia['MOM_14'])

            atr_perc = round((atr / preco) * 100, 2) if pd.notna(atr) and pd.notna(preco) and preco > 0 else "N/A"

            recomendacao = "Observar"
            preco_entrada = "N/A"
            preco_stop = "N/A"
            preco_tp = "N/A"
            preco_be = "N/A"
            qtd_acoes = "N/A"
            multiplicador_atr = 1.0

            trailing_base = preco - (atr * multiplicador_trailing_ts) if pd.notna(preco) and pd.notna(atr) else "N/A"
            trailing_final = round(trailing_base, 2) if trailing_base != "N/A" else "N/A"

            preco_caiu_hoje = preco < preco_anterior if pd.notna(preco) and pd.notna(preco_anterior) else False
            volume_despejo = rvol > 1.20 if pd.notna(rvol) else False

            val_rs_num = limpar_float(rs_score)
            rs_aprovado = (val_rs_num is not None and val_rs_num >= regime_macro["rs_min"])
            tendencia_lp_ok = (sma200 > 0 and preco > sma200)
            ja_em_carteira = (ticker in posicoes_ativas)
            setor_bloqueado = (setor not in ["Europa", "Desconhecido", "N/A", ""] and setor.lower() in setores_ocupados)
            perigo_earnings = alerta_earnings.startswith("PERIGO")

            if (veto_macro_ativo or not rs_aprovado or not tendencia_lp_ok or ja_em_carteira or 
                setor_bloqueado or perigo_earnings or pd.isna(momentum) or pd.isna(adx) or 
                pd.isna(rvol) or pd.isna(rsi) or pd.isna(dist_mm20) or pd.isna(atr) or
                (preco_caiu_hoje and volume_despejo) or (momentum <= 0.5)):
                recomendacao = "Observar"
            elif var_perc > 0 and adx < 25 and not cruzou_ema9:
                recomendacao = "Aguardar Recuo"
                preco_entrada = round(preco - (atr * 0.4), 2)
                multiplicador_atr = 1.0
            elif cruzou_ema9 and rvol > 1.00 and momentum > 0.50 and rsi > 50 and dist_mm20 <= 3.00:
                recomendacao = "Ignicao EMA9"
                preco_entrada = round(preco - (atr * 0.1), 2)
                multiplicador_atr = 1.2
            elif var_perc > 0 and adx >= 30 and rvol >= 1.20 and (55.00 <= rsi <= 72.00) and (0.00 <= dist_mm20 <= 3.00) and momentum > 1.50 and acima_ema9:
                recomendacao = "Forca Consolidada"
                preco_entrada = round(preco - (atr * 0.1), 2)
                multiplicador_atr = 1.3 
            elif adx >= 25 and rvol >= 1.00 and (50.00 <= rsi <= 75.00) and (-1.00 <= dist_mm20 <= 3.00) and momentum > 0.50 and acima_ema9:
                recomendacao = "Alerta Iminente"
                preco_entrada = round(preco - (atr * 0.2), 2)
                multiplicador_atr = 1.2
            else:
                recomendacao = "Observar"

            # FILTRO DE SEGURANÇA: PREÇO FUGIDO (GAP > 1% DA ENTRADA)
            if recomendacao != "Observar" and isinstance(preco_entrada, (int, float)):
                variacao_pct_entrada = ((preco - preco_entrada) / preco_entrada) * 100
                if variacao_pct_entrada > 1.0:
                    recomendacao = "Observar"
                    preco_entrada = "N/A"

            moeda_local = moeda_por_ticker_eu(ticker)
            taxa_fx = taxas_fx_usd.get(moeda_local, 1.10)
            # Londres (.L) cota em pence (GBp = 0.01 GBP)
            fator_pence = 0.01 if ticker.endswith(".L") else 1.0
            risco_moeda_local = (risco_ajustado_usd / taxa_fx) / fator_pence

            if recomendacao != "Observar" and preco_entrada != "N/A" and risco_moeda_local > 0:
                preco_stop_calc = preco_entrada - (atr * multiplicador_atr)
                if preco_stop_calc > sma20 and preco > sma20:
                    preco_stop_calc = sma20 * 0.995
                
                preco_stop = round(preco_stop_calc, 2)
                risco_por_acao = preco_entrada - preco_stop_calc
                
                if risco_por_acao > 0:
                    tp_calc = preco_entrada + (risco_por_acao * racio_tp_base)
                    preco_tp = round(tp_calc, 2)
                    qtd_calc = round(risco_moeda_local / risco_por_acao, 2)
                    
                    if qtd_calc <= 0:
                        recomendacao = "Observar"
                        qtd_acoes = "N/A"
                    else:
                        qtd_acoes = qtd_calc
                        preco_be = round(preco_entrada + (risco_por_acao * 0.8), 2)
                        trailing_final = round(max(trailing_base, preco_stop_calc), 2)

            data_atual = datetime.now(ZoneInfo("Europe/Lisbon")).strftime('%d/%m/%Y %H:%M:%S')

            if ticker in posicoes_ativas:
                pos_info = posicoes_ativas[ticker]
                status_pos = str(pos_info.get('status', 'ATIVA')).strip().upper()
                if status_pos in ['ATIVA_FAST', 'ATIVA_SWING']:
                    info_carteira = f"NÃO (Gerido pelo modelo {status_pos.replace('ATIVA_', '')} - {status_pos})"
                else:
                    info_carteira = f"SIM (Entrada: {pos_info.get('precoEntrada', 'N/A')}, StopAtual: {pos_info.get('stopAtual', 'N/A')}, Qtd: {pos_info.get('quantidade', 'N/A')})"
            else:
                info_carteira = "NÃO"

            def limpa(v):
                try:
                    if v == "N/A" or pd.isna(v): return "N/A"
                    val = float(v)
                    if np.isnan(val): return "N/A"
                    return round(val, 2)
                except Exception:
                    return "N/A"

            if val_rs_num is not None:
                if val_rs_num >= 80:
                    status_rs = "🔥 ELITE (RS >= 80 - Vento a Favor)"
                elif val_rs_num >= 70:
                    status_rs = "⚖️ FORTE (RS 70-79 - Acompanha o Mercado)"
                else:
                    status_rs = "⚠️ FRACO / LAGGARD (RS < 70 - Vento Contra)"
            else:
                status_rs = "❓ SEM DADO DE RS"

            dados_temporarios.append({
                "ticker": ticker,
                "nome": nome_empresa,
                "setor": setor,
                "moeda": moeda_local,
                "rs_score": rs_score,
                "status_rs": status_rs,
                "preco": limpa(preco),
                "dist_mm20": limpa(dist_mm20),
                "ema9": limpa(ema9),
                "momentum": limpa(momentum),
                "rsi": limpa(rsi),
                "adx": limpa(adx),
                "atr": limpa(atr),
                "atr_perc": limpa(atr_perc),
                "rvol": limpa(rvol),
                "estado": recomendacao,
                "entrada": round(preco_entrada, 2) if isinstance(preco_entrada, float) else preco_entrada,
                "stop": preco_stop,
                "tp": preco_tp,
                "be": preco_be,
                "qtd_bruta": qtd_acoes,
                "trailing": trailing_final,
                "earnings": alerta_earnings,
                "posicao_ativa": info_carteira,
                "data": data_atual
            })
            
            print(f"[OK] {ticker} analisado. Setor: {setor} | Estado: {recomendacao}")

        except Exception as e:
            print(f"[ERRO] Falha ao processar {ticker}: {e}")

# ===================================================================
# 4. FORMATAÇÃO DO COMBOIO & PREPARAÇÃO PARA SHEETS
# ===================================================================
tipo_lote = f"{int(regime_macro['fator_risco']*100)}% ({regime_macro['modo']})"
data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M")

# Filtra apenas os sinais acionáveis e limita a 1 entrada por setor livre
candidatos_acionaveis = [
    d for d in dados_temporarios
    if d["estado"] not in ["Observar", "Aguardar Recuo"] and d["qtd_bruta"] != "N/A"
]
candidatos_acionaveis = sorted(
    candidatos_acionaveis,
    key=lambda x: (limpar_float(x["rs_score"]) or 0.0, limpar_float(x["rvol"]) or 0.0),
    reverse=True
)

sinais_selecionados = []
setores_usados_hoje = set()
for item in candidatos_acionaveis:
    s_key = str(item["setor"]).strip().lower()
    if s_key not in setores_usados_hoje:
        sinais_selecionados.append(item)
        if s_key not in ["europa", "desconhecido", "n/a", ""]:
            setores_usados_hoje.add(s_key)

# Monta o relatório do comboio Europa
texto_comboio = (
    f"🇪🇺 RELATÓRIO DE TRADING - MOTOR EUROPA ({data_hoje})\n"
    f"==================================================================\n"
    f"🌐 Regime Macro: {regime_macro['msg']}\n"
    f"💰 Risco Configurado por Trade: ${risco_ajustado_usd:,.2f} USD (Base: ${risco_base_usd:,.2f} | Lote: {tipo_lote})\n"
    f"==================================================================\n\n"
)

if veto_macro_ativo:
    texto_comboio += f"🛡️ [MODO DEFENSIVO EUROPA] Novas compras bloqueadas hoje ({motivo_veto}).\n"
elif sinais_selecionados:
    texto_comboio += f"🎯 SINAIS DE ENTRADA ACIONÁVEIS EUROPA ({len(sinais_selecionados)}):\n\n"
    for s in sinais_selecionados:
        simbolo_moeda = "€" if s["moeda"] == "EUR" else ("£" if s["moeda"] == "GBP" else f"{s['moeda']} ")
        texto_comboio += (
            f"🔹 [{s['ticker']}] - {s['nome']} ({s['setor']}) | Moeda: {s['moeda']}\n"
            f"   - 📊 Setup: {s['estado']} | RS Score: {s['rs_score']} ({s['status_rs']})\n"
            f"   - 📈 Indicadores: Preço: {simbolo_moeda}{s['preco']} | RVOL: {s['rvol']}x | ADX: {s['adx']} | RSI: {s['rsi']}\n"
            f"   - 🔢 Plano de Execução: Entrada: {simbolo_moeda}{s['entrada']} | Stop Loss: {simbolo_moeda}{s['stop']} | Alvo ({racio_tp_base}R): {simbolo_moeda}{s['tp']} | BE (+0.8R): {simbolo_moeda}{s['be']}\n"
            f"   - 💰 Dimensionamento: Qtd: {s['qtd_bruta']} ações | Trailing Stop: {simbolo_moeda}{s['trailing']}\n"
            f"--------------------------------------------------\n"
        )
else:
    texto_comboio += "✅ Nenhum ativo europeu atingiu os critérios institucionais de entrada hoje.\n"

# Gravar ficheiro temporário para o Orquestrador
with open("comboio_europa_temp.txt", "w", encoding="utf-8") as f:
    f.write(texto_comboio)

print("\n" + texto_comboio)

# Atualizar a aba Analise Compra EU no Google Sheets via Webhook POST
if WEBHOOK_URL and dados_temporarios:
    try:
        payload_sheets = {
            "acao": "atualizarAnalise",
            "aba": NOME_ABA_EUROPA,
            "dados": dados_temporarios
        }
        resp_post = requests.post(WEBHOOK_URL, json=payload_sheets, timeout=25)
        print(f"[SHEETS] Atualização enviada para '{NOME_ABA_EUROPA}' (HTTP {resp_post.status_code}).")
    except Exception as e:
        print(f"[ERRO] Falha ao atualizar Google Sheets ({NOME_ABA_EUROPA}): {e}")

# Enviar e-mail sempre (incluindo em Modo Defensivo ou sem novos sinais)
assunto_eu = (
    f"🇪🇺🛡️ tradingRelatorioIA Europa - MODO DEFENSIVO ({datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')})"
    if veto_macro_ativo else
    f"🇪🇺🎯 tradingRelatorioIA Europa - {len(sinais_selecionados)} Sinal(is) ({datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')})"
)
enviar_email_para_agente_ia(texto_comboio, assunto=assunto_eu)

# ===================================================================
# 5. NOTIFICAÇÃO TELEGRAM (DEBUG OU NOVOS SINAIS EUROPA)
# ===================================================================
debug_telegram_ativado = str(configs.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

if debug_telegram_ativado or len(sinais_selecionados) > 0:
    print("A enviar notificação Europa para o Telegram via função modular...")
    lista_tickers_tg = ", ".join([s["ticker"] for s in sinais_selecionados]) if sinais_selecionados else "Nenhum"
    mensagem_tg = (
        f"🇪🇺 *MOTOR EUROPA (BREAKOUTS)*\n\n"
        f"🔍 Execução concluída ({regime_macro['modo']}).\n"
        f"📊 Analisados: *{len(dados_temporarios)}* | Sinais Acionáveis: *{len(sinais_selecionados)}* ({lista_tickers_tg})\n"
        f"💰 Risco/Trade: *${risco_ajustado_usd:.2f} USD*"
    )
    enviar_alerta(mensagem_tg)
