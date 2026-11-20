# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR FAST TREND (ROBERT CARVER)
# ===================================================================================
import pandas as pd
import yfinance as yf
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
    print("[INFO] Fim de semana detetado. O motor Carver vai descansar.")
    # sys.exit(0)

# ===================================================================
# 1. CONFIGURAÇÕES E CREDENCIAIS (GitHub Secrets)
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

# Máximo de 1 novo sinal por setor livre (evita concentração setorial)
MAX_NOVOS_SINAIS_POR_SETOR = 1

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
# 2. FUNÇÕES DE REDE & PREÇO EM TEMPO REAL
# ===================================================================
def buscar_dados_completos():
    print("A carregar a Watchlist, Posições Ativas e Configurações a partir do Google Sheets...")
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
                print(f"[ERRO] O Webhook não retornou um JSON válido. Resposta: {resp.text[:200]}")
                return [], {}, {}

            if isinstance(dados, dict):
                ativos = dados.get("ativos", [])
                posicoes = dados.get("posicoesAtivas", {}) or dados.get("posicoes", {})
                configs = dados.get("configs", {})
                return ativos, posicoes, configs
            elif isinstance(dados, list):
                return dados, {}, {}
                
        print(f"[AVISO] Webhook retornou status {resp.status_code}. Resposta: {resp.text[:200]}")
        return [], {}, {}
    except Exception as e:
        print(f"[ERRO CRÍTICO] Sheets: {e}")
        return [], {}, {}

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

def enviar_email_bruto(conteudo):
    print("\nA enviar o relatório de dados brutos do Carver para o Agente IA via email...")
    
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] Credenciais de email em falta. A saltar envio.")
        return

    if "@" not in EMAIL_USER or "." not in EMAIL_USER:
        print(f"[ERRO CRÍTICO] O e-mail configurado ('{EMAIL_USER}') não é um endereço válido.")
        return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = f"tradingRelatorioIA US - FAST TREND CARVER ({datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')})"
    msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
    
    max_tentativas = 3
    for tentativa in range(max_tentativas):
        try:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
            server.quit()
            print(f"[SUCESSO] Email bruto do Carver enviado na tentativa {tentativa + 1}!")
            break
        except Exception as e:
            print(f"[ERRO] Falha ao enviar o email (tentativa {tentativa + 1} de {max_tentativas}): {e}")
            if tentativa < max_tentativas - 1:
                time.sleep(5)
            else:
                print("[ERRO CRÍTICO] Falha definitiva no envio de email.")

