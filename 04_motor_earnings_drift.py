# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR DE EARNINGS DRIFT (PEAD)
# ===================================================================
# Descrição Geral:
# Caçador de Post-Earnings Announcement Drift (PEAD) via GitHub Actions.
# Filtra ativos líderes (RS >= 70) com earnings nos últimos 5 dias úteis
# e explosão institucional (salto >= 2.0% e RVOL >= 2.0).
# Gatilho: BUY STOP acima da máxima do dia de impulso (High * 1.002)
# Stop Loss: Limite técnico (max entre Low * 0.995 e Entrada - 2.0 * ATR)
# Alvo: 2.0R | Dimensionamento exato pelo risco por trade configurado.
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
# 2. FUNÇÕES DE REDE E RESILIÊNCIA YAHOO FINANCE
# ===================================================================
def get_yf_history_safe(ticker_str, period="6mo"):
    """Descarrega histórico diário limpo (removendo eventuais barras intradiárias sem volume)."""
    for _ in range(3):
        try:
            time.sleep(random.uniform(0.7, 1.5))
            df = yf.download(ticker_str, period=period, interval="1d", progress=False, timeout=15, session=session)
            if not df.empty and len(df) >= 25:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])
                # Filtra barras parciais sem volume real (ex: pré-abertura antes das 14:30 WET)
                df = df[df['Volume'] > 0]
                if len(df) >= 25:
                    return df
        except Exception:
            time.sleep(2.0)
    return pd.DataFrame()

