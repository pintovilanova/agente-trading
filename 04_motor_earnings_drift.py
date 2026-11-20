# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR DE EARNINGS DRIFT (PEAD)
# ===================================================================
# Descrição Geral:
# Caçador de Post-Earnings Announcement Drift (PEAD) via GitHub Actions.
# Adapta-se ao regime do SPY:
#   - Expansão (SPY > EMA20): Alvo 2.0R | RS >= 70 | Lote 100%
#   - Corretivo (SMA200 < SPY <= EMA20): Alvo 1.5R | RS >= 80 | Lote 50%
#   - Baixista (SPY < SMA200 ou VIX > 30): Bloqueia novas entradas
# ===================================================================

import pandas as pd
import yfinance as yf
import pandas_ta as ta
import numpy as np
from datetime import datetime, date, timedelta
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
    print("[INFO] Fim de semana detetado. O mercado está fechado.")
    # sys.exit(0)

# ===================================================================
# 1. CONFIGURAÇÕES E CREDENCIAIS (GitHub Secrets)
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")

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
# 2. FUNÇÕES DE REDE, REGIME MACRO E RESILIÊNCIA YAHOO FINANCE
# ===================================================================
def verificar_regime_mercado():
    """
    Avalia o regime do SPY para o motor PEAD:
    - Expansão (SPY > EMA20): TP 2.0R | RS >= 70 | Fator Lote 1.0 (ou 0.5 se VIX > 23)
    - Corretivo/Lateral (SMA200 < SPY <= EMA20): TP 1.5R | RS >= 80 | Fator Lote 0.5 (ou 0.35 se VIX > 23)
    - Baixista (SPY < SMA200 ou VIX > 30): Bloqueia novas entradas
    """
    regime_default = {
        "autorizado": True,
        "modo": "EXPANSAO",
        "tp_mult": 2.0,
        "rs_min": 70.0,
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
                "tp_mult": 1.5,
                "rs_min": 85.0,
                "fator_risco": 0.0,
                "msg": f"SPY (${close_hoje:.2f}) abaixo da SMA200 (${sma200:.2f}). Mercado em regime baixista{tag_vix}."
            }
        if var_dia <= -2.5:
            return {
                "autorizado": False,
                "modo": "CRASH",
                "tp_mult": 1.5,
                "rs_min": 85.0,
                "fator_risco": 0.0,
                "msg": f"SPY em queda extrema/crash hoje ({var_dia:.2f}% <= -2.50%){tag_vix}."
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

        if close_hoje < ema20:
            fator = 0.35 if (vix_atual is not None and vix_atual > 23.0) else 0.50
            return {
                "autorizado": True,
                "modo": "CORRETIVO",
                "tp_mult": 1.5,
                "rs_min": 80.0,
                "fator_risco": fator,
                "msg": (
                    f"SPY em pullback/lateral (${close_hoje:.2f} < EMA20 ${ema20:.2f} | SMA200 ${sma200:.2f} | "
                    f"Var: {var_dia:+.2f}%{tag_vix}) — Modo Tático: Alvo 1.5R, RS >= 80 e Lote {int(fator*100)}%."
                )
            }

        fator = 0.50 if (vix_atual is not None and vix_atual > 23.0) else 1.0
        return {
            "autorizado": True,
            "modo": "EXPANSAO",
            "tp_mult": 2.0,
            "rs_min": 70.0,
            "fator_risco": fator,
            "msg": (
                f"SPY em Expansão (${close_hoje:.2f} > EMA20 ${ema20:.2f} > SMA200 ${sma200:.2f} | "
                f"Var: {var_dia:+.2f}%{tag_vix}) — Alvo 2.0R | Lote {int(fator*100)}%."
            )
        }
    except Exception as e:
        regime_default["msg"] = f"Aviso SPY: {e}"
        return regime_default

def get_yf_history_safe(ticker_str, period="1y"):
    """Descarrega histórico diário limpo (removendo eventuais barras intradiárias sem volume)."""
    for _ in range(3):
        try:
            time.sleep(random.uniform(0.7, 1.5))
            df = yf.download(ticker_str, period=period, interval="1d", progress=False, timeout=15, session=session)
            if not df.empty and len(df) >= 200:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])
                df = df[df['Volume'] > 0]
                if len(df) >= 200:
                    return df
        except Exception:
            time.sleep(2.0)
    return pd.DataFrame()

def obter_preco_tempo_real(ticker_str, fallback_close):
    """Obtém a cotação mais recente (regular, pre-market ou post-market)."""
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