# ===================================================================
# 3. FILTRO DE REGIME MACRO (S&P 500 / SPY + VIX)
# ===================================================================
def verificar_regime_macro():
    """
    Matriz Macro Institucional alinhada com o ecossistema:
    - Expansão (SPY > EMA20 > SMA200): Forecast >= 12.0 | RS >= 70 | Lote 100% (50% se VIX > 23)
    - Corretivo (SMA200 < SPY <= EMA20): Forecast >= 15.0 | RS >= 80 | Lote 50% (35% se VIX > 23)
    - Baixista / Queda <= -1.50% / VIX > 30: Bloqueia novas entradas
    """
    regime_default = {
        "autorizado": True,
        "status": "EXPANSAO",
        "fator_lote": 1.0,
        "min_forecast": 12.0,
        "rs_min": 70.0,
        "msg": "Dados SPY insuficientes (autorizado por defeito em modo Expansão)."
    }
    try:
        spy = yf.download("SPY", period="1y", interval="1d", progress=False, session=session)
        if spy.empty or len(spy) < 200:
            return regime_default
            
        if isinstance(spy.columns, pd.MultiIndex):
            spy.columns = spy.columns.droplevel(1)
            
        spy = spy.dropna(subset=['Close'])
        close_hoje = float(spy['Close'].iloc[-1])
        close_ontem = float(spy['Close'].iloc[-2])
        sma200 = float(spy['Close'].rolling(200).mean().iloc[-1])
        ema20 = float(spy['Close'].ewm(span=20, adjust=False).mean().iloc[-1])
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
            msg = f"SPY (${close_hoje:.2f}) abaixo da SMA200 (${sma200:.2f}). Regime Baixista{tag_vix}."
            print(f"[MACRO VETO] {msg}")
            return {"autorizado": False, "status": "BAIXISTA", "fator_lote": 0.0, "min_forecast": 15.0, "rs_min": 85.0, "msg": msg}

        if var_dia <= -1.50:
            msg = f"SPY em queda acentuada hoje ({var_dia:.2f}% <= -1.50%){tag_vix}. Novas entradas Carver bloqueadas."
            print(f"[MACRO VETO] {msg}")
            return {"autorizado": False, "status": "QUEDA_DIARIA", "fator_lote": 0.0, "min_forecast": 15.0, "rs_min": 85.0, "msg": msg}

        if vix_atual is not None and vix_atual > 30.0:
            msg = f"VIX em pânico sistémico ({vix_atual:.2f} > 30.00). Novas entradas Carver bloqueadas."
            print(f"[MACRO VETO] {msg}")
            return {"autorizado": False, "status": "PANICO_VIX", "fator_lote": 0.0, "min_forecast": 15.0, "rs_min": 85.0, "msg": msg}

        if close_hoje < ema20:
            fator = 0.35 if (vix_atual is not None and vix_atual > 23.0) else 0.50
            msg = (
                f"SPY em pullback/lateral (${close_hoje:.2f} < EMA20 ${ema20:.2f} | SMA200 ${sma200:.2f} | "
                f"Var: {var_dia:+.2f}%{tag_vix}) — Modo Tático: Forecast >= 15.0, RS >= 80 e Lote {int(fator*100)}%."
            )
            print(f"[MACRO CORRETIVO] {msg}")
            return {"autorizado": True, "status": "CORRETIVO", "fator_lote": fator, "min_forecast": 15.0, "rs_min": 80.0, "msg": msg}

        fator = 0.50 if (vix_atual is not None and vix_atual > 23.0) else 1.0
        msg = (
            f"SPY em Expansão (${close_hoje:.2f} > EMA20 ${ema20:.2f} > SMA200 ${sma200:.2f} | "
            f"Var: {var_dia:+.2f}%{tag_vix}) — Forecast >= 12.0 | RS >= 70 | Lote {int(fator*100)}%."
        )
        print(f"[MACRO EXPANSAO] {msg}")
        return {"autorizado": True, "status": "EXPANSAO", "fator_lote": fator, "min_forecast": 12.0, "rs_min": 70.0, "msg": msg}

    except Exception as e:
        print(f"[AVISO MACRO] Falha ao verificar regime do mercado: {e}. A usar parâmetros padrão.")
        return regime_default

# ===================================================================
# 4. MOTOR MATEMÁTICO: CÁLCULO NATIVO
# ===================================================================
def calcular_indicadores_tecnicos(ticker):
    try:
        time.sleep(random.uniform(0.3, 0.7))
        df = yf.download(ticker, period="1y", interval="1d", progress=False, session=session)
        if df.empty:
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])
        if df.empty or len(df) < 200:
            return None

        df['EMA_8'] = df['Close'].ewm(span=8, adjust=False).mean()
        df['EMA_32'] = df['Close'].ewm(span=32, adjust=False).mean()
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        df['VOL_MEDIO_20'] = df['Volume'].rolling(window=20).mean()

        high = df['High']
        low = df['Low']
        close = df['Close']
        
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['ATR_36'] = tr.rolling(window=36).mean()

        df = df.dropna(subset=['EMA_8', 'EMA_32', 'SMA_200', 'ATR_36', 'VOL_MEDIO_20'])
        if df.empty:
            return None

        ultimo = df.iloc[-1]
        return {
            "preco": float(ultimo['Close']),
            "ema8": float(ultimo['EMA_8']),
            "ema32": float(ultimo['EMA_32']),
            "sma200": float(ultimo['SMA_200']),
            "atr36": float(ultimo['ATR_36']),
            "vol_medio_20": float(ultimo['VOL_MEDIO_20'])
        }
    except Exception as e:
        print(f"[ERRO] Falha ao descarregar dados para {ticker}: {e}")
        return None

