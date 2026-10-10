# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR DE REVERSÃO CONNORS-CHAN (RSI 2 + BB)
# ===================================================================
# Descrição Geral:
# Este script implementa a estratégia quantitativa de alta frequência 
# popularizada por Larry Connors e estudada por Ernest Chan. O seu foco é 
# identificar exaustões de curto prazo em ativos da Watchlist através da 
# confluência de feixes estatísticos extremos (Preço abaixo da Banda de 
# Bollinger Inferior e RSI de 2 períodos em sobrevenda extrema < 10).
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
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O mercado está fechado. O Motor Connors-Chan vai descansar.")
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
CAPITAL_TOTAL_CONTA = 10400.00  
ALVO_VOLATILIDADE_ANUAL = 0.05  

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
            print(f"[SUCESSO] {len(ativos)} ativos carregados para motor Connors-Chan.")
            return ativos
        else:
            print(f"[ERRO] Falha ao descarregar dados: {resp.status_code}")
            return []
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha de comunicação com Sheets: {e}")
        return []

def enviar_email(conteudo):
    print("\nA enviar email do Motor Connors-Chan para o Agente IA...")
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] Credenciais de email em falta. A saltar envio.")
        return
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_USER
        # ÍCONES INJETADOS AQUI - Assunto Técnico
        msg['Subject'] = "🧲 tradingRelatorioIA US - CONNORS-CHAN REVERSÃO 🏹"
        
        msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
        server.quit()
        print("[SUCESSO] Email enviado! O Agente IA tem novos alvos estatísticos.")
    except Exception as e:
        print(f"[ERRO] Falha ao enviar email: {e}")

