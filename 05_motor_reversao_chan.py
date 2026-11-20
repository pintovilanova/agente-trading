# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR DE REVERSÃO CONNORS-CHAN (RSI 2 + BB)
# ===================================================================
# Descrição Geral:
# Implementa a estratégia quantitativa de curto prazo de Larry Connors & Ernest Chan:
#   - Tendência Primária obrigatória: Close > SMA 200 + Liquidez institucional
#   - Exaustão Estatística: Close < Banda Bollinger Inferior (20, 2.0) e RSI(2) < 10
#   - Saída Mecânica: Banda Central de Bollinger (SMA 20)
#   - Regime Macro (SPY/VIX):
#       * Expansão (SPY > EMA20): RS >= 60 | Lote 100%
#       * Corretivo (SMA200 < SPY <= EMA20): RS >= 75 | Lote 50%
#       * Baixista (SPY < SMA200, crash <= -2.5% ou VIX > 32): Bloqueia entradas
# ===================================================================

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
    print("[INFO] Fim de semana detetado. O mercado está fechado. O Motor Connors-Chan vai descansar.")
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
# 2. FUNÇÕES DE REDE, REGIME MACRO & PREÇO TEMPO REAL
# ===================================================================
def verificar_regime_mercado_connors():
    """
    Avalia o regime do SPY para Connors-Chan (RSI 2 + BB):
    - Expansão (SPY > EMA20): RS >= 60 | Fator Lote 1.0 (0.5 se VIX > 25)
    - Corretivo (SMA200 < SPY <= EMA20): RS >= 75 | Fator Lote 0.5 (0.35 se VIX > 25)
    - Baixista / Crash / Pânico Sistémico: Bloqueia novas entradas
    """
    regime_default = {
        "autorizado": True,
        "modo": "EXPANSAO",
        "rs_min": 60.0,
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
                "rs_min": 80.0,
                "fator_risco": 0.0,
                "msg": f"SPY (${close_hoje:.2f}) abaixo da SMA200 (${sma200:.2f}). Mercado em tendência de baixa{tag_vix}."
            }
        if var_dia <= -2.5:
            return {
                "autorizado": False,
                "modo": "CRASH",
                "rs_min": 80.0,
                "fator_risco": 0.0,
                "msg": f"SPY em queda extrema hoje ({var_dia:.2f}% <= -2.50%){tag_vix}. Entradas suspensas."
            }
        if vix_atual is not None and vix_atual > 32.0:
            return {
                "autorizado": False,
                "modo": "PANICO_SISTEMICO",
                "rs_min": 80.0,
                "fator_risco": 0.0,
                "msg": f"VIX em pânico sistémico extremo ({vix_atual:.2f} > 32.00)."
            }

        if close_hoje < ema20:
            fator = 0.35 if (vix_atual is not None and vix_atual > 25.0) else 0.50
            return {
                "autorizado": True,
                "modo": "CORRETIVO",
                "rs_min": 75.0,
                "fator_risco": fator,
                "msg": (
                    f"SPY em correção (${close_hoje:.2f} < EMA20 ${ema20:.2f} | SMA200 ${sma200:.2f} | "
                    f"Var: {var_dia:+.2f}%{tag_vix}) — Connors Seletivo: RS >= 75 e Lote {int(fator*100)}%."
                )
            }

        fator = 0.50 if (vix_atual is not None and vix_atual > 25.0) else 1.0
        return {
            "autorizado": True,
            "modo": "EXPANSAO",
            "rs_min": 60.0,
            "fator_risco": fator,
            "msg": (
                f"SPY em Expansão (${close_hoje:.2f} > EMA20 ${ema20:.2f} > SMA200 ${sma200:.2f} | "
                f"Var: {var_dia:+.2f}%{tag_vix}) — RS >= 60 | Lote {int(fator*100)}%."
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
                
            print(f"[SUCESSO] {len(ativos)} ativos carregados para motor Connors-Chan.")
            return ativos, posicoes, configs
        else:
            print(f"[ERRO] Falha ao descarregar dados: {resp.status_code}")
            return [], {}, {}
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha de comunicação com Sheets: {e}")
        return [], {}, {}

def enviar_email(conteudo):
    print("\nA enviar email do Motor Connors-Chan para o Agente IA...")
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] Credenciais de email em falta. A saltar envio.")
        return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = f"🧲 tradingRelatorioIA US - CONNORS-CHAN REVERSÃO ({datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')}) 🏹"
    msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
    
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
            print(f"[ERRO] Falha ao enviar email (tentativa {tentativa + 1} de {max_tentativas}): {e}")
            if tentativa < max_tentativas - 1:
                time.sleep(5)
            else:
                print("[ERRO CRÍTICO] Falha definitiva no envio de email.")

# ===================================================================
# 3. MOTOR MATEMÁTICO: CONNORS-CHAN (RSI(2) + BANDAS DE BOLLINGER)
# ===================================================================
def analisar_connors_chan(ativo_info, risco_por_trade_usd, tickers_ativos_set, setores_ocupados, regime):
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

        ultimo_dia = df.iloc[-1]
        preco = float(ultimo_dia['Close'])
        vol_medio_20 = float(df['Volume'].rolling(20).mean().iloc[-1])

        # Exige liquidez institucional (Preço >= $10 e Volume Médio 20d >= 300k)
        if pd.isna(preco) or preco < 10.00 or pd.isna(vol_medio_20) or vol_medio_20 < 300000:
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

        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        df.ta.bbands(length=20, std=2.0, append=True)
        df.ta.rsi(length=2, append=True)            
        df.ta.atr(length=14, append=True)            

        col_bbl = [c for c in df.columns if str(c).startswith('BBL_')]
        col_bbm = [c for c in df.columns if str(c).startswith('BBM_')]
        col_rsi = [c for c in df.columns if str(c).startswith('RSI_2')]
        col_atr = [c for c in df.columns if str(c).startswith('ATRr_') or str(c).startswith('ATR_')]

        if not col_bbl or not col_bbm or not col_rsi or not col_atr:
            return None

        nome_bbl = col_bbl[0]
        nome_bbm = col_bbm[0]
        nome_rsi = col_rsi[0]
        nome_atr = col_atr[0]

        df = df.dropna(subset=['SMA_200', nome_bbl, nome_bbm, nome_rsi, nome_atr])
        if df.empty:
            return None

        ultimo_dia = df.iloc[-1]

        sma200 = float(ultimo_dia['SMA_200'])
        bbl_inferior = float(ultimo_dia[nome_bbl])
        bb_media = float(ultimo_dia[nome_bbm])
        rsi_2 = float(ultimo_dia[nome_rsi])
        atr = float(ultimo_dia[nome_atr])
        minimo = float(ultimo_dia['Low'])

        # Regra de Ouro de Connors: Só comprar exaustão de RSI(2) em tendência primária de alta (Close > SMA 200)
        if preco <= sma200:
            return None

        estado = "Observar"
        entrada = "N/A"
        alvo_tp = "N/A"
        stop_loss = "N/A"
        qtd_acoes = "N/A"
        valor_investir = "N/A"
        
        if (preco < bbl_inferior) and (rsi_2 < 10.0):
            preco_rt = obter_preco_tempo_real(ticker, preco)
            # Se o preço em pré-abertura/pós-fecho já repicou para perto da SMA20, o sinal expirou
            if preco_rt >= bb_media:
                return None

            estado = f"EXAUSTÃO ESTATÍSTICA - Connors-Chan ({regime['modo']})"
            entrada = round(min(preco, preco_rt), 2)
            alvo_tp = round(bb_media, 2)
            
            stop_calc = entrada - (atr * 1.5) if atr > 0 else minimo * 0.98
            stop_loss = round(min(stop_calc, minimo * 0.99), 2)
            
            risco = entrada - stop_loss
            recompensa = alvo_tp - entrada
            
            if recompensa < (risco * 1.1) or risco <= 0:
                return None

            # Dimensionamento pelo RISCO REAL (Entrada - Stop) para garantir perda máxima controlada
            qtd_calc = round(risco_por_trade_usd / risco, 2)
            if qtd_calc <= 0:
                return None

            qtd_acoes = qtd_calc
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
            elif val_rs_num >= 70:
                status_rs = "⚖️ FORTE (RS 70-79 - Suporte Institucional)"
            else:
                status_rs = "⚠️ MODERADO (RS 60-69 - Tendência Primária > SMA200)"
        else:
            status_rs = "❓ SEM DADO DE RS"

        linha_comboio = (
            f"{ticker},Nome: {nome_empresa},Setor: {setor},Preço: {limpa(preco)},"
            f"RS Score: {rs_score} ({status_rs}),"
            f"BBLower: {limpa(bbl_inferior)},SMA20 (Alvo): {limpa(bb_media)},RSI2: {limpa(rsi_2)},"
            f"Estado: {estado},Ordem: BUY LIMIT,Entrada: {limpa(entrada)},"
            f"Stop: {limpa(stop_loss)},Take-Profit (SMA20): {limpa(alvo_tp)},"
            f"Qtd: {qtd_acoes},ValorInvestir: {valor_investir},Earnings: {alerta_earnings},"
            f"Data: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
        )

        return {
            "ticker": ticker,
            "estado": estado,
            "comboio_str": linha_comboio
        }

    except Exception as e:
        print(f"[ERRO] Falha ao processar ativo {ativo_info.get('ticker', 'N/A')}: {e}")
        return None

# ===================================================================
# 4. EXECUÇÃO PRINCIPAL E GERAÇÃO DE PROMPT
# ===================================================================
def executar_motor():
    ativos, posicoes_ativas_dict, configs = buscar_dados_completos()
    if not ativos:
        print("[AVISO] Nenhum ativo carregado. A terminar a execução sem erro.")
        sys.exit(0)

    regime_macro = verificar_regime_mercado_connors()
        
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

    ativos_acionados = []
    total_analisados = 0
    
    if regime_macro["autorizado"]:
        for ativo_info in ativos:
            ticker = ativo_info.get("ticker")
            if not ticker or ticker == "#N/A": continue
            
            total_analisados += 1
            res = analisar_connors_chan(ativo_info, risco_ajustado_usd, tickers_ativos_set, setores_ocupados, regime_macro)
            
            if res:
                print(f"[OK] {ticker} analisado. Estado: {res['estado']}")
                if "EXAUSTÃO ESTATÍSTICA" in res['estado']:
                    ativos_acionados.append(res)
                
    prompt_ia = """MODO PREDADOR CONNORS-CHAN (REVERSÃO DE CURTO PRAZO)
O teu mandato é auditar os sinais estatísticos gerados pelo motor Python e formatá-los.

🚨 REGRAS DE OURO (ANTI-ALUCINAÇÃO DE DADOS) 🚨
1. ZERO CRIATIVIDADE: É ESTRITAMENTE PROIBIDO inventar notícias, motivos de queda, lucros, previsões ou datas que não estejam na linha do comboio.
2. FONTE ÚNICA: Retira os dados EXCLUSIVAMENTE da linha do comboio fornecida.
3. NARRATIVA NEUTRA: Se não tiveres detalhes sobre o motivo da queda, escreve apenas 'Anomalia estatística baseada em exaustão técnica extrema'.

Regras de Triagem e Execução:
1. VALIDAÇÃO DE EXAUSTÃO: Confirma que o RSI(2) está abaixo de 10 e que o preço rompeu a Banda de Bollinger inferior em tendência primária > SMA200.
2. CONTEXTO INSTITUCIONAL (RS SCORE): Avalia o RS Score reportado. Se o ativo tiver RS Score de Elite (>= 80), o ressalto beneficia de suporte forte.
3. VETO FUNDAMENTAL: O motor já filtra ações <$10, baixa liquidez, mREITs, ativos abaixo da SMA200 e Earnings iminentes. Emite veto caso exista notícia de fraude ou revisão drástica de guidance.
4. TÁTICA DE SAÍDA: O alvo de Take-Profit é cravado na Banda Central de Bollinger (SMA20).
5. TÁTICA DE ENTRADA: Execução disciplinada com Buy Limit respeitando o orçamento de risco do regime atual.

Estrutura Visual Obrigatória:
🎯 [TICKER] - [Nome da Empresa] ([Setor])
- 🚨 SINAL CONNORS-CHAN: [Destacar BBLower e RSI(2) extremo]
- 📊 CONTEXTO INSTITUCIONAL (RS SCORE): [Incluir o RS Score e o respetivo estado institucional reportado]
- ⚙️ TÁTICA: SWING REVERSION. Alvo na SMA20 / Banda Média.
- 🔢 DADOS EXATOS: Entrada: X | Stop: X | TP (SMA20): X | Qtd: X | Valor a Investir: X
- 📋 REFERÊNCIA: [Linha do Comboio exata]
"""
    
    bloco_texto_ia = (
        f"🧲 RELATÓRIO DE DADOS BRUTOS - CONNORS-CHAN REVERSÃO 🏹\n"
        f"🌐 Filtro Macro: {regime_macro['msg']}\n"
        f"💰 Risco Configurado por Trade: ${risco_ajustado_usd:.2f} USD (Base: ${risco_base_usd:.2f} | Fator: {int(regime_macro['fator_risco']*100)}%)\n\n"
        f"{prompt_ia}\n\n--------------------------------------------------\n"
    )
    
    if not regime_macro["autorizado"]:
        bloco_texto_ia += f"🛡️ [MODO DEFENSIVO] Novas entradas Connors-Chan bloqueadas hoje ({regime_macro['msg']}).\n"
    elif not ativos_acionados:
        bloco_texto_ia += "[SEM SINAIS CONNORS-CHAN] - Nenhuma ação da Watchlist cumpre os critérios de exaustão estatística hoje.\n"
    else:
        bloco_texto_ia += "DADOS DOS ATIVOS EM EXAUSTÃO (COMBOIO):\n\n"
        for item in ativos_acionados:
            bloco_texto_ia += item["comboio_str"] + "\n"
            
    with open("comboio_connors_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco_texto_ia)
        
    enviar_email(bloco_texto_ia)

    # ===================================================================
    # 5. NOTIFICAÇÃO TELEGRAM (DEBUG OU SINAL CONNORS-CHAN DETETADO)
    # ===================================================================
    debug_telegram_ativado = str(configs.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

    if debug_telegram_ativado or len(ativos_acionados) > 0:
        print("A enviar notificação para o Telegram via função modular...")
        total_acionados = len(ativos_acionados)
        mensagem_debug = (
            f"05 🧲 *MOTOR CONNORS-CHAN (REVERSÃO)*\n\n"
            f"🔍 Execução concluída ({regime_macro['modo']}).\n"
            f"📊 Ativos analisados: *{total_analisados}* | Acionados: *{total_acionados}*\n"
            f"💰 Risco/Trade: *${risco_ajustado_usd:.2f} USD*\n"
            f"✉️ Relatório Connors-Chan gerado e enviado por e-mail."
        )
        enviar_alerta(mensagem_debug)

if __name__ == "__main__":
    executar_motor()