def verificar_earnings_iminentes(ticker_obj):
    try:
        calendario = ticker_obj.calendar
        if isinstance(calendario, dict) and 'Earnings Date' in calendario and len(calendario['Earnings Date']) > 0:
            proxima_data = calendario['Earnings Date'][0]
            if hasattr(proxima_data, 'date'):
                proxima_data = proxima_data.date()
            hoje = datetime.now(ZoneInfo("Europe/Lisbon")).date()
            dias_restantes = (proxima_data - hoje).days
            if 0 <= dias_restantes <= 3:
                return f"PERIGO (em {dias_restantes} dias)"
    except Exception:
        pass
    return "OK"

def analisar_tendencia_carver(ativo_info, risco_base_usd, info_macro, setores_ocupados):
    ticker = str(ativo_info.get("ticker", "")).strip().upper().replace(".", "-")
    nome_empresa = ativo_info.get("nome", "N/A")
    setor = str(ativo_info.get("setor") or ativo_info.get("setorAtivo") or ativo_info.get("sector") or "Desconhecido").strip()
    rs_score = ativo_info.get("rs_score", "N/A")

    if not ticker or ticker == "#N/A" or ticker == "NONE":
        return None

    if ticker == "BRK-A":
        ticker = "BRK-B"

    if setor not in ["Desconhecido", "N/A", "", "NONE"] and setor.lower() in setores_ocupados:
        return None

    val_rs_num = limpar_float(rs_score)
    if val_rs_num is not None and val_rs_num < info_macro["rs_min"]:
        return None

    ind = calcular_indicadores_tecnicos(ticker)
    if not ind: return None
    
    preco, ema8, ema32, sma200, atr36, vol_medio_20 = (
        ind['preco'], ind['ema8'], ind['ema32'], ind['sma200'], ind['atr36'], ind['vol_medio_20']
    )
    if pd.isna(preco) or pd.isna(ema8) or pd.isna(ema32) or pd.isna(atr36) or atr36 <= 0:
        return None

    # Exige liquidez institucional (Preço >= $10 e Volume Médio 20d >= 300k) e tendência primária > SMA200
    if preco < 10.0 or vol_medio_20 < 300000 or preco <= sma200:
        return None

    diferenca_bruta = ema8 - ema32
    forecast_carver = (diferenca_bruta / atr36) * 5.0
    
    min_forecast = info_macro.get("min_forecast", 12.0)
    if forecast_carver < min_forecast:
        return None

    # Verifica setor e earnings antes de aprovar nova entrada
    alerta_earnings = "OK"
    try:
        ticker_obj = yf.Ticker(ticker, session=session)
        if setor in ["Desconhecido", "N/A", "", "NONE"]:
            setor_yf = ticker_obj.info.get('sector')
            if setor_yf:
                setor = setor_yf
        alerta_earnings = verificar_earnings_iminentes(ticker_obj)
    except Exception:
        pass

    if setor not in ["Desconhecido", "N/A", "", "NONE"] and setor.lower() in setores_ocupados:
        return None
    if alerta_earnings.startswith("PERIGO"):
        print(f"[VETO EARNINGS] {ticker} ignorado por apresentar {alerta_earnings}.")
        return None

    preco_rt = obter_preco_tempo_real(ticker, preco)
    # Se o preço caiu mais de 1.5% abaixo do fecho em pré-abertura, aguardar estabilização
    if preco_rt < preco * 0.985:
        return None

    # Escala de convicção controlada entre 0.75x e 1.0x do risco do regime (nunca ultrapassa o orçamento)
    escala_conviccao = min(max(forecast_carver / 20.0, 0.75), 1.0)
    fator_lote = info_macro.get("fator_lote", 1.0)
    risco_alocado_usd = round(risco_base_usd * fator_lote * escala_conviccao, 2)

    estado_str = f"FAST TREND - Carver Momentum ({info_macro['status']})"
    entrada = round(max(preco, preco_rt), 2)
    stop_loss = round(entrada - (atr36 * 1.5), 2)
    risco_por_acao = entrada - stop_loss
    
    if risco_por_acao <= 0 or risco_alocado_usd <= 0:
        return None

    alvo_tp = round(entrada + (risco_por_acao * 3.0), 2)
    qtd_acoes = round(risco_alocado_usd / risco_por_acao, 2)

    if qtd_acoes <= 0:
        return None

    val_calc = entrada * qtd_acoes
    label_lote = f"Lote {int(fator_lote*100)}% | Convicção {int(escala_conviccao*100)}%"
    valor_investir = f"~${val_calc:.2f} USD ({label_lote})"

    def limpa(v):
        try:
            return round(float(v), 2)
        except Exception:
            return "N/A"

    if val_rs_num is not None:
        if val_rs_num >= 80:
            status_rs = "🔥 ELITE (RS >= 80 - Vento a Favor)"
        else:
            status_rs = "⚖️ FORTE (RS 70-79 - Acompanha o Mercado)"
    else:
        status_rs = "❓ SEM DADO DE RS"

    linha_comboio = (
        f"{ticker},Nome: {nome_empresa},Setor: {setor},Preço: {limpa(preco_rt)},"
        f"RS Score: {rs_score} ({status_rs}),"
        f"EMA8: {limpa(ema8)},EMA32: {limpa(ema32)},ATR36: {limpa(atr36)},"
        f"Forecast: {limpa(forecast_carver)},RiscoAlocado: ${risco_alocado_usd:.2f},"
        f"Estado: {estado_str},Ordem: BUY STOP,Entrada: {limpa(entrada)},Stop: {limpa(stop_loss)},"
        f"Take-Profit (3.0R): {limpa(alvo_tp)},Qtd: {qtd_acoes},ValorInvestir: {valor_investir},"
        f"Data: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
    )

    return {
        "ticker": ticker,
        "setor": setor,
        "forecast": forecast_carver,
        "comboio_str": linha_comboio
    }