def obter_earnings_dates_safe(ticker_str):
    """Obtém o calendário de earnings com isolamento de exceção."""
    try:
        time.sleep(random.uniform(0.5, 1.1))
        ticker_obj = yf.Ticker(ticker_str, session=session)
        earnings_df = ticker_obj.earnings_dates
        return ticker_obj, earnings_df
    except Exception:
        return None, None

def buscar_dados_completos():
    print("A carregar a Watchlist, Posições Ativas e Configurações a partir do Google Sheets...")
    if not WEBHOOK_URL: 
        print("[ERRO] WEBHOOK_URL não configurado.")
        return [], {}, {}
    try:
        url_alvo = WEBHOOK_URL if "?" in WEBHOOK_URL else f"{WEBHOOK_URL}?aba=Analise Compra"
        resp = requests.get(url_alvo, timeout=20)
        if resp.status_code == 200:
            dados = resp.json()
            if isinstance(dados, dict):
                ativos = dados.get("ativos", [])
                posicoes = dados.get("posicoesAtivas", {}) or dados.get("posicoes", {})
                configs = dados.get("configs", {})
            elif isinstance(dados, list):
                ativos, posicoes, configs = dados, {}, {}
            else:
                ativos, posicoes, configs = [], {}, {}
                
            print(f"[SUCESSO] {len(ativos)} ativos carregados para auditoria.")
            return ativos, posicoes, configs
        else:
            print(f"[ERRO] Falha ao descarregar dados: {resp.status_code}")
            return [], {}, {}
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha de comunicação com Sheets: {e}")
        return [], {}, {}

def enviar_email(conteudo):
    print("\nA enviar relatório de Earnings Drift para o Agente IA...")
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] Credenciais de email em falta. A saltar envio.")
        return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = f"tradingRelatorioIA US - EARNINGS DRIFT ({datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')})"
    msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
    
    max_tentativas = 3
    for tentativa in range(max_tentativas):
        try:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
            server.quit()
            print(f"[SUCESSO] Email de Earnings enviado na tentativa {tentativa + 1}!")
            break
        except Exception as e:
            print(f"[ERRO] Falha ao enviar o email (tentativa {tentativa + 1} de {max_tentativas}): {e}")
            if tentativa < max_tentativas - 1:
                time.sleep(5)
            else:
                print("[ERRO CRÍTICO] Falha definitiva no envio de email.")

