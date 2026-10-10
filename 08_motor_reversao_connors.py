# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR MEAN REVERSION (LARRY CONNORS)
# ===================================================================================
# Documentação e Arquitetura do Módulo:
# 1. OBJETIVO:
#    Identificar oportunidades de compra em "Elástico Esticado". Procura ações fortes
#    (Bull Market) que sofreram um mini-crash temporário (pânico irracional) e estão
#    prontas a fazer o "snap-back" (ressalto) imediato.
#
# 2. INDICADORES TÉCNICOS & CÁLCULOS (Sistema RSI-2):
#    - Filtro Macro Estrutural: Preço atual > SMA 200 (Tendência Primária de Alta).
#    - Condição de Pânico (Stretch): Preço atual < SMA 5.
#    - Sobrevenda Extrema: RSI de 2 períodos (RSI-2) inferior a 10.
#
# 3. GESTÃO DE RISCO E DIMENSIONAMENTO:
#    - Execução: Ordem Limit (Comprar a um preço igual ou ligeiramente abaixo do fecho).
#    - Dimensionamento: Volatility Parity usando ATR de 14 dias.
#    - Tática Sniper: Não se usa Trailing Stop para capturar tendência. A saída é  
#      cirúrgica e mecânica assim que o preço cruzar ACIMA da SMA 5.
#    - Stop Catástrofe: Stop Loss de segurança posicionado a 2.5x ATR abaixo da entrada.
#
# 4. GESTÃO DE ESTADOS NO SHEETS:
#    - 'ATIVA_MR': Estado para as ações geridas por este motor. O motor vai ler 
#      este estado nas posições ativas e avisar-te do dia exato para vender.
# ===================================================================================

import pandas as pd
import yfinance as yf
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo
import sys
import os
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O Motor Reversão à Média vai descansar.")
    sys.exit(0)

# ===================================================================
# 1. CONFIGURAÇÕES E CREDENCIAIS
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

CAPITAL_TOTAL_CONTA = 10400.00  
ALVO_VOLATILIDADE_ANUAL = 0.05  
VOLATILIDADE_ALVO_DIARIA_USD = (CAPITAL_TOTAL_CONTA * ALVO_VOLATILIDADE_ANUAL) / 16.0 

# ===================================================================
# 2. FUNÇÕES DE REDE
# ===================================================================
def buscar_dados_completos():
    print("A carregar a Watchlist e Posições Ativas (Sheets)...")
    if not WEBHOOK_URL: 
        return [], {}
    try:
        resp = requests.get(WEBHOOK_URL)
        if resp.status_code == 200:
            dados = resp.json()
            if isinstance(dados, dict):
                return dados.get("ativos", []), dados.get("posicoesAtivas", {})
            elif isinstance(dados, list):
                return dados, {}
        return [], {}
    except Exception as e:
        print(f"[ERRO CRÍTICO] Sheets: {e}")
        return [], {}

def enviar_email_bruto(conteudo):
    print("\nA enviar o relatório para o Agente IA via email...")
    if not EMAIL_USER or not EMAIL_PASS:
        return
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_USER
        # Assunto OBRIGATÓRIO para o Agente IA (02_agente_gemini.py) o reconhecer
        msg['Subject'] = "tradingRelatorioIA US - CONNORS-CHAN"
        msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
        server.quit()
        print("[SUCESSO] Email bruto de Reversão enviado!")
    except Exception as e:
        print(f"[ERRO] Falha ao enviar email: {e}")

# ===================================================================
# 3. MOTOR MATEMÁTICO: REVERSÃO À MÉDIA E RSI-2
# ===================================================================
def calcular_indicadores_mr(ticker):
    try:
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if df.empty or len(df) < 200:
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        # Médias Simples (Connors usa muito SMAs)
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        df['SMA_5'] = df['Close'].rolling(window=5).mean()

        # Cálculo do RSI de 2 Períodos (Wilder)
        delta = df['Close'].diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        ema_up = up.ewm(com=1, adjust=False).mean()
        ema_down = down.ewm(com=1, adjust=False).mean()
        rs = ema_up / ema_down
        df['RSI_2'] = 100 - (100 / (1 + rs))

        # ATR para Dimensionamento e Stop de Segurança
        high = df['High']
        low = df['Low']
        close = df['Close']
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['ATR_14'] = tr.rolling(window=14).mean()

        ultimo = df.iloc[-1]
        
        return {
            "preco": float(ultimo['Close']),
            "sma200": float(ultimo['SMA_200']),
            "sma5": float(ultimo['SMA_5']),
            "rsi2": float(ultimo['RSI_2']),
            "atr14": float(ultimo['ATR_14'])
        }
    except Exception as e:
        print(f"[ERRO] Falha técnica em {ticker}: {e}")
        return None

