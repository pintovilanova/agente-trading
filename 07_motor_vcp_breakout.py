# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR DE COMPRESSÃO VCP (BREAKOUT)
# ===================================================================
# Descrição Geral:
# Caçador de Volatility Contraction Pattern (Mark Minervini):
#   - Tendência Primária: Preço > SMA 50 > SMA 200 + Liquidez institucional
#   - Contração & Squeeze: BBW perto do mínimo de 120d + amplitude 5d comprimida
#   - Seca de Volume (VDU): Volume médio 3d < 60% da média de 50d
#   - Gatilho: Ordem BUY STOP acima da máxima de 5 dias, com preço no terço superior
#   - Regime Macro (SPY/VIX):
#       * Expansão (SPY > EMA20): Alvo 3.0R | RS >= 75 | Lote 100%
#       * Corretivo (SMA200 < SPY <= EMA20): Alvo 2.0R | RS >= 85 | Lote 50%
#       * Baixista (SPY < SMA200, queda <= -1.50% ou VIX > 30): Bloqueia entradas
# ===================================================================

import pandas as pd
import yfinance as yf
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
    print("[INFO] Fim de semana detetado. O Motor VCP vai descansar.")
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
def verificar_regime_mercado_vcp():
    """
    Avalia o regime do SPY para Breakouts VCP (Minervini):
    - Expansão (SPY > EMA20): TP 3.0R | RS >= 75 | Fator Lote 1.0 (0.5 se VIX > 23)
    - Corretivo (SMA200 < SPY <= EMA20): TP 2.0R | RS >= 85 | Fator Lote 0.5 (0.35 se VIX > 23)
    - Baixista / Queda <= -1.50% / VIX > 30: Bloqueia novas entradas
    """
    regime_default = {
        "autorizado": True,
        "modo": "EXPANSAO",
        "tp_mult": 3.0,
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
                "tp_mult": 2.0,
                "rs_min": 85.0,
                "fator_risco": 0.0,
                "msg": f"SPY (${close_hoje:.2f}) abaixo da SMA200 (${sma200:.2f}). Regime Baixista{tag_vix}."
            }
        if var_dia <= -1.50:
            return {
                "autorizado": False,
                "modo": "QUEDA_DIARIA",
                "tp_mult": 2.0,
                "rs_min": 85.0,
                "fator_risco": 0.0,
                "msg": f"SPY em queda acentuada hoje ({var_dia:.2f}% <= -1.50%){tag_vix}. Breakouts VCP bloqueados."
            }
        if vix_atual is not None and vix_atual > 30.0:
            return {
                "autorizado": False,
                "modo": "PANICO_VIX",
                "tp_mult": 2.0,
                "rs_min": 85.0,
                "fator_risco": 0.0,
                "msg": f"VIX em pânico sistémico ({vix_atual:.2f} > 30.00)."
            }

        if close_hoje < ema20:
            fator = 0.35 if (vix_atual is not None and vix_atual > 23.0) else 0.50
            return {
                "autorizado": True,
                "modo": "CORRETIVO",
                "tp_mult": 2.0,
                "rs_min": 85.0,
                "fator_risco": fator,
                "msg": (
                    f"SPY em pullback/lateral (${close_hoje:.2f} < EMA20 ${ema20:.2f} | SMA200 ${sma200:.2f} | "
                    f"Var: {var_dia:+.2f}%{tag_vix}) — VCP Tático: Alvo 2.0R, RS >= 85 e Lote {int(fator*100)}%."
                )
            }

        fator = 0.50 if (vix_atual is not None and vix_atual > 23.0) else 1.0
        return {
            "autorizado": True,
            "modo": "EXPANSAO",
            "tp_mult": 3.0,
            "rs_min": 75.0,
            "fator_risco": fator,
            "msg": (
                f"SPY em Expansão (${close_hoje:.2f} > EMA20 ${ema20:.2f} > SMA200 ${sma200:.2f} | "
                f"Var: {var_dia:+.2f}%{tag_vix}) — Alvo 3.0R | RS >= 75 | Lote {int(fator*100)}%."
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
    print("A carregar a Watchlist, Posições Ativas e Configurações a partir do Google Sheets...")
    if not WEBHOOK_URL: 
        print("[ERRO CRÍTICO] WEBHOOK_URL não encontrada nas variáveis de ambiente.")
        return [], {}, {}
    try:
        url_alvo = WEBHOOK_URL if "?" in WEBHOOK_URL else f"{WEBHOOK_URL}?aba=Analise Compra"
        resp = requests.get(url_alvo, timeout=20)
        
        if resp.status_code == 200:
            try:
                dados = resp.json()
            except Exception as e:
                print(f"[ERRO] O Webhook não retornou JSON válido: {e}. Resposta: {resp.text[:200]}")
                return [], {}, {}

            if isinstance(dados, dict):
                if "erro" in dados:
                    print(f"[ERRO DO SHEETS] {dados['erro']}")
                    return [], {}, {}
                ativos = dados.get("ativos", [])
                posicoes = dados.get("posicoesAtivas", {}) or dados.get("posicoes", {})
                configs = dados.get("configs", {})
                print(f"[SUCESSO] {len(ativos)} ativos, {len(posicoes)} posições e {len(configs)} configs carregados.")
                return ativos, posicoes, configs
            elif isinstance(dados, list):
                print(f"[SUCESSO] {len(dados)} ativos carregados (formato lista).")
                return dados, {}, {}
            else:
                return [], {}, {}
        else:
            print(f"[ERRO HTTP] Falha ao descarregar dados: {resp.status_code}.")
            return [], {}, {}
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha de comunicação com Sheets: {e}")
        return [], {}, {}

def enviar_email(conteudo):
    print("\nA enviar email VCP/Squeeze para o Agente IA...")
    
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] Credenciais de email em falta. A saltar envio.")
        return

    if "@" not in EMAIL_USER or "." not in EMAIL_USER:
        print(f"[ERRO CRÍTICO] O e-mail configurado ('{EMAIL_USER}') não é um endereço válido.")
        return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = f"🎯 tradingRelatorioIA US - VCP BREAKOUT SQUEEZE ({datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')})"
    msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
    
    max_tentativas = 3
    for tentativa in range(max_tentativas):
        try:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
            server.quit()
            print(f"[SUCESSO] Email VCP enviado na tentativa {tentativa + 1}!")
            break
        except Exception as e:
            print(f"[ERRO] Falha ao enviar o email (tentativa {tentativa + 1} de {max_tentativas}): {e}")
            if tentativa < max_tentativas - 1:
                time.sleep(5)
            else:
                print("[ERRO CRÍTICO] Falha definitiva no envio de email.")

# ===================================================================
# 3. MOTOR MATEMÁTICO: COMPRESSÃO DE VOLATILIDADE (VCP MINERVINI)
# ===================================================================
def analisar_compressao_vcp(ativo_info, risco_por_trade_usd, capital_total_conta, tickers_ativos_set, setores_ocupados, regime):
    try:
        ticker = str(ativo_info.get("ticker", "")).strip().upper().replace(".", "-")
        nome_empresa = ativo_info.get("nome", "N/A")
        setor = str(ativo_info.get("setor") or ativo_info.get("setorAtivo") or ativo_info.get("sector") or "Desconhecido").strip()
        rs_score = ativo_info.get("rs_score", "N/A")

        if not ticker or ticker == "#N/A" or ticker == "NONE":
            return None

        if ticker == "BRK-A":
            ticker = "BRK-B"

        if ticker in tickers_ativos_set:
            return None
        if setor not in ["Desconhecido", "N/A", "", "NONE"] and setor.lower() in setores_ocupados:
            return None

        val_rs_num = limpar_float(rs_score)
        if val_rs_num is not None and val_rs_num < regime["rs_min"]:
            return None

        time.sleep(random.uniform(0.35, 0.8))
        df = yf.download(ticker, period="1y", interval="1d", progress=False, session=session)
        if df.empty:
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])
        if len(df) < 200:
            return None

        preco = float(df.iloc[-1]['Close'])
        vol_sma50_check = float(df['Volume'].rolling(window=50).mean().iloc[-1])
        
        # Liquidez institucional: Preço >= $10 e Volume Médio 50d >= 300k
        if pd.isna(preco) or preco < 10.00 or pd.isna(vol_sma50_check) or vol_sma50_check < 300000:
            return None

        alerta_earnings = "OK"
        try:
            ticker_obj = yf.Ticker(ticker, session=session)
            if setor in ["Desconhecido", "N/A", "", "NONE"]:
                setor_yf = ticker_obj.info.get('sector')
                if setor_yf:
                    setor = setor_yf

            if setor not in ["Desconhecido", "N/A", "", "NONE"] and setor.lower() in setores_ocupados:
                return None

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

        # Veto duro no Python para Earnings iminentes ou REITs
        if alerta_earnings.startswith("PERIGO"):
            return None
        if setor and any(termo in str(setor).lower() for termo in ["real estate", "reit", "mortgage"]):
            return None

        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        df['STD_20'] = df['Close'].rolling(window=20).std()
        df['BB_Upper'] = df['SMA_20'] + (df['STD_20'] * 2)
        df['BB_Lower'] = df['SMA_20'] - (df['STD_20'] * 2)
        df['BBW'] = ((df['BB_Upper'] - df['BB_Lower']) / df['SMA_20']) * 100
        
        df['Vol_SMA_50'] = df['Volume'].rolling(window=50).mean()
        vol_medio_3d = float(df['Volume'].iloc[-3:].mean())
        
        high = df['High']
        low = df['Low']
        close = df['Close']
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['ATR_14'] = tr.rolling(window=14).mean()

        df = df.dropna(subset=['SMA_50', 'SMA_200', 'BBW', 'Vol_SMA_50', 'ATR_14'])
        if df.empty:
            return None

        ultimo = df.iloc[-1]
        sma50 = float(ultimo['SMA_50'])
        sma200 = float(ultimo['SMA_200'])
        bbw_atual = float(ultimo['BBW'])
        vol_sma50 = float(ultimo['Vol_SMA_50'])
        atr = float(ultimo['ATR_14'])
        
        max_5d = float(df['High'].iloc[-5:].max())
        min_5d = float(df['Low'].iloc[-5:].min())

        # Contração progressiva VCP: amplitude dos últimos 5d < amplitude dos 15d anteriores
        amplitude_5d = (max_5d - min_5d) / min_5d if min_5d > 0 else 1.0
        max_prev_15d = float(df['High'].iloc[-20:-5].max())
        min_prev_15d = float(df['Low'].iloc[-20:-5].min())
        amplitude_prev_15d = (max_prev_15d - min_prev_15d) / min_prev_15d if min_prev_15d > 0 else 1.0
        contracao_progressiva = (amplitude_5d < amplitude_prev_15d) and (amplitude_5d <= 0.06)

        # Preço perto do gatilho de rompimento (no terço superior da base, <= 3.5% abaixo da máxima 5d)
        dist_gatilho_pct = ((max_5d - preco) / preco) * 100 if preco > 0 else 99.0
        perto_do_gatilho = (0.0 <= dist_gatilho_pct <= 3.5)

        tendencia_alta = (preco > sma50) and (sma50 > sma200)
        bbw_120d_min = float(df['BBW'].iloc[-120:].min()) if len(df) >= 120 else float(df['BBW'].min())
        squeeze_ativo = (bbw_atual <= (bbw_120d_min * 1.5)) and (bbw_atual < 8.0)
        seca_volume = vol_medio_3d < (vol_sma50 * 0.60)

        if tendencia_alta and squeeze_ativo and contracao_progressiva and perto_do_gatilho and seca_volume:
            preco_rt = obter_preco_tempo_real(ticker, preco)
            entrada_gatilho = round(max_5d * 1.002, 2)

            # Se em pré-abertura o preço já disparou > 2.5% acima do gatilho, não perseguir
            if preco_rt > entrada_gatilho * 1.025:
                return None

            stop_base = round(min_5d * 0.998, 2)
            # Piso mínimo de stop (0.5x ATR) para evitar ruído intradiário e alavancagem excessiva
            stop_min_atr = round(entrada_gatilho - (atr * 0.5), 2) if atr > 0 else stop_base
            stop_loss = min(stop_base, stop_min_atr)
            
            risco = entrada_gatilho - stop_loss
            if risco <= 0:
                return None

            tp_mult = regime["tp_mult"]
            alvo_tp = round(entrada_gatilho + (risco * tp_mult), 2)
            
            # Dimensionamento pelo RISCO REAL (Gatilho - Stop), com teto máximo de 25% da conta por posição
            qtd_por_risco = risco_por_trade_usd / risco
            qtd_max_capital = (capital_total_conta * 0.25) / entrada_gatilho
            qtd_calc = round(min(qtd_por_risco, qtd_max_capital), 2)
                
            if qtd_calc <= 0:
                return None

            qtd_acoes = qtd_calc
            val_calc = entrada_gatilho * qtd_acoes
            valor_investir = f"~${val_calc:.2f} USD"
            estado = f"SQUEEZE EXTREMO - Ignição Iminente ({regime['modo']})"
            
            def limpa(v): 
                try:
                    if pd.isna(v) or v == "N/A": return "N/A"
                    return round(float(v), 2)
                except Exception:
                    return "N/A"
            
            if val_rs_num is not None:
                if val_rs_num >= 80:
                    status_rs = "🔥 ELITE (RS >= 80 - Vento a Favor)"
                else:
                    status_rs = "⚖️ FORTE (RS 75-79 - Líder Institucional)"
            else:
                status_rs = "❓ SEM DADO DE RS"
            
            linha_comboio = (
                f"{ticker},Nome: {nome_empresa},Setor: {setor},Preço: {limpa(preco_rt)},"
                f"RS Score: {rs_score} ({status_rs}),"
                f"BBW Atual: {limpa(bbw_atual)}%,Amplitude 5D: {round(amplitude_5d*100, 2)}%,Volume 3D: Seco (-40%+),"
                f"Gatilho Compra (Buy Stop): {limpa(entrada_gatilho)},"
                f"Stop Físico (Base 5D): {limpa(stop_loss)},Alvo TP ({tp_mult:.1f}R): {limpa(alvo_tp)},"
                f"Estado: {estado},Qtd: {qtd_acoes},ValorInvestir: {valor_investir},Earnings: {alerta_earnings},"
                f"Data: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
            )

            return {
                "ticker": ticker,
                "setor": setor,
                "bbw": bbw_atual,
                "comboio_str": linha_comboio
            }
            
        return None
    except Exception as e:
        print(f"[ERRO] Falha ao processar ativo {ativo_info.get('ticker')}: {e}")
        return None

