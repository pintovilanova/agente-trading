# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR DE COMPRESSÃO VCP (BREAKOUT)
# ===================================================================
# Descrição Geral:
# Este script atua como um rastreador de "Molas Comprimidas" (Volatility 
# Contraction Pattern - VCP / Bollinger Squeeze). O objetivo é detetar 
# ativos saudáveis em tendência de alta que entraram num período de 
# consolidação extrema e seca de volume institucional, antecipando uma 
# rutura (breakout) iminente e explosiva.
#
# Pilares Técnicos e Arquitetura:
# 1. Filtro de Tendência Estrutural (Mark Minervini):
#    - Preço > SMA 50 > SMA 200 (Garante que a consolidação ocorre num Bull Market).
# 2. Gatilhos de Compressão (O "Squeeze"):
#    - Bollinger Band Width (BBW) nos níveis mais baixos dos últimos 120 dias.
#    - Contração de Preço: Intervalo (High - Low) dos últimos 5 dias muito estreito.
#    - Seca de Volume: Volume médio dos últimos 3 dias < 60% da média de 50 dias.
# 3. Gestão de Risco de Alta Precisão:
#    - Stop Loss cravado estritamente abaixo do mínimo dos últimos 5 dias (risco mínimo).
#    - Entrada (Buy Stop) acima do máximo dos últimos 5 dias.
#    - Dimensionamento baseado na volatilidade (ATR) adaptado ao micro-risco.
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
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O Motor VCP vai descansar.")
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
def buscar_watchlist():
    print("A carregar a Watchlist a partir do Google Sheets...")
    if not WEBHOOK_URL: 
        return []
    try:
        resp = requests.get(WEBHOOK_URL)
        if resp.status_code == 200:
            dados = resp.json()
            ativos = dados.get("ativos", []) if isinstance(dados, dict) else dados
            return ativos
        return []
    except Exception as e:
        print(f"[ERRO CRÍTICO] Sheets: {e}")
        return []

def enviar_email(conteudo):
    print("\nA enviar email VCP/Squeeze para o Agente IA...")
    if not EMAIL_USER or not EMAIL_PASS:
        return
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_USER
        msg['Subject'] = "🎯 tradingRelatorioIA US - VCP BREAKOUT SQUEEZE"
        msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
        server.quit()
        print("[SUCESSO] Email enviado!")
    except Exception as e:
        print(f"[ERRO] Falha ao enviar email: {e}")

# ===================================================================
# 3. MOTOR MATEMÁTICO: COMPRESSÃO DE VOLATILIDADE
# ===================================================================
def analisar_compressao_vcp(ticker, nome_empresa, setor):
    try:
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if df.empty or len(df) < 200:
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        preco = float(df.iloc[-1]['Close'])
        
        # Filtros Anti-Lixo
        if pd.isna(preco) or preco < 5.00:
            return None
        if setor and any(termo in setor.lower() for termo in ["real estate", "reit"]):
            return None

        # Médias de Tendência
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        
        # Bollinger Bands & Band Width (BBW)
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        df['STD_20'] = df['Close'].rolling(window=20).std()
        df['BB_Upper'] = df['SMA_20'] + (df['STD_20'] * 2)
        df['BB_Lower'] = df['SMA_20'] - (df['STD_20'] * 2)
        df['BBW'] = ((df['BB_Upper'] - df['BB_Lower']) / df['SMA_20']) * 100
        
        # Volume Seco
        df['Vol_SMA_50'] = df['Volume'].rolling(window=50).mean()
        vol_medio_3d = df['Volume'].iloc[-3:].mean()
        
        # ATR para Dimensionamento
        high = df['High']
        low = df['Low']
        close = df['Close']
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['ATR_14'] = tr.rolling(window=14).mean()

        ultimo = df.iloc[-1]
        sma50 = float(ultimo['SMA_50'])
        sma200 = float(ultimo['SMA_200'])
        bbw_atual = float(ultimo['BBW'])
        vol_sma50 = float(ultimo['Vol_SMA_50'])
        atr = float(ultimo['ATR_14'])
        
        # Caixote de 5 dias (High/Low da consolidação)
        max_5d = float(df['High'].iloc[-5:].max())
        min_5d = float(df['Low'].iloc[-5:].min())

        # ==============================================================
        # CONDIÇÕES DO GATILHO VCP (SQUEEZE)
        # ==============================================================
        # 1. Bull Market Estrutural
        tendencia_alta = (preco > sma50) and (sma50 > sma200)
        
        # 2. Compressão Histórica (BBW no percentil 15% mais baixo dos últimos 6 meses)
        bbw_120d_min = float(df['BBW'].iloc[-120:].min())
        squeeze_ativo = bbw_atual <= (bbw_120d_min * 1.5) and bbw_atual < 8.0
        
        # 3. Seca de Volume (Desinteresse / Sem pressão de venda)
        seca_volume = vol_medio_3d < (vol_sma50 * 0.6)

        if tendencia_alta and squeeze_ativo and seca_volume:
            estado = "SQUEEZE EXTREMO - Ignição Iminente"
            entrada_gatilho = round(max_5d * 1.002, 2) # Ligeiramente acima do máximo
            stop_loss = round(min_5d * 0.998, 2) # Ligeiramente abaixo do mínimo
            
            risco = entrada_gatilho - stop_loss
            alvo_tp = round(entrada_gatilho + (risco * 3), 2) # Rácio 3:1
            
            # Dimensionamento (Volatilidade Alvo)
            if atr > 0:
                qtd_acoes = round(VOLATILIDADE_ALVO_DIARIA_USD / atr, 2)
            else:
                qtd_acoes = round(VOLATILIDADE_ALVO_DIARIA_USD / risco, 2) if risco > 0 else "N/A"
                
            val_calc = entrada_gatilho * qtd_acoes if qtd_acoes != "N/A" else 0
            valor_investir = f"~{val_calc:.2f} USD"
            
            def limpa(v): return round(float(v), 2)
            
            linha_comboio = (
                f"{ticker},Nome: {nome_empresa},Setor: {setor},Preço: {limpa(preco)},"
                f"BBW Atual: {limpa(bbw_atual)}%,Volume 3D: Seco (-40%+),"
                f"Gatilho Compra (Buy Stop): {limpa(entrada_gatilho)},"
                f"Stop Físico (Min 5D): {limpa(stop_loss)},Alvo TP: {limpa(alvo_tp)},"
                f"Estado: {estado},Qtd: {qtd_acoes},ValorInvestir: {valor_investir},"
                f"Data: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
            )

            return {
                "ticker": ticker,
                "bbw": bbw_atual,
                "comboio_str": linha_comboio
            }
            
        return None
    except Exception as e:
        print(f"[ERRO] Falha ao processar {ticker}: {e}")
        return None

