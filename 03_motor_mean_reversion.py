# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR DE REVERSÃO À MÉDIA (PÂNICO)
# ===================================================================
# Descrição Geral:
# Este script opera como um "Predador de Pânico" (Mean Reversion). O seu 
# objetivo não é caçar tendências, mas sim identificar quedas massivas e 
# anomalias estatísticas em ativos da Watchlist, acionando entradas cirúrgicas 
# para ressaltos rápidos ("Dead Cat Bounce" / Estratégia Hit & Run).
#
# Pilares Técnicos e Arquitetura:
# 1. Filtros de Segurança Estrutural (Anti-Lixo):
#    - Rejeição automática de Penny Stocks (Preço < 3.00 USD).
#    - Exclusão estrita do setor imobiliário / REITs / mREITs.
# 2. Gatilhos de Pânico Extremo (O Confluente):
#    - Distância à SMA20 inferior ou igual a -8.0%.
#    - RSI de 14 períodos em sobrevenda extrema (< 30).
#    - Confirmação institucional por Volume Relativo (RVOL >= 1.5) 
#      OU padrão devela de Absorção (Sombra inferior > 1.5x o corpo).
# 3. Gestão de Risco Institucional (Método Carver - Target Volatility):
#    - Orçamento de flutuação diária calculado com base na volatilidade 
#      anual alvo (5%) sobre o capital total da conta ($10,400.00).
#    - Dimensionamento de posições baseado no ATR (Average True Range) 
#      para nivelar o risco real por ativo.
# 4. Execução e Saída (Hit & Run):
#    - Stop Loss físico cravado a 1% abaixo do mínimo do dia de pânico.
#    - Validação matemática de Rácio Risco/Recompensa (Recompensa >= Risco).
#    - Alvo de Take-Profit fixo e cravado estritamente na EMA9 (sem trailing).
# ===================================================================

import pandas as pd
import yfinance as yf
import pandas_ta as ta  # <-- Importação explícita obrigatória para registar os métodos .ta
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo
import sys
import os
import requests
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O mercado está fechado. O Agente de Reversão vai descansar.")
    sys.exit(0)

# ===================================================================
# 1. CONFIGURAÇÕES E CREDENCIAIS (GitHub Secrets)
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# ===================================================================
# CONFIGURAÇÕES DE RISCO INSTITUCIONAL (MÉTODO CARVER)
# ===================================================================
CAPITAL_TOTAL_CONTA = 10400.00  # Capital atualizado da conta
ALVO_VOLATILIDADE_ANUAL = 0.05  # Alvo de 5% ao ano de flutuação (Conservador)

# Orçamento diário de volatilidade do Carver (constante 16 para raiz de 256 dias úteis)
VOLATILIDADE_ALVO_DIARIA_USD = (CAPITAL_TOTAL_CONTA * ALVO_VOLATILIDADE_ANUAL) / 16.0 

# ===================================================================
# 2. FUNÇÕES DE REDE
# ===================================================================
def buscar_watchlist():
    print("A carregar a Watchlist a partir do Google Sheets...")
    if not WEBHOOK_URL: 
        print("[ERRO] WEBHOOK_URL não configurado.")
        return []
    try:
        resp = requests.get(WEBHOOK_URL)
        if resp.status_code == 200:
            dados = resp.json()
            ativos = dados.get("ativos", []) if isinstance(dados, dict) else dados
            print(f"[SUCESSO] {len(ativos)} ativos carregados para monitorização de pânico.")
            return ativos
        else:
            print(f"[ERRO] Falha ao descarregar dados: {resp.status_code}")
            return []
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha de comunicação com Sheets: {e}")
        return []

def enviar_email(conteudo):
    print("\nA enviar email de Reversão para o Agente IA...")
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] Credenciais de email em falta. A saltar envio.")
        return
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_USER
        msg['Subject'] = "🚨 tradingRelatorioIA US - PÂNICO E REVERSÃO ⚡"
        
        msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
        server.quit()
        print("[SUCESSO] Email enviado! O Agente IA tem novos alvos para triagem.")
    except Exception as e:
        print(f"[ERRO] Falha ao enviar email: {e}")