# ===================================================================
# 4. EXECUÇÃO PRINCIPAL
# ===================================================================
def executar_motor():
    ativos, posicoes_ativas_dict, configs = buscar_dados_completos()
    if not ativos:
        print("[AVISO] Nenhum ativo carregado para análise. A terminar a execução sem erro.")
        sys.exit(0)

    regime_macro = verificar_regime_mercado_vcp()
        
    capital_total_conta = limpar_float(configs.get("CAPITAL_TOTAL_CONTA")) or 10400.00
    alvo_volatilidade_anual = limpar_float(configs.get("ALVO_VOLATILIDADE_ANUAL")) or 0.05
    risco_fixo_usd = limpar_float(configs.get("RISCO_MAXIMO_USD"))

    volatilidade_alvo_diaria_usd = (capital_total_conta * alvo_volatilidade_anual) / 16.0
    risco_base_usd = risco_fixo_usd if (risco_fixo_usd and risco_fixo_usd > 0) else volatilidade_alvo_diaria_usd
    risco_ajustado_usd = round(risco_base_usd * regime_macro["fator_risco"], 2) if regime_macro["autorizado"] else 0.0

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

    print(f"[CONFIG] Capital Total: ${capital_total_conta:,.2f} | Risco Base: ${risco_base_usd:.2f} | Risco Ajustado ({regime_macro['modo']}): ${risco_ajustado_usd:.2f} USD")
    print(f"[MACRO] {regime_macro['msg']}\n")

    candidatos_vcp = []
    total_analisados = 0
    if regime_macro["autorizado"]:
        for ativo_info in ativos:
            ticker = ativo_info.get("ticker")
            if not ticker or ticker == "#N/A": continue
            
            total_analisados += 1
            res = analisar_compressao_vcp(
                ativo_info, risco_ajustado_usd, capital_total_conta, tickers_ativos_set, setores_ocupados, regime_macro
            )
            if res:
                candidatos_vcp.append(res)
            
    # Ordena pelos squeezes mais apertados e limita a 1 breakout por setor livre
    candidatos_vcp = sorted(candidatos_vcp, key=lambda k: k['bbw'])
    ativos_acionados = []
    setores_novos_usados = set()
    for item in candidatos_vcp:
        s_key = item["setor"].lower()
        if s_key not in setores_novos_usados:
            ativos_acionados.append(item)
            if s_key not in ["desconhecido", "n/a", ""]:
                setores_novos_usados.add(s_key)

    tp_label = f"{regime_macro['tp_mult']:.1f}R"
    prompt_ia = f"""Atuas como Analista Quantitativo de Breakouts (Modelo Mark Minervini). O teu mandato é auditar ativos em fase de Squeeze (Contração de Volatilidade) preparados para explosão direcional.

REGRAS ESTRITAS:
1. O ativo não deve ser comprado a mercado. Recomenda SEMPRE ordens pendentes "Buy Stop" no Gatilho de Compra estipulado.
2. Destaca o facto do risco ser controlado, dado que o Stop Loss está cravado na base da consolidação (caixote de 5 dias) com piso de ATR.
3. Avalia o Rácio Risco/Recompensa ({tp_label}) e presta especial atenção ao RS Score institucional anexado aos dados.

ESTRUTURA OBRIGATÓRIA:
🎯 [TICKER] - [Nome da Empresa] ([Setor])
- 🗜️ NÍVEL DE COMPRESSÃO: BBW a [X]% | Amplitude 5D [X]% (Mola comprimida com seca de volume).
- 📊 CONTEXTO INSTITUCIONAL: RS Score e respetivo estado de Força Relativa.
- ⚙️ TÁTICA DE EXECUÇÃO: Colocar ordem pendente Buy Stop em [Gatilho] para apanhar o breakout.
- 🛡️ RISCO MICRO: Stop Físico cravado em [Stop] (Base de 5 dias).
- 🔢 DADOS: Alvo ({tp_label}): [TP] | Qtd: [X] | Alocação: [Valor].
- 🔄 PASSAGEM DE TESTEMUNHO: Adiciona explicitamente o texto: "⚠️ ATENÇÃO: Assim que esta ordem for executada na corretora, altera imediatamente o estado no Google Sheets para 'ATIVA_FAST'. O Motor Carver assumirá automaticamente a gestão do Trailing Stop a partir daí."
"""
    
    bloco_texto_ia = (
        f"📊 RELATÓRIO VCP BREAKOUT / SQUEEZE 🗜️\n"
        f"🌐 Filtro Macro: {regime_macro['msg']}\n"
        f"💰 Risco Configurado por Trade: ${risco_ajustado_usd:.2f} USD (Base: ${risco_base_usd:.2f} | Fator: {int(regime_macro['fator_risco']*100)}%)\n\n"
        f"{prompt_ia}\n\n--------------------------------------------------\n"
    )
    
    if not regime_macro["autorizado"]:
        bloco_texto_ia += f"🛡️ [MODO DEFENSIVO] Novas entradas VCP bloqueadas hoje ({regime_macro['msg']}).\n"
    elif not ativos_acionados:
        bloco_texto_ia += "[SEM SINAIS VCP] - Nenhuma ação apresenta os critérios extremos de Squeeze e seca de volume hoje.\n"
    else:
        bloco_texto_ia += "ALVOS DE BREAKOUT IMINENTE:\n\n"
        for item in ativos_acionados:
            bloco_texto_ia += item["comboio_str"] + "\n"
            
    with open("comboio_vcp_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco_texto_ia)
        
    enviar_email(bloco_texto_ia)

    # ===================================================================
    # 5. NOTIFICAÇÃO TELEGRAM (DEBUG OU SINAL VCP DETETADO)
    # ===================================================================
    debug_telegram_ativado = str(configs.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

    if debug_telegram_ativado or len(ativos_acionados) > 0:
        print("A enviar notificação para o Telegram via função modular...")
        total_acionados = len(ativos_acionados)
        mensagem_debug = (
            f"07 🎯 *MOTOR VCP BREAKOUT (SQUEEZE)*\n\n"
            f"🔍 Execução concluída ({regime_macro['modo']} | Alvo {tp_label}).\n"
            f"📊 Ativos analisados: *{total_analisados}* | Acionados: *{total_acionados}*\n"
            f"💰 Risco/Trade: *${risco_ajustado_usd:.2f} USD*\n"
            f"✉️ Relatório VCP gerado e enviado por e-mail."
        )
        enviar_alerta(mensagem_debug)

if __name__ == "__main__":
    executar_motor()