# ===================================================================
# 3. MOTOR MATEMÁTICO: CONNORS-CHAN (RSI(2) + BANDAS DE BOLLINGER)
# ===================================================================
def analisar_connors_chan(ativo_info):
    try:
        ticker = ativo_info.get("ticker")
        nome_empresa = ativo_info.get("nome", "N/A")
        setor = ativo_info.get("setor", "Desconhecido")
        rs_score = ativo_info.get("rs_score", "N/A")

        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if df.empty:
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        # BLINDAGEM CONTRA IPOs RECENTES (Histórico curto):
        if len(df) < 25:
            return None

        ultimo_dia = df.iloc[-1]
        preco = ultimo_dia['Close']

        # -------------------------------------------------------------
        # FILTROS DE SEGURANÇA ESTRUTURAL (ANTI-LIXO BOLSISTA)
        # -------------------------------------------------------------
        if pd.isna(preco) or preco < 3.00:
            print(f"[FILTRADO] {ticker} rejeitado por preço baixo (Preço: {preco}).")
            return None
            
        if setor and any(termo in setor.lower() for termo in ["real estate", "reit", "mortgage"]):
            print(f"[FILTRADO] {ticker} rejeitado por pertencer ao setor REIT/Imobiliário.")
            return None

        # Indicadores Técnicos (Pandas TA)
        df.ta.bbands(length=20, std=2.0, append=True) # Cria BBL_20_2.0, BBM_20_2.0, BBU_20_2.0
        df.ta.rsi(length=2, append=True)              # Cria RSI_2
        df.ta.atr(length=14, append=True)             # Cria ATRr_14

        # Recolher o último dia com as colunas novas
        ultimo_dia = df.iloc[-1]

        bbl_inferior = ultimo_dia.get('BBL_20_2.0', np.nan)
        bb_media = ultimo_dia.get('BBM_20_2.0', np.nan)
        rsi_2 = ultimo_dia.get('RSI_2', np.nan)
        atr = ultimo_dia.get('ATRr_14', np.nan)
        minimo = ultimo_dia.get('Low', preco)

        estado = "Observar"
        entrada = "N/A"
        alvo_tp = "N/A"
        stop_loss = "N/A"
        qtd_acoes = "N/A"
        valor_investir = "N/A"
        
        # -------------------------------------------------------------
        # A MATEMÁTICA DO GATILHO DE EXAUSTÃO CONNORS-CHAN
        # -------------------------------------------------------------
        if pd.notna(bbl_inferior) and pd.notna(rsi_2) and (preco < bbl_inferior) and (rsi_2 < 10.0):
            estado = "EXAUSTÃO ESTATÍSTICA - Connors-Chan"
            entrada = round(preco, 2)
            
            alvo_tp = round(bb_media, 2) if pd.notna(bb_media) else round(preco * 1.03, 2)
            
            stop_calc = preco - (atr * 1.5) if pd.notna(atr) else minimo * 0.98
            stop_loss = round(min(stop_calc, minimo * 0.99), 2)
            
            risco = entrada - stop_loss
            recompensa = alvo_tp - entrada
            
            if recompensa < risco:
                 estado = "Rejeitado (Rácio de Risco Negativo)"
                 entrada = alvo_tp = stop_loss = "N/A"
            else:
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

        # Análise contextual do RS Score (Coluna O)
        try:
            val_rs = float(rs_score)
            if val_rs >= 80:
                status_rs = "🔥 ELITE (RS >= 80 - Vento a Favor)"
            elif val_rs >= 50:
                status_rs = "⚖️ NEUTRO (RS 50-79 - Acompanha o Mercado)"
            else:
                status_rs = "⚠️ FRACO / LAGGARD (RS < 50 - Vento Contra)"
        except ValueError:
            status_rs = "❓ SEM DADO DE RS"

        linha_comboio = (
            f"{ticker},Nome: {nome_empresa},Setor: {setor},Preço: {limpa(preco)},"
            f"RS Score: {rs_score} ({status_rs}),"
            f"BBLower: {limpa(bbl_inferior)},RSI2: {limpa(rsi_2)},"
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
        print(f"[ERRO] Falha ao processar ativo: {e}")
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
        
        res = analisar_connors_chan(ativo_info)
        
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
1. VALIDAÇÃO DE EXAUSTÃO: Confirma que o RSI(2) está abaixo de 10 e que o preço rompeu a Banda de Bollinger inferior.
2. VETO FUNDAMENTAL: Emite veto obrigatório caso exista um rácio de risco negativo.
3. TÁTICA DE SAÍDA: O alvo de Take-Profit é cravado na Banda Central de Bollinger (SMA20).
4. TÁTICA DE ENTRADA: Execução com alocação rígida baseada em volatilidade (Carver).
5. CONTEXTO INSTITUCIONAL: Presta especial atenção ao RS Score e estado de força relativa reportados.

Estrutura Visual Obrigatória:
🎯 [TICKER] - [Nome da Empresa] ([Setor])
- 🚨 SINAL CONNORS-CHAN: [Destacar BBLower e RSI(2) extremo]
- 📊 CONTEXTO INSTITUCIONAL: RS Score e respetivo estado de Força Relativa.
- ⚙️ TÁTICA: SWING REVERSION. Alvo na SMA20 / Banda Média.
- 🔢 DADOS EXATOS: Entrada: X | Stop: X | TP (SMA20): X | Qtd: X | Valor a Investir: X
- 📋 REFERÊNCIA: [Linha do Comboio exata]
"""
    
    # ÍCONES INJETADOS AQUI - Cabeçalho do Prompt para o LLM
    bloco_texto_ia = f"🧲 RELATÓRIO DE DADOS BRUTOS - CONNORS-CHAN REVERSÃO 🏹\n\n{prompt_ia}\n\n--------------------------------------------------\n"
    
    if not ativos_acionados:
        bloco_texto_ia += "[SEM SINAIS CONNORS-CHAN] - Nenhuma ação da Watchlist cumpre os critérios de exaustão estatística hoje.\n"
    else:
        bloco_texto_ia += "DADOS DOS ATIVOS EM EXAUSTÃO (COMBOIO):\n\n"
        for item in ativos_acionados:
            bloco_texto_ia += item["comboio_str"] + "\n"
            
    with open("comboio_connors_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco_texto_ia)
        
    enviar_email(bloco_texto_ia)

if __name__ == "__main__":
    executar_motor()