# ===================================================================
# 3. MOTOR MATEMÁTICO: REVERSÃO À MÉDIA (COM TARGET VOLATILITY)
# ===================================================================
def analisar_reversao_media(ticker, nome_empresa, setor):
    try:
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if df.empty:
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        # Verificar se há dados suficientes
        if len(df) < 25:
            return None

        preco = df.iloc[-1]['Close']

        # -------------------------------------------------------------
        # FILTROS DE SEGURANÇA ESTRUTURAL (ANTI-LIXO BOLSISTA)
        # -------------------------------------------------------------
        if pd.isna(preco) or preco < 3.00:
            print(f"[FILTRADO] {ticker} rejeitado por preço baixo (Preço: {preco}).")
            return None
            
        if setor and any(termo in setor.lower() for termo in ["real estate", "reit", "mortgage"]):
            print(f"[FILTRADO] {ticker} rejeitado por pertencer ao setor REIT/Imobiliário.")
            return None

        # Indicadores Base
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        
        # RSI 14 Rápido
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI_14'] = 100 - (100 / (1 + rs))
        
        # Média Móvel de 9 (Alvo de Saída)
        df['EMA_9'] = df['Close'].ewm(span=9, adjust=False).mean()
        
        # Volume Relativo (RVOL) e ATR para o Carver
        df['SMA_20_Vol'] = df['Volume'].rolling(window=20).mean()
        df['RVOL'] = df['Volume'] / df['SMA_20_Vol']
        df.ta.atr(length=14, append=True)

        # Selecionar o último dia de forma segura após o cálculo das colunas
        ultimo_dia = df.iloc[-1]

        sma20 = ultimo_dia.get('SMA_20', np.nan)
        ema9 = ultimo_dia.get('EMA_9', preco)
        rsi = ultimo_dia.get('RSI_14', np.nan)
        rvol = ultimo_dia.get('RVOL', 1.0)
        atr = ultimo_dia.get('ATRr_14', np.nan)
        
        dist_mm20 = ((preco - sma20) / sma20) * 100 if pd.notna(sma20) and sma20 > 0 else 0.0
        
        # Deteção de Absorção (Candlestick)
        abertura = ultimo_dia.get('Open', preco)
        minimo = ultimo_dia.get('Low', preco)
        
        corpo = abs(abertura - preco)
        sombra_inferior = min(abertura, preco) - minimo
        absorcao = sombra_inferior > (corpo * 1.5)

        estado = "Observar"
        entrada = "N/A"
        alvo_tp = "N/A"
        stop_loss = "N/A"
        qtd_acoes = "N/A"
        valor_investir = "N/A"
        
        # -------------------------------------------------------------
        # A MATEMÁTICA DO GATILHO DE CHOQUE
        # -------------------------------------------------------------
        if pd.notna(dist_mm20) and dist_mm20 <= -8.0 and pd.notna(rsi) and rsi < 30 and (rvol >= 1.5 or absorcao):
            estado = "PÂNICO EXTREMO - Oportunidade de Reversão"
            entrada = round(preco, 2)
            alvo_tp = round(ema9, 2)
            stop_loss = round(minimo * 0.99, 2)
            
            risco = entrada - stop_loss
            recompensa = alvo_tp - entrada
            
            if recompensa < risco:
                 estado = "Rejeitado (Rácio de Risco Negativo)"
                 entrada = alvo_tp = stop_loss = "N/A"
            else:
                 # CÁLCULO DE MESTRE CARVER ADAPTADO A REVERSÃO:
                 if pd.notna(atr) and atr > 0:
                     qtd_acoes = round(VOLATILIDADE_ALVO_DIARIA_USD / atr, 2)
                 else:
                     qtd_acoes = round(VOLATILIDADE_ALVO_DIARIA_USD / risco, 2) if risco > 0 else "N/A"

                 if qtd_acoes != "N/A":
                     val_calc = entrada * qtd_acoes
                     valor_investir = f"~{val_calc:.2f} USD"

        def limpa(v):
            if pd.isna(v) or v == "N/A": return "N/A"
            return round(float(v), 2)

        linha_comboio = (
            f"{ticker},Nome: {nome_empresa},Setor: {setor},Preço: {limpa(preco)},"
            f"Dist MM20: {limpa(dist_mm20)}%,EMA9: {limpa(ema9)},"
            f"RSI: {limpa(rsi)},RVOL: {limpa(rvol)},Absorção: {'Sim' if absorcao else 'Não'},"
            f"Estado: {estado},Entrada: {limpa(entrada)},"
            f"Stop: {limpa(stop_loss)},Take-Profit: {limpa(alvo_tp)},"
            f"Qtd: {qtd_acoes},ValorInvestir: {valor_investir},"
            f"Data: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
        )

        return {
            "ticker": ticker,
            "estado": estado,
            "comboio_str": linha_comboio
        }

    except Exception as e:
        print(f"[ERRO] Falha ao processar {ticker}: {e}")
        return None