# ===================================================================
# 3. MOTOR MATEMÁTICO: EARNINGS DRIFT (PEAD)
# ===================================================================
def analisar_earnings_drift(ativo_info, risco_por_trade_usd, posicoes_ativas_dict, setores_ocupados, regime):
    ticker = str(ativo_info.get("ticker", "")).strip().upper()
    nome_empresa = ativo_info.get("nome", "N/A")
    setor = str(ativo_info.get("setor") or ativo_info.get("setorAtivo") or ativo_info.get("sector") or "Desconhecido").strip()
    rs_score = ativo_info.get("rs_score", "N/A")

    if not ticker or ticker == "#N/A" or ticker == "NONE":
        return None
    if ticker in posicoes_ativas_dict:
        return None
    if setor not in ["Desconhecido", "N/A", "", "NONE"] and setor.lower() in setores_ocupados:
        return None

    if ticker == "BRK-A":
        ticker = "BRK-B"

    # Alinhamento institucional dinâmico (RS >= 70 em Expansão | RS >= 80 em Corretivo)
    val_rs_num = limpar_float(rs_score)
    if val_rs_num is not None and val_rs_num < regime["rs_min"]:
        return None

    try:
        df = get_yf_history_safe(ticker, period="1y")
        if df.empty or len(df) < 200:
            return None

        ticker_obj, earnings_df = obter_earnings_dates_safe(ticker)

        if setor in ["Desconhecido", "N/A", "", "NONE"] and ticker_obj is not None:
            try:
                setor_yf = ticker_obj.info.get('sector')
                if setor_yf:
                    setor = setor_yf
            except Exception:
                pass

        if setor not in ["Desconhecido", "N/A", "", "NONE"] and setor.lower() in setores_ocupados:
            return None

        df.ta.atr(length=14, append=True)
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        media_volume_20 = df['Volume'].rolling(window=20).mean()
        df['RVOL'] = df['Volume'] / media_volume_20

        # Exige tendência primária de alta (Close > SMA200)
        fecho_atual_df = float(df['Close'].iloc[-1])
        sma200_atual = float(df['SMA_200'].iloc[-1])
        if pd.isna(sma200_atual) or fecho_atual_df <= sma200_atual:
            return None

        earnings_recente = False
        data_earnings_str = "N/A"
        d_earn_alvo = None
        
        if earnings_df is not None and not earnings_df.empty:
            hoje = datetime.now(ZoneInfo("Europe/Lisbon")).date()
            for idx, _ in earnings_df.head(6).iterrows():
                d_earn = idx.date() if hasattr(idx, 'date') else pd.to_datetime(idx).date()
                dias_passados = (hoje - d_earn).days
                if -1 <= dias_passados <= 5:
                    earnings_recente = True
                    data_earnings_str = d_earn.strftime('%d/%m/%Y')
                    d_earn_alvo = d_earn
                    break

        if not earnings_recente or d_earn_alvo is None:
            return None

        # Localiza a barra exata da reação ao earnings (pode ser o próprio dia ou o dia útil seguinte se foi After-Hours)
        datas_df = [idx.date() if hasattr(idx, 'date') else pd.to_datetime(idx).date() for idx in df.index]
        pos_evento = None
        for i, d_bar in enumerate(datas_df):
            if d_bar >= d_earn_alvo and i >= 1:
                # Se a barra do próprio dia não saltou, verifica a barra seguinte (anúncios pós-fecho)
                var_i = ((float(df['Close'].iloc[i]) - float(df['Close'].iloc[i - 1])) / float(df['Close'].iloc[i - 1])) * 100
                if var_i >= 2.0 or i == len(df) - 1:
                    pos_evento = i
                    break

        preco_rt = obter_preco_tempo_real(ticker, fecho_atual_df)
        cols_atr = [c for c in df.columns if str(c).startswith('ATRr_') or str(c).startswith('ATR_')]
        atr = float(df[cols_atr[0]].iloc[-1]) if cols_atr and pd.notna(df[cols_atr[0]].iloc[-1]) else np.nan

        # Caso A: Reação já consolidada numa vela diária (últimos 1-5 dias)
        sinal_valido = False
        if pos_evento is not None and pos_evento >= 1:
            barra_ev = df.iloc[pos_evento]
            barra_prev = df.iloc[pos_evento - 1]
            var_evento = ((float(barra_ev['Close']) - float(barra_prev['Close'])) / float(barra_prev['Close'])) * 100
            rvol_evento = float(barra_ev['RVOL']) if pd.notna(barra_ev['RVOL']) else 0.0
            min_evento = float(barra_ev['Low'])
            max_recente = float(df['High'].iloc[pos_evento:].max())

            # Confirma explosão no dia do earnings + preço atual ainda sustenta acima da mínima do dia do evento
            if var_evento >= 2.0 and rvol_evento >= 2.0 and preco_rt >= min_evento:
                sinal_valido = True
                var_perc = var_evento
                rvol = rvol_evento
                topo_referencia = max(max_recente, preco_rt)
                base_stop = min_evento

        # Caso B: Anúncio After-Hours recente com gap confirmado em pré-abertura/pós-fecho (>= +3.5%)
        if not sinal_valido:
            var_ah = ((preco_rt - fecho_atual_df) / fecho_atual_df) * 100
            if var_ah >= 3.5:
                sinal_valido = True
                var_perc = var_ah
                rvol = float(df['RVOL'].iloc[-1]) if pd.notna(df['RVOL'].iloc[-1]) else 2.0
                topo_referencia = preco_rt
                base_stop = max(fecho_atual_df, preco_rt - (atr * 1.5 if pd.notna(atr) and atr > 0 else preco_rt * 0.03))

        if not sinal_valido:
            return None

        estado = f"EARNINGS MOMENTUM - Drift Detetado ({regime['modo']})"
        entrada = round(topo_referencia * 1.002, 2)

        stop_por_minima = base_stop * 0.995
        stop_por_atr = entrada - (atr * 2.0) if (pd.notna(atr) and atr > 0) else stop_por_minima
        stop_loss = round(max(stop_por_minima, stop_por_atr), 2)

        risco = entrada - stop_loss
        if risco <= 0:
            return None

        tp_mult = regime["tp_mult"]
        alvo_tp = round(entrada + (risco * tp_mult), 2)
        qtd_acoes = round(risco_por_trade_usd / risco, 2)

        if qtd_acoes <= 0:
            return None

        val_calc = entrada * qtd_acoes
        valor_investir = f"~${val_calc:.2f} USD"

        def limpa(v):
            if pd.isna(v) or v == "N/A": return "N/A"
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
            f"{ticker},Nome: {nome_empresa},Setor: {setor},PreçoAtual: {limpa(preco_rt)},"
            f"RS Score: {rs_score} ({status_rs}),"
            f"DataEarnings: {data_earnings_str},VarEvento: {limpa(var_perc)}%,RVOL: {limpa(rvol)},"
            f"Estado: {estado},Ordem: BUY STOP,Entrada: {limpa(entrada)},Stop: {limpa(stop_loss)},"
            f"Take-Profit ({tp_mult:.1f}R): {limpa(alvo_tp)},Qtd: {qtd_acoes},ValorInvestir: {valor_investir},"
            f"Data: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
        )

        return {
            "ticker": ticker,
            "preco": limpa(preco_rt),
            "rs_score": rs_score,
            "status_rs": status_rs,
            "data_earnings": data_earnings_str,
            "var_perc": f"{limpa(var_perc)}%",
            "rvol": limpa(rvol),
            "estado": estado,
            "entrada": limpa(entrada),
            "stop": limpa(stop_loss),
            "tp": limpa(alvo_tp),
            "tp_mult": tp_mult,
            "qtd": qtd_acoes,
            "valor_investir": valor_investir,
            "comboio_str": linha_comboio
        }

    except Exception as e:
        print(f"[ERRO] Falha ao processar {ticker}: {e}")
        return None