def analisar_setup_connors(ticker, nome_empresa, setor):
    ind = calcular_indicadores_mr(ticker)
    if not ind: return None
    
    preco, sma200, sma5, rsi2, atr = ind['preco'], ind['sma200'], ind['sma5'], ind['rsi2'], ind['atr14']
    
    if pd.isna(sma200) or pd.isna(rsi2) or pd.isna(atr):
        return None

    # FILTROS DE ALTA PRECISÃO LARRY CONNORS
    bull_market = preco > sma200
    panico_curto_prazo = preco < sma5
    sobrevenda_extrema = rsi2 < 10.0

    if bull_market and panico_curto_prazo and sobrevenda_extrema:
        estado_str = "PÂNICO/STRETCH - Elástico Esticado"
        
        # A entrada é feita em ordem Limite perto do fecho (apanhar o medo extremo)
        entrada_sugerida = round(preco, 2)
        
        # Stop Catástrofe (Apenas para proteção extrema, não deve ser acionado na teoria)
        stop_catastrofe = round(entrada_sugerida - (atr * 2.5), 2)
        
        # Volatility Parity Sizing
        qtd_acoes = round(VOLATILIDADE_ALVO_DIARIA_USD / atr, 2) if atr > 0 else 0
        val_calc = entrada_sugerida * qtd_acoes
        valor_investir = f"~{val_calc:.2f} USD"

        def limpa(v): return round(float(v), 2)

        linha_comboio = (
            f"{ticker},Nome: {nome_empresa},Setor: {setor},Preço Atual: {limpa(preco)},"
            f"SMA 200: {limpa(sma200)},SMA 5: {limpa(sma5)},RSI(2): {limpa(rsi2)},"
            f"Estado: {estado_str},Entrada (Limit): {limpa(entrada_sugerida)},"
            f"Stop Catástrofe: {limpa(stop_catastrofe)},TP: Fecho > SMA 5,"
            f"Qtd: {qtd_acoes},ValorInvestir: {valor_investir},"
            f"Data: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
        )

        return {
            "ticker": ticker,
            "rsi2": rsi2,
            "comboio_str": linha_comboio
        }
    return None

def monitorizar_posicao_ativa_mr(ticker, nome_empresa, status_atual, dados_posicao):
    ind = calcular_indicadores_mr(ticker)
    if not ind: return None
    
    preco, sma5, atr, stop_catastrofe = ind['preco'], ind['sma5'], ind['atr14'], None
    preco_entrada = dados_posicao.get("precoEntrada", "N/A")
    quantidade = dados_posicao.get("quantidade", "N/A")
    
    # Lógica Mecânica de Saída do Connors
    # O setup manda vender APENAS quando o preço fecha acima da SMA 5.
    if preco > sma5:
        acao_recomendada = f"🟢 O ELÁSTICO RECOLHEU! O preço de fecho ({preco:.2f}) cruzou ACIMA da SMA 5 ({sma5:.2f}). VENDER A MERCADO na próxima sessão e fechar posição."
    else:
        acao_recomendada = f"🟡 MANTER. O pânico ainda vigora. O preço ({preco:.2f}) continua abaixo da SMA 5 ({sma5:.2f}). Aguardar o ressalto."

    linha_monitorizacao = (
        f"📌 [POSIÇÃO ATIVA - {status_atual}] {ticker} ({nome_empresa}) | "
        f"Qtd: {quantidade} | Entrada: {preco_entrada} | Preço Atual: {preco:.2f} | "
        f"SMA 5 Atual: {sma5:.2f} | RSI(2): {ind['rsi2']:.2f} | "
        f"🛑 AÇÃO TÁTICA: {acao_recomendada}"
    )
    return linha_monitorizacao