def monitorizar_posicao_ativa(ticker, nome_empresa, status_atual, dados_posicao):
    ticker_clean = "BRK-B" if ticker == "BRK-A" else ticker.strip().upper().replace(".", "-")

    ind = calcular_indicadores_tecnicos(ticker_clean)
    if not ind: return None
    
    preco, ema8, ema32, atr36 = ind['preco'], ind['ema8'], ind['ema32'], ind['atr36']
    
    if pd.isna(preco) or pd.isna(ema8) or pd.isna(ema32) or pd.isna(atr36):
        print(f"[AVISO] Valores inválidos/NaN detetados para {ticker_clean}. Monitorização ignorada hoje.")
        return None

    preco_rt = obter_preco_tempo_real(ticker_clean, preco)
    preco_ref = max(preco, preco_rt)

    alerta_earnings = "OK"
    try:
        ticker_obj = yf.Ticker(ticker_clean, session=session)
        alerta_earnings = verificar_earnings_iminentes(ticker_obj)
    except Exception:
        pass

    trailing_stop_calculado = round(preco_ref - (atr36 * 1.5), 2)
    
    preco_entrada = dados_posicao.get("precoEntrada", "N/A")
    quantidade = dados_posicao.get("quantidade", "N/A")
    stop_atual_registado = dados_posicao.get("stopAtual", None)
    
    stop_final = trailing_stop_calculado
    subiu_stop = False
    instrucao_risco = f"Atualizar stop para {trailing_stop_calculado}"
    
    stop_atual_val = limpar_float(stop_atual_registado)
    if stop_atual_val is not None:
        if stop_atual_val >= trailing_stop_calculado:
            stop_final = stop_atual_val
            instrucao_risco = (
                f"MANTER o Stop atual em {stop_atual_val} (o cálculo matemático de hoje ({trailing_stop_calculado}) "
                f"é inferior, aplicando-se a regra de inércia do trailing stop)."
            )
        else:
            subiu_stop = True
            instrucao_risco = f"SUBIR o Stop do valor anterior ({stop_atual_val}) para o novo patamar ({trailing_stop_calculado})."

    if preco_rt <= stop_final:
        instrucao_risco = f"🚨 STOP ATINGIDO (${preco_rt:.2f} <= ${stop_final:.2f})! LIQUIDAR POSIÇÃO IMEDIATAMENTE."
        subiu_stop = True

    if "PERIGO" in alerta_earnings:
        instrucao_risco += f" | ⚠️ ALERTA CRÍTICO: EARNINGS EM BREVE ({alerta_earnings}) - AVALIAR FECHO PREVENTIVO ANTES DOS RESULTADOS!"
        subiu_stop = True

    diferenca_bruta = ema8 - ema32
    forecast_atual = (diferenca_bruta / atr36) * 5.0 if atr36 > 0 else 0

    linha_monitorizacao = (
        f"📌 [POSIÇÃO ATIVA - {status_atual}] {ticker_clean} ({nome_empresa}) | "
        f"Qtd: {quantidade} | Entrada: {preco_entrada} | Preço Atual: {preco_rt:.2f} | "
        f"EMA8: {ema8:.2f} | EMA32: {ema32:.2f} | Forecast: {forecast_atual:.2f} | "
        f"Stop Atual: {stop_atual_registado} | Novo Stop Sugerido: {stop_final} | "
        f"Earnings: {alerta_earnings} | "
        f"🛑 AÇÃO: {instrucao_risco} (ATR36: {atr36:.2f})"
    )
    return {"texto": linha_monitorizacao, "alerta_urgente": subiu_stop}