# ===================================================================
# 4. EXECUÇÃO PRINCIPAL E GERAÇÃO DE PROMPT
# ===================================================================
def executar_motor():
    ativos = buscar_watchlist()
    if not ativos:
        sys.exit(1)
        
    ativos_acionados = []
    
    for ativo_info in ativos:
        ticker = ativo_info.get("ticker")
        if not ticker or ticker == "#N/A": continue
        
        res = analisar_reversao_media(
            ticker, 
            ativo_info.get("nome", "N/A"), 
            ativo_info.get("setor", "Desconhecido")
        )
        
        res_dict = res if isinstance(res, dict) else None
        if res_dict:
            print(f"[OK] {ticker} analisado. Estado: {res_dict['estado']}")
            if "PÂNICO EXTREMO" in res_dict['estado']:
                ativos_acionados.append(res_dict)
                
    # ==============================================================================
    # 2. PROMPT DE SISTEMA PARA A IA (Instruções Rigorosas)
    # ==============================================================================
    prompt_ia = """Atuas como o Analista Quantitativo Chefe de um fundo institucional. O teu mandato é auditar ações que sofreram quedas massivas e identificar fundos institucionais para ressaltos rápidos (Dead Cat Bounce). 
Não estás à procura de tendências; estás a apanhar a correção de uma anomalia estatística baseada no orçamento de volatilidade da conta.

REGRAS ESTRITAS (ANTI-ALUCINAÇÃO):
- NUNCA inventes, deduzas ou alteres preços, tickers ou indicadores. Usa EXATAMENTE os números fornecidos nos dados.
- O tom deve ser militar, frio e puramente matemático. Sem saudações.

REGRAS DE TRIAGEM E EXECUÇÃO:
1. VALIDAÇÃO DE FUNDO: Confirma a Capitulação. Um RVOL > 1.5 ou "Absorção: Sim" indicam que o dinheiro institucional começou a comprar o pânico.
2. VETO FUNDAMENTAL: O motor já filtra penny stocks (<$3) e mREITs, mas se souberes que a queda foi originada por fraude ou falência iminente, emite um VETO OBRIGATÓRIO.
3. TÁTICA DE SAÍDA (Hit & Run): O alvo de Take-Profit é fixo e cravado na EMA9. Não recomendes o uso de Trailing Stops. O objetivo é comprar barato e largar a ação mal ela toque na linha dos 9 dias.
4. TÁTICA DE ENTRADA: Recomenda execução próxima do fecho (para confirmar a vela de absorção) ou o uso de Buy Limit na zona de pânico.

ESTRUTURA VISUAL OBRIGATÓRIA:
🎯 [TICKER] - [Nome da Empresa] ([Setor])
- 🚨 SINAL DE PÂNICO: [Destacar a Dist MM20 e o RSI]
- 🩸 PEGADA INSTITUCIONAL: [Referir RVOL ou Absorção]
- ⚙️ TÁTICA: HIT & RUN. Retirar lucro imediato no alvo EMA9.
- 🔢 DADOS EXATOS: Entrada: X | Stop: X | TP (EMA9): X | Qtd: X | Valor a Investir: X
- 📋 REFERÊNCIA: [Linha do Comboio]

Termina o relatório com: "EXECUÇÃO MECÂNICA. NÃO PERSEGUIR O PREÇO. O RISCO DITA A SOBREVIVÊNCIA."
"""
    
    bloco_texto_ia = f"{prompt_ia}\n\n--------------------------------------------------\n"
    
    if not ativos_acionados:
        bloco_texto_ia += "[SEM SINAIS DE PÂNICO] - Nenhuma ação da Watchlist cumpre os requisitos matemáticos de sobrevenda extrema hoje.\n"
    else:
        bloco_texto_ia += "DADOS DOS ATIVOS EM PÂNICO (COMBOIO):\n\n"
        for item in ativos_acionados:
            bloco_texto_ia += item["comboio_str"] + "\n"
            
    with open("comboio_reversao_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco_texto_ia)
        
    enviar_email(bloco_texto_ia)

if __name__ == "__main__":
    executar_motor()