# ===================================================================
# 4. EXECUÇÃO PRINCIPAL
# ===================================================================
def executar_motor():
    ativos = buscar_watchlist()
    if not ativos:
        sys.exit(1)
        
    ativos_acionados = []
    for ativo_info in ativos:
        ticker = ativo_info.get("ticker")
        if not ticker or ticker == "#N/A": continue
        
        res = analisar_compressao_vcp(ticker, ativo_info.get("nome", "N/A"), ativo_info.get("setor", "Desconhecido"))
        if res:
            ativos_acionados.append(res)
            
    # Ordenar pelos ativos mais comprimidos (menor BBW)
    ativos_acionados = sorted(ativos_acionados, key=lambda k: k['bbw'])

    prompt_ia = """Atuas como Analista Quantitativo de Breakouts (Modelo Mark Minervini). O teu mandato é auditar ativos em fase de Squeeze (Contração de Volatilidade) preparados para explosão direcional.

REGRAS ESTRITAS:
1. O ativo não deve ser comprado a mercado. Recomenda SEMPRE ordens pendentes "Buy Stop" no Gatilho de Compra estipulado.
2. Destaca o facto do risco ser mínimo, dado que o Stop Loss está cravado na base da consolidação (caixote de 5 dias).
3. Avalia o Rácio Risco/Recompensa.

ESTRUTURA OBRIGATÓRIA:
🎯 [TICKER] - [Nome da Empresa] ([Setor])
- 🗜️ NÍVEL DE COMPRESSÃO: BBW a [X]% (Mola comprimida com seca de volume).
- ⚙️ TÁTICA DE EXECUÇÃO: Colocar ordem pendente Buy Stop em [Gatilho] para apanhar o breakout.
- 🛡️ RISCO MICRO: Stop Físico cravado em [Stop] (Abaixo da base de 5 dias).
- 🔢 DADOS: Alvo: [TP] | Qtd: [X] | Alocação: [Valor] USD.
- 🔄 PASSAGEM DE TESTEMUNHO: Adiciona explicitamente o texto: "⚠️ ATENÇÃO: Assim que esta ordem for executada na corretora, altera imediatamente o estado no Google Sheets para 'ATIVA_FAST'. O Motor Carver assumirá automaticamente a gestão do Trailing Stop a partir daí."
"""
    
    bloco_texto_ia = f"📊 RELATÓRIO VCP BREAKOUT / SQUEEZE 🗜️\n\n{prompt_ia}\n\n--------------------------------------------------\n"
    
    if not ativos_acionados:
        bloco_texto_ia += "[SEM SINAIS VCP] - Nenhuma ação apresenta os critérios extremos de Squeeze e seca de volume hoje.\n"
    else:
        bloco_texto_ia += "ALVOS DE BREAKOUT IMINENTE:\n\n"
        for item in ativos_acionados:
            bloco_texto_ia += item["comboio_str"] + "\n"
            
    with open("comboio_vcp_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco_texto_ia)
        
    enviar_email(bloco_texto_ia)

if __name__ == "__main__":
    executar_motor()