def obter_preco_tempo_real(ticker_str, fallback_close):
    """Obtém a cotação mais recente (regular, pre-market ou post-market) para evitar entradas obsoletas."""
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
        resp = requests.get(url_alvo, timeout=15)
        if resp.status_code == 200:
            dados = resp.json()
            if isinstance(dados, dict):
                ativos = dados.get("ativos", [])
                posicoes = dados.get("posicoesAtivas", {}) or dados.get("posicoes", {})
                configs = dados.get("configs", {})
            elif isinstance(dados, list):
                ativos = dados
                posicoes = {}
                configs = {}
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
def analisar_earnings_drift(ativo_info, risco_por_trade_usd, posicoes_ativas_dict):
    ticker = str(ativo_info.get("ticker", "")).strip().upper()
    nome_empresa = ativo_info.get("nome", "N/A")
    setor = str(ativo_info.get("setor", "Desconhecido")).strip()
    rs_score = ativo_info.get("rs_score", "N/A")

    if not ticker or ticker == "#N/A" or ticker == "NONE":
        return None
    if ticker in posicoes_ativas_dict:
        return None

    if ticker == "BRK-A":
        ticker = "BRK-B"

    # Alinhamento institucional: exige RS Score >= 70
    val_rs_num = limpar_float(rs_score)
    if val_rs_num is not None and val_rs_num < 70.0:
        print(f"[FILTRADO] {ticker} rejeitado por RS Score insuficiente ({val_rs_num} < 70).")
        return None

    try:
        df = get_yf_history_safe(ticker, period="6mo")
        if df.empty or len(df) < 25:
            return None

        ticker_obj, earnings_df = obter_earnings_dates_safe(ticker)

        if setor in ["Desconhecido", "N/A", "", "NONE"] and ticker_obj is not None:
            try:
                setor_yf = ticker_obj.info.get('sector')
                if setor_yf:
                    setor = setor_yf
            except Exception:
                pass

        df.ta.atr(length=14, append=True)
        df.ta.sma(length=20, append=True)
        df.ta.ema(length=9, append=True)
        
        media_volume_20 = df['Volume'].rolling(window=20).mean()
        df['RVOL'] = df['Volume'] / media_volume_20

        earnings_recente = False
        data_earnings_str = "N/A"
        
        if earnings_df is not None and not earnings_df.empty:
            hoje = datetime.now(ZoneInfo("Europe/Lisbon")).date()
            for idx, _ in earnings_df.head(4).iterrows():
                d_earn = idx.date() if hasattr(idx, 'date') else pd.to_datetime(idx).date()
                dias_passados = (hoje - d_earn).days
                # Aceita earnings reportados desde ontem à noite (-1/0) até 5 dias atrás
                if -1 <= dias_passados <= 5:
                    earnings_recente = True
                    data_earnings_str = d_earn.strftime('%d/%m/%Y')
                    break

        if not earnings_recente:
            return None

        ultimo_dia = df.iloc[-1]
        dia_anterior = df.iloc[-2]

        fecho_ultimo = float(ultimo_dia['Close'])
        preco_anterior = float(dia_anterior['Close'])
        maximo_dia = float(ultimo_dia['High'])
        minimo_dia = float(ultimo_dia['Low'])
        rvol = float(ultimo_dia['RVOL'])
        
        cols_atr = [c for c in df.columns if str(c).startswith('ATRr_') or str(c).startswith('ATR_')]
        atr = float(ultimo_dia[cols_atr[0]]) if cols_atr and pd.notna(ultimo_dia[cols_atr[0]]) else np.nan

        # Verifica preço mais recente (inclui pós-fecho / pré-abertura)
        preco_rt = obter_preco_tempo_real(ticker, fecho_ultimo)
        preco_ref = max(fecho_ultimo, preco_rt)
        var_perc = ((preco_ref - preco_anterior) / preco_anterior) * 100

        if var_perc >= 2.0 and rvol >= 2.0:
            estado = "EARNINGS MOMENTUM - Drift Detetado"
            
            # Gatilho BUY STOP acima da máxima da vela de impulso (e nunca abaixo do preço atual)
            topo_referencia = max(maximo_dia, preco_rt)
            entrada = round(topo_referencia * 1.002, 2)
            
            # Stop Loss técnico: protege abaixo da mínima do dia, mas limita a 2.0x ATR para não distorcer o alvo
            stop_por_minima = minimo_dia * 0.995
            stop_por_atr = entrada - (atr * 2.0) if (pd.notna(atr) and atr > 0) else stop_por_minima
            stop_loss = round(max(stop_por_minima, stop_por_atr), 2)
            
            risco = entrada - stop_loss
            if risco <= 0:
                return None

            alvo_tp = round(entrada + (risco * 2.0), 2)
            qtd_acoes = round(risco_por_trade_usd / risco, 2)
                
            if qtd_acoes <= 0:
                print(f"[FILTRADO] {ticker} rejeitado por quantidade calculada nula.")
                return None

            val_calc = entrada * qtd_acoes
            valor_investir = f"~${val_calc:.2f} USD"
        else:
            return None

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
            f"DataEarnings: {data_earnings_str},VarDia: {limpa(var_perc)}%,RVOL: {limpa(rvol)},"
            f"Estado: {estado},Ordem: BUY STOP,Entrada: {limpa(entrada)},Stop: {limpa(stop_loss)},"
            f"Take-Profit: {limpa(alvo_tp)},Qtd: {qtd_acoes},ValorInvestir: {valor_investir},"
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
        
    capital_total_conta = limpar_float(configs.get("CAPITAL_TOTAL_CONTA")) or 10400.00
    pct_risco = (
        limpar_float(configs.get("RISCO_POR_TRADE")) or 
        limpar_float(configs.get("RISCO_SWING_PCT")) or 
        0.0025
    )
    risco_fixo_usd = limpar_float(configs.get("RISCO_MAXIMO_USD"))
    risco_por_trade_usd = risco_fixo_usd if (risco_fixo_usd and risco_fixo_usd > 0) else (capital_total_conta * pct_risco)

    print(f"[CONFIG] Capital Total da Conta: ${capital_total_conta:,.2f}")
    print(f"[CONFIG] Orçamento de Risco por Trade: ${risco_por_trade_usd:,.2f} USD\n")

    total_analisados = 0
    for ativo_info in ativos:
        ticker = ativo_info.get("ticker")
        if not ticker or ticker == "#N/A": continue
        
        total_analisados += 1
        res = analisar_earnings_drift(ativo_info, risco_por_trade_usd, posicoes_ativas_dict)
        
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

    prompt_ia = (
        "MODO CAÇADOR DE EARNINGS DRIFT (PEAD)\n"
        "O teu mandato é auditar os sinais gerados pelo motor Python e formatá-los para leitura do gestor da conta.\n\n"
        "🚨 REGRAS DE OURO (ANTI-ALUCINAÇÃO DE DADOS) 🚨\n"
        "1. ZERO CRIATIVIDADE: É ESTRITAMENTE PROIBIDO inventar, alucinar ou deduzir métricas de EPS, lucros, receitas, previsões de analistas ou datas que não te sejam dadas.\n"
        "2. FONTE ÚNICA: Retira os dados EXCLUSIVAMENTE da linha do comboio fornecida pelo motor. Não utilizes o teu conhecimento base de treino sobre a empresa.\n"
        "3. NARRATIVA NEUTRA: Se não tiveres detalhes sobre o motivo da subida na linha do comboio, escreve apenas 'Anomalia estatística detetada pelo algoritmo'.\n\n"
        "Estrutura Visual Obrigatória:\n"
        "🎯 [TICKER] - [Nome da Empresa] ([Setor])\n"
        "- 🚀 CATALISADOR DE EARNINGS: Data do evento: [DataEarnings] | Salto inicial: [VarDia%]\n"
        "- 📊 CONTEXTO INSTITUCIONAL (RS SCORE): [Incluir o RS Score e o respetivo estado institucional reportado]\n"
        "- 🩸 PEGADA INSTITUCIONAL: RVOL detetado de [RVOL]\n"
        "- ⚙️ TÁTICA: EARNINGS DRIFT. Surfar tendência com rácio 2:1.\n"
        "- 🔢 DADOS EXATOS: Ordem: BUY STOP | Entrada: X | Stop: X | TP: X | Qtd: X | Valor a Investir: X\n"
        "- 📋 REFERÊNCIA: [Copia e cola a Linha do Comboio exata fornecida abaixo]\n"
    )
    
    bloco_texto_ia = f"📊 RELATÓRIO DE DADOS BRUTOS - EARNINGS DRIFT 🚀\n\n{prompt_ia}\n\n--------------------------------------------------\n"

    if not comboio_ia:
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
            f"🔍 Execução concluída com sucesso.\n"
            f"📊 Ativos analisados: *{total_analisados}* | Acionados: *{total_acionados}*\n"
            f"💰 Risco/Trade: *${risco_por_trade_usd:.2f}*\n"
            f"✉️ Relatório de Earnings gerado e enviado por e-mail."
        )
        enviar_alerta(mensagem_debug)

if __name__ == "__main__":
    executar_motor()
