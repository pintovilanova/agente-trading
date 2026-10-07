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

RISCO_MAXIMO_DOLARES = 25.00

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
        msg['Subject'] = "tradingRelatorioIA US - PÂNICO E REVERSÃO"
        
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
# 3. MOTOR MATEMÁTICO: REVERSÃO À MÉDIA
# ===================================================================
def analisar_reversao_media(ticker, nome_empresa, setor):
    try:
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if df.empty:
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

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
        
        # Volume Relativo (RVOL)
        df['SMA_20_Vol'] = df['Volume'].rolling(window=20).mean()
        df['RVOL'] = df['Volume'] / df['SMA_20_Vol']

        ultimo_dia = df.iloc[-1]
        
        preco = ultimo_dia['Close']
        sma20 = ultimo_dia['SMA_20']
        ema9 = ultimo_dia['EMA_9']
        rsi = ultimo_dia['RSI_14']
        rvol = ultimo_dia['RVOL']
        
        dist_mm20 = ((preco - sma20) / sma20) * 100
        
        # Deteção de Absorção (Candlestick)
        abertura = ultimo_dia['Open']
        maximo = ultimo_dia['High']
        minimo = ultimo_dia['Low']
        
        corpo = abs(abertura - preco)
        sombra_inferior = min(abertura, preco) - minimo
        
        # Absorção: Sombra inferior pelo menos 1.5x maior que o corpo da vela
        absorcao = sombra_inferior > (corpo * 1.5)

        estado = "Observar"
        entrada = "N/A"
        alvo_tp = "N/A"
        stop_loss = "N/A"
        qtd_acoes = "N/A"
        valor_investir = "N/A"
        
        # -------------------------------------------------------------
        # A MATEMÁTICA DO GATILHO DE CHOQUE
        # 1. Distância à MM20 <= -8.0%
        # 2. RSI < 30 (Sobrevenda)
        # 3. RVOL >= 1.5 (Capitulação) OU Absorção visível na vela
        # -------------------------------------------------------------
        if pd.notna(dist_mm20) and dist_mm20 <= -8.0 and rsi < 30 and (rvol >= 1.5 or absorcao):
            estado = "PÂNICO EXTREMO - Oportunidade de Reversão"
            entrada = round(preco, 2)
            alvo_tp = round(ema9, 2)
            # Stop Loss cravado a 1% abaixo do mínimo absoluto do dia de pânico
            stop_loss = round(minimo * 0.99, 2)
            
            # Filtro de Sanidade: Risco vs Recompensa
            risco = entrada - stop_loss
            recompensa = alvo_tp - entrada
            
            if recompensa < risco:
                 estado = "Rejeitado (Rácio de Risco Negativo)"
                 entrada = alvo_tp = stop_loss = "N/A"
            else:
                 qtd_acoes = round(RISCO_MAXIMO_DOLARES / risco, 2) if risco > 0 else "N/A"
                 if qtd_acoes != "N/A":
                     val_calc = entrada * qtd_acoes
                     valor_investir = f"~{val_calc:.2f} USD"

        def limpa(v):
            if pd.isna(v) or v == "N/A": return "N/A"
            return round(float(v), 2)

        # Estrutura do Comboio adaptada para Reversão
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
        
        if res:
            print(f"[OK] {ticker} analisado. Estado: {res['estado']}")
            if "PÂNICO EXTREMO" in res['estado']:
                ativos_acionados.append(res)
                
    # O Prompt especializado em Hit & Run
    prompt_ia = """MODO PREDADOR DE REVERSÃO (MEAN REVERSION)
O teu mandato é auditar ações que sofreram quedas massivas e identificar fundos institucionais para ressaltos rápidos (Dead Cat Bounce). 
Não estás à procura de tendências; estás a apanhar a correção de uma anomalia estatística.

Regras de Triagem e Execução:
1. VALIDAÇÃO DE FUNDO: Confirma a Capitulação. Um RVOL > 1.5 ou "Absorção: Sim" indicam que o dinheiro institucional começou a comprar o pânico.
2. VETO FUNDAMENTAL: Se souberes que a queda foi originada por um risco de falência, fraude fiscal ou diluição grave de ações, emite um VETO OBRIGATÓRIO.
3. TÁTICA DE SAÍDA (Hit & Run): O alvo de Take-Profit é fixo e cravado na EMA9. Não recomendes o uso de Trailing Stops. O objetivo é comprar barato e largar a ação mal ela toque na linha dos 9 dias.
4. TÁTICA DE ENTRADA: Recomenda execução próxima do fecho (para confirmar a vela de absorção) ou o uso de Buy Limit na zona de pânico.

Estrutura Visual Obrigatória:
🎯 [TICKER] - [Nome da Empresa] ([Setor])
- 🚨 SINAL DE PÂNICO: [Destacar a Dist MM20 e o RSI]
- 🩸 PEGADA INSTITUCIONAL: [Referir RVOL ou Absorção]
- ⚙️ TÁTICA: HIT & RUN. Retirar lucro imediato no alvo EMA9.
- 🔢 DADOS EXATOS: Entrada: X | Stop: X | TP (EMA9): X | Qtd: X | Valor a Investir: X
- 📋 REFERÊNCIA: [Linha do Comboio]
"""
    
    bloco_texto_ia = f"{prompt_ia}\n\n--------------------------------------------------\n"
    
    if not ativos_acionados:
        bloco_texto_ia += "[SEM SINAIS DE PÂNICO] - Nenhuma ação da Watchlist cumpre os requisitos matemáticos de sobrevenda extrema hoje.\n"
    else:
        bloco_texto_ia += "DADOS DOS ATIVOS EM PÂNICO (COMBOIO):\n\n"
        for item in ativos_acionados:
            bloco_texto_ia += item["comboio_str"] + "\n"
            
    # Guarda o ficheiro localmente como cópia de segurança
    with open("comboio_reversao_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco_texto_ia)
        
    enviar_email(bloco_texto_ia)

if __name__ == "__main__":
    executar_motor()