# ===================================================================
# 5. EXECUÇÃO PRINCIPAL
# ===================================================================
def executar_motor():
    ativos, posicoes_ativas_dict, configs = buscar_dados_completos()
    if not ativos and not posicoes_ativas_dict:
        print("[AVISO] Nenhum dado carregado do Sheets. A terminar sem erro.")
        sys.exit(0)

    capital_total_conta = limpar_float(configs.get("CAPITAL_TOTAL_CONTA")) or 10400.00
    alvo_volatilidade_anual = limpar_float(configs.get("ALVO_VOLATILIDADE_ANUAL")) or 0.05
    risco_fixo_usd = limpar_float(configs.get("RISCO_MAXIMO_USD"))

    volatilidade_alvo_diaria_usd = (capital_total_conta * alvo_volatilidade_anual) / 16.0
    risco_base_usd = risco_fixo_usd if (risco_fixo_usd and risco_fixo_usd > 0) else volatilidade_alvo_diaria_usd

    print(f"[CONFIG] Capital Total da Conta: ${capital_total_conta:,.2f}")
    print(f"[CONFIG] Orçamento Base de Risco por Trade: ${risco_base_usd:.2f} USD\n")
    
    info_macro = verificar_regime_macro()

    # Mapeamento de setores e posições realmente ativas (ignora posições FECHADA)
    mapa_setores_watchlist = {}
    for item in ativos:
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
        
    candidatos_novos = []
    posicoes_em_gestao = []
    alerta_gestao_urgente = False
    total_analisados = 0

    if info_macro["autorizado"]:
        for ativo_info in ativos:
            ticker_raw = str(ativo_info.get("ticker", "")).strip().upper().replace(".", "-")
            if not ticker_raw or ticker_raw == "#N/A": continue
            if ticker_raw in tickers_ativos_set: continue

            total_analisados += 1
            res = analisar_tendencia_carver(ativo_info, risco_base_usd, info_macro, setores_ocupados)
            if res:
                candidatos_novos.append(res)

    candidatos_novos = sorted(candidatos_novos, key=lambda k: k['forecast'], reverse=True)

    ativos_acionados = []
    contagem_setores = {}

    for item in candidatos_novos:
        setor = str(item.get("setor", "Desconhecido")).strip()
        setor_key = setor.lower()
        qtd_atual_setor = contagem_setores.get(setor_key, 0)
        
        if qtd_atual_setor < MAX_NOVOS_SINAIS_POR_SETOR:
            ativos_acionados.append(item)
            contagem_setores[setor_key] = qtd_atual_setor + 1
        else:
            print(f"[CORRELAÇÃO BLOQUEADA] Ativo {item['ticker']} ignorado. Limite de {MAX_NOVOS_SINAIS_POR_SETOR} novo sinal para o setor '{setor}' atingido.")

    for ticker, dados_pos in posicoes_ativas_dict.items():
        if not isinstance(dados_pos, dict): continue
        status_atual = str(dados_pos.get("status", "")).strip().upper()
        
        if status_atual != "ATIVA_FAST":
            continue
            
        nome = dados_pos.get("nome", ticker)
        monitorizacao = monitorizar_posicao_ativa(ticker, nome, status_atual, dados_pos)
        if monitorizacao:
            posicoes_em_gestao.append(monitorizacao["texto"])
            if monitorizacao["alerta_urgente"]:
                alerta_gestao_urgente = True

    prompt_ia = (
        "MODO ACELERADOR ESTATÍSTICO (CARVER FAST TREND)\n"
        "O teu mandato é auditar as entradas geradas e monitorizar as posições ativas do portefólio.\n"
        "Presta especial atenção ao RS Score institucional anexado aos dados de cada novo sinal para avaliar o contexto de força do mercado.\n"
        "ATENÇÃO À GESTÃO DE RISCO: Respeita estritamente a regra de inércia do trailing stop nas posições ativas "
        "(o stop nunca desce; se o stop atual registado já for superior ao novo cálculo sugerido, a instrução deve ser obrigatoriamente manter o valor atual).\n"
        "Se uma posição ativa apresentar aviso de Earnings em breve ou Stop atingido, reforça o alerta imediato.\n\n"
        "REGRAS ESTRITAS:\n"
        "- 🔄 GESTÃO DE ESTADOS NO SHEETS (LEMBRETE OBRIGATÓRIO): Termina o teu relatório com uma secção de 'Lembrete Operacional' contendo exatamente estas duas notas:\n"
        "  1. \"🟢 NOVAS ENTRADAS: Assim que abrires uma nova posição sugerida neste relatório, altera o seu estado no Google Sheets para 'ATIVA_FAST' para que eu inicie o cálculo diário do Trailing Stop.\"\n"
        "  2. \"🔴 SAÍDAS/STOPS: Se uma posição ativa atingir o Trailing Stop, altera o estado no Sheets para 'WIN' (se a trade fechou com lucro) ou 'LOSS' (se fechou com prejuízo) para as tuas estatísticas. Ao mudares o estado, eu deixarei de a monitorizar automaticamente.\"\n"
    )
    
    bloco_texto_ia = (
        f"📊 RELATÓRIO DE DADOS BRUTOS - FAST TREND CARVER 🏄‍♂️\n"
        f"🌐 Filtro Macro: {info_macro['msg']}\n"
        f"💰 Risco Base por Trade: ${risco_base_usd:.2f} USD | Fator Lote Regime: {int(info_macro['fator_lote']*100)}%\n\n"
        f"{prompt_ia}\n\n--------------------------------------------------\n"
    )

    if posicoes_em_gestao:
        bloco_texto_ia += "GESTÃO DE POSIÇÕES ATIVAS (TRAILING STOP SUGERIDO & QUANTIDADES):\n\n"
        for pos in posicoes_em_gestao:
            bloco_texto_ia += pos + "\n"
        bloco_texto_ia += "\n--------------------------------------------------\n"

    if not info_macro["autorizado"]:
        bloco_texto_ia += f"🛡️ [MODO DEFENSIVO] Novas entradas Carver bloqueadas hoje ({info_macro['msg']}).\n"
    elif not ativos_acionados:
        bloco_texto_ia += f"[MERCADO LENTO / FILTRADO] - Nenhum novo ativo aprovado (Regime Macro: {info_macro['status']}, Forecast Mínimo: {info_macro['min_forecast']}).\n"
    else:
        bloco_texto_ia += f"NOVOS DADOS DE ENTRADA (COMBOIO) - REGIME MACRO: {info_macro['status']}:\n\n"
        for item in ativos_acionados:
            bloco_texto_ia += item["comboio_str"] + "\n"

    with open("comboio_carver_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco_texto_ia)

    enviar_email_bruto(bloco_texto_ia)

    # ===================================================================
    # 6. NOTIFICAÇÃO TELEGRAM (DEBUG, NOVO SINAL OU AJUSTE DE STOP URGENTE)
    # ===================================================================
    debug_telegram_ativado = str(configs.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

    if debug_telegram_ativado or len(ativos_acionados) > 0 or alerta_gestao_urgente:
        print("A enviar notificação para o Telegram via função modular...")
        total_acionados = len(ativos_acionados)
        mensagem_debug = (
            f"06 🏄‍♂️ *MOTOR FAST TREND (CARVER)*\n\n"
            f"🔍 Execução concluída ({info_macro['status']}).\n"
            f"📊 Ativos analisados: *{total_analisados}* | Novos Sinais: *{total_acionados}* | Em Gestão: *{len(posicoes_em_gestao)}*\n"
            f"✉️ Relatório Carver gerado e enviado por e-mail."
        )
        enviar_alerta(mensagem_debug)

if __name__ == "__main__":
    executar_motor()