# ===================================================================
# 4. EXECUÇÃO PRINCIPAL E INTEGRAÇÃO (Sheets + Email)
# ===================================================================
def executar_motor():
    resultados_para_sheets = []
    comboio_ia = []
    
    ativos, posicoes_ativas_dict, configs = buscar_dados_completos()
    if not ativos:
        sys.exit(1)

    regime_macro = verificar_regime_mercado()
        
    capital_total_conta = limpar_float(configs.get("CAPITAL_TOTAL_CONTA")) or 10400.00
    pct_risco = (
        limpar_float(configs.get("RISCO_POR_TRADE")) or 
        limpar_float(configs.get("RISCO_SWING_PCT")) or 
        0.0025
    )
    risco_fixo_usd = limpar_float(configs.get("RISCO_MAXIMO_USD"))
    risco_base_usd = risco_fixo_usd if (risco_fixo_usd and risco_fixo_usd > 0) else (capital_total_conta * pct_risco)
    risco_por_trade_usd = round(risco_base_usd * regime_macro["fator_risco"], 2) if regime_macro["autorizado"] else 0.0

    # Proteção anti-correlação setorial
    mapa_setores_watchlist = {}
    for item in ativos:
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

    print(f"[CONFIG] Capital Total: ${capital_total_conta:,.2f} | Risco Base: ${risco_base_usd:,.2f} | Risco Ajustado ({regime_macro['modo']}): ${risco_por_trade_usd:,.2f} USD")
    print(f"[MACRO] {regime_macro['msg']}\n")

    total_analisados = 0
    if regime_macro["autorizado"]:
        for ativo_info in ativos:
            ticker = ativo_info.get("ticker")
            if not ticker or ticker == "#N/A": continue
            
            total_analisados += 1
            res = analisar_earnings_drift(ativo_info, risco_por_trade_usd, posicoes_ativas_dict, setores_ocupados, regime_macro)
            
            if res:
                print(f"[SUCESSO] {ticker} ativado no motor PEAD!")
                resultados_para_sheets.append({
                    "ticker": res['ticker'],
                    "preco": res['preco'],
                    "rs_score": res['rs_score'],
                    "data_earnings": res['data_earnings'],
                    "var_perc": res['var_perc'],
                    "rvol": res['rvol'],
                    "estado": res['estado'],
                    "entrada": res['entrada'],
                    "stop": res['stop'],
                    "tp": res['tp'],
                    "qtd": res['qtd'],
                    "valor_investir": res['valor_investir'],
                    "time": datetime.now(ZoneInfo("Europe/Lisbon")).strftime('%d/%m/%Y %H:%M:%S'),
                    "comboio": res['comboio_str']
                })
                comboio_ia.append(res['comboio_str'])

    if WEBHOOK_URL:
        print("\nA atualizar o Google Sheets (Aba: Earnings Drift)...")
        try:
            payload_sheets = {
                "acao": "atualizar_earnings_drift",
                "aba": "Earnings Drift",
                "dados": resultados_para_sheets
            }
            headers = {'Content-Type': 'application/json'}
            resposta = requests.post(WEBHOOK_URL, data=json.dumps(payload_sheets), headers=headers, timeout=15)
            if resposta.status_code == 200:
                print("[SUCESSO] Sheets atualizado!")
            else:
                print(f"[ERRO] HTTP {resposta.status_code}: {resposta.text}")
        except Exception as e:
            print(f"[ERRO CRÍTICO] Falha HTTP: {e}")

    tp_label = f"{regime_macro['tp_mult']:.1f}R"
    prompt_ia = (
        "MODO CAÇADOR DE EARNINGS DRIFT (PEAD)\n"
        "O teu mandato é auditar os sinais gerados pelo motor Python e formatá-los para leitura do gestor da conta.\n\n"
        "🚨 REGRAS DE OURO (ANTI-ALUCINAÇÃO DE DADOS) 🚨\n"
        "1. ZERO CRIATIVIDADE: É ESTRITAMENTE PROIBIDO inventar, alucinar ou deduzir métricas de EPS, lucros, receitas, previsões de analistas ou datas que não te sejam dadas.\n"
        "2. FONTE ÚNICA: Retira os dados EXCLUSIVAMENTE da linha do comboio fornecida pelo motor. Não utilizes o teu conhecimento base de treino sobre a empresa.\n"
        "3. NARRATIVA NEUTRA: Se não tiveres detalhes sobre o motivo da subida na linha do comboio, escreve apenas 'Anomalia estatística detetada pelo algoritmo'.\n\n"
        "Estrutura Visual Obrigatória:\n"
        "🎯 [TICKER] - [Nome da Empresa] ([Setor])\n"
        "- 🚀 CATALISADOR DE EARNINGS: Data do evento: [DataEarnings] | Salto inicial: [VarEvento%]\n"
        "- 📊 CONTEXTO INSTITUCIONAL (RS SCORE): [Incluir o RS Score e o respetivo estado institucional reportado]\n"
        "- 🩸 PEGADA INSTITUCIONAL: RVOL detetado de [RVOL]\n"
        f"- ⚙️ TÁTICA: EARNINGS DRIFT ({regime_macro['modo']}). Surfar tendência com alvo {tp_label}.\n"
        "- 🔢 DADOS EXATOS: Ordem: BUY STOP | Entrada: X | Stop: X | TP: X | Qtd: X | Valor a Investir: X\n"
        "- 📋 REFERÊNCIA: [Copia e cola a Linha do Comboio exata fornecida abaixo]\n"
    )
    
    bloco_texto_ia = (
        f"📊 RELATÓRIO DE DADOS BRUTOS - EARNINGS DRIFT 🚀\n"
        f"🌐 Filtro Macro: {regime_macro['msg']}\n"
        f"💰 Risco Configurado por Trade: ${risco_por_trade_usd:,.2f} USD (Base: ${risco_base_usd:,.2f} | Fator: {int(regime_macro['fator_risco']*100)}%)\n\n"
        f"{prompt_ia}\n\n--------------------------------------------------\n"
    )

    if not regime_macro["autorizado"]:
        bloco_texto_ia += f"🛡️ [MODO DEFENSIVO] Novas entradas PEAD bloqueadas hoje ({regime_macro['msg']}).\n"
    elif not comboio_ia:
        bloco_texto_ia += "[SEM OPORTUNIDADES PEAD] - Nenhum ativo registou earnings recentes com explosão de volume e preço nos parâmetros estritos.\n"
    else:
        bloco_texto_ia += "DADOS DOS ATIVOS ATIVADOS (COMBOIO):\n\n"
        for linha in comboio_ia:
            bloco_texto_ia += linha + "\n"

    with open("comboio_earnings_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco_texto_ia)

    enviar_email(bloco_texto_ia)

    # ===================================================================
    # 5. NOTIFICAÇÃO TELEGRAM (DEBUG OU SINAL DETETADO)
    # ===================================================================
    debug_telegram_ativado = str(configs.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

    if debug_telegram_ativado or len(comboio_ia) > 0:
        print("A enviar notificação para o Telegram via função modular...")
        total_acionados = len(comboio_ia)
        mensagem_debug = (
            f"04 📊 *MOTOR DE EARNINGS DRIFT (PEAD)*\n\n"
            f"🔍 Execução concluída ({regime_macro['modo']} | Alvo {tp_label}).\n"
            f"📊 Ativos analisados: *{total_analisados}* | Acionados: *{total_acionados}*\n"
            f"💰 Risco/Trade: *${risco_por_trade_usd:.2f}*\n"
            f"✉️ Relatório de Earnings gerado e enviado por e-mail."
        )
        enviar_alerta(mensagem_debug)

if __name__ == "__main__":
    executar_motor()