# ===================================================================
# 4. EXECUÇÃO PRINCIPAL
# ===================================================================
def executar_motor():
    ativos, posicoes_ativas_dict = buscar_dados_completos()
    if not ativos and not posicoes_ativas_dict:
        sys.exit(1)
        
    ativos_acionados = []
    posicoes_em_gestao = []

    # 1. Analisa novos pânicos (ignora as que já compraste)
    for ativo_info in ativos:
        ticker = ativo_info.get("ticker")
        if not ticker or ticker == "#N/A": continue
        
        if ticker in posicoes_ativas_dict:
            continue

        res = analisar_setup_connors(ticker, ativo_info.get("nome", "N/A"), ativo_info.get("setor", "Desconhecido"))
        if res:
            ativos_acionados.append(res)
            
    # 2. Monitoriza ativas APENAS se o estado for ATIVA_MR (Mean Reversion)
    for ticker, dados_pos in posicoes_ativas_dict.items():
        status_atual = dados_pos.get("status", "").strip().upper()
        if status_atual != "ATIVA_MR":
            continue
            
        nome = dados_pos.get("nome", ticker)
        monitorizacao = monitorizar_posicao_ativa_mr(ticker, nome, status_atual, dados_pos)
        if monitorizacao:
            posicoes_em_gestao.append(monitorizacao)

    # Ordenar pelas mais sobrevendidas (menor RSI-2)
    ativos_acionados = sorted(ativos_acionados, key=lambda k: k['rsi2'])

    prompt_ia = (
        "MODO SNIPER - REVERSÃO À MÉDIA (Larry Connors Pullbacks)\n"
        "O teu mandato é auditar entradas em ações fortes que estão a sofrer um mini-crash (pânico irracional) e "
        "monitorizar o ressalto técnico (snap-back) daquelas que já estão em carteira.\n\n"
        "REGRAS ESTRITAS:\n"
        "1. DINÂMICA: Este é um trade tático curto (2 a 5 dias). Não há Take-Profit fixo e o Stop Loss é apenas uma rede de catástrofe distante.\n"
        "2. SAÍDA MECÂNICA: A saída deve ser executada a mercado APENAS no dia em que o preço de fecho cruzar acima da SMA 5.\n"
        "- 🔄 GESTÃO DE ESTADOS NO SHEETS (LEMBRETE OBRIGATÓRIO):\n"
        "  1. \"🟢 NOVAS ENTRADAS: Se abrires posição, altera o estado no Sheets para 'ATIVA_MR' (Mean Reversion). Isso impedirá que o motor Carver a confunda com uma tendência e eu irei avisar-te do dia exato para vender.\"\n"
        "  2. \"🔴 SAÍDAS (RESGATE DO ELÁSTICO): Se eu te der o sinal 'O ELÁSTICO RECOLHEU', vende a ação, regista os lucros e altera o estado para 'WIN' (ou 'LOSS') no Sheets.\"\n"
    )
    
    bloco_texto_ia = f"📊 RELATÓRIO PÂNICO & REVERSÃO (RSI-2) 🏹\n\n{prompt_ia}\n\n--------------------------------------------------\n"

    if posicoes_em_gestao:
        bloco_texto_ia += "GESTÃO DE POSIÇÕES ATIVAS (ATIVA_MR - VIGILÂNCIA DA SMA 5):\n\n"
        for pos in posicoes_em_gestao:
            bloco_texto_ia += pos + "\n\n"
        bloco_texto_ia += "--------------------------------------------------\n"

    if not ativos_acionados:
        bloco_texto_ia += "[MERCADO ESTÁVEL] - Nenhuma ação apresenta sinais de pânico extremo (RSI-2 < 10) num Bull Market hoje.\n"
    else:
        bloco_texto_ia += "OPORTUNIDADES DE RESSALTO / PÂNICO EXTREMO:\n\n"
        for item in ativos_acionados:
            bloco_texto_ia += item["comboio_str"] + "\n\n"

    # NOME EXATO DO FICHEIRO PARA O AGENTE IA DETETAR A ESTRATÉGIA
    with open("comboio_connors_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco_texto_ia)

    enviar_email_bruto(bloco_texto_ia)

if __name__ == "__main__":
    executar_motor()
