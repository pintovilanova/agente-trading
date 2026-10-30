# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR DE EARNINGS DRIFT (PEAD)
# ===================================================================
# Descrição Geral:
# Este script opera como um "Caçador de Earnings Drift" (PEAD - Post-Earnings 
# Announcement Drift) automatizado na nuvem via GitHub Actions. O seu 
# objetivo é varrer a Watchlist em busca de empresas que tenham reportado 
# resultados recentemente (últimos 5 dias), filtrando aquelas que apresentem 
# uma explosão de preço e volume (salto inicial >= 2.0% e RVOL >= 2.0), 
# calculando o dimensionamento de risco institucional (Método Carver) e 
# enviando um relatório estruturado por email para triagem de uma IA.
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

# Importação da função modular de notificação do Telegram
from F01_notificador_telegram import enviar_alerta

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O mercado está fechado.")
    #sys.exit(0)

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
    """Descarrega o histórico com retentativas e pausas aleatórias para evitar HTTP 401/429."""
    for tentativa in range(3):
        try:
            time.sleep(random.uniform(0.8, 1.8))
            df = yf.download(ticker_str, period=period, interval="1d", progress=False, timeout=15)
            if not df.empty and len(df) >= 25:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                return df.dropna(subset=['Close', 'Volume'])
        except Exception:
            time.sleep(2.0)
    return pd.DataFrame()

def obter_earnings_dates_safe(ticker_str):
    """Obtém o calendário de earnings com tratamento de erro e isolamento de exceção."""
    try:
        time.sleep(random.uniform(0.5, 1.2))
        ticker_obj = yf.Ticker(ticker_str)
        earnings_df = ticker_obj.earnings_dates
        return ticker_obj, earnings_df
    except Exception:
        return None, None

def buscar_watchlist():
    print("A carregar a Watchlist e Configurações a partir do Google Sheets...")
    if not WEBHOOK_URL: 
        print("[ERRO] WEBHOOK_URL não configurado.")
        return [], {}
    try:
        resp = requests.get(WEBHOOK_URL, timeout=15)
        if resp.status_code == 200:
            dados = resp.json()
            if isinstance(dados, dict):
                ativos = dados.get("ativos", [])
                configs = dados.get("configs", {})
            elif isinstance(dados, list):
                ativos = dados
                configs = {}
            else:
                ativos = []
                configs = {}
                
            print(f"[SUCESSO] {len(ativos)} ativos carregados para auditoria.")
            return ativos, configs
        else:
            print(f"[ERRO] Falha ao descarregar dados: {resp.status_code}")
            return [], {}
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha de comunicação com Sheets: {e}")
        return [], {}

def enviar_email(conteudo):
    print("\nA enviar relatório de Earnings Drift para o Agente IA...")
    
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] Credenciais de email em falta. A saltar envio.")
        return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = "tradingRelatorioIA US - EARNINGS DRIFT"
    
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
                print("A aguardar 5 segundos antes de tentar novamente...")
                time.sleep(5)
            else:
                print("[ERRO CRÍTICO] O servidor Gmail fechou a ligação definitivamente. Falha no envio.")

# ===================================================================
# 3. MOTOR MATEMÁTICO: EARNINGS DRIFT (PEAD)
# ===================================================================
def analisar_earnings_drift(ativo_info, vol_alvo_diaria_usd):
    ticker = str(ativo_info.get("ticker", "")).strip().upper()
    nome_empresa = ativo_info.get("nome", "N/A")
    setor = str(ativo_info.get("setor", "Desconhecido")).strip()
    rs_score = ativo_info.get("rs_score", "N/A")

    if not ticker or ticker == "#N/A" or ticker == "NONE":
        return None

    if ticker == "BRK-A":
        print("[AJUSTE] Ticker BRK-A convertido automaticamente para BRK-B.")
        ticker = "BRK-B"

    val_rs_num = limpar_float(rs_score)
    if val_rs_num is not None and val_rs_num < 50:
        print(f"[FILTRADO] {ticker} rejeitado por RS Score fraco ({val_rs_num} < 50 - Laggard).")
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
            for idx, row in earnings_df.head(3).iterrows():
                if hasattr(idx, 'date'):
                    d_earn = idx.date()
                else:
                    d_earn = pd.to_datetime(idx).date()
                
                dias_passados = (hoje - d_earn).days
                if 0 <= dias_passados <= 5:
                    earnings_recente = True
                    data_earnings_str = d_earn.strftime('%d/%m/%Y')
                    break

        if not earnings_recente:
            return None

        ultimo_dia = df.iloc[-1]
        dia_anterior = df.iloc[-2]

        preco = ultimo_dia['Close']
        preco_anterior = dia_anterior['Close']
        var_perc = ((preco - preco_anterior) / preco_anterior) * 100
        rvol = ultimo_dia['RVOL']
        minimo_dia = ultimo_dia['Low']
        
        atr = ultimo_dia.get('ATRr_14', np.nan)

        if var_perc >= 2.0 and rvol >= 2.0:
            estado = "EARNINGS MOMENTUM - Drift Detetado"
            entrada = round(preco, 2)
            stop_loss = round(minimo_dia * 0.99, 2)
            alvo_tp = round(entrada + ((entrada - stop_loss) * 2.0), 2)
            
            risco = entrada - stop_loss
            
            if pd.notna(atr) and atr > 0:
                qtd_calc = round(vol_alvo_diaria_usd / atr, 2)
            else:
                qtd_calc = round(vol_alvo_diaria_usd / risco, 2) if risco > 0 else 0
                
            if qtd_calc <= 0:
                print(f"[FILTRADO] {ticker} rejeitado por quantidade calculada nula.")
                return None

            qtd_acoes = qtd_calc
            val_calc = entrada * qtd_acoes
            valor_investir = f"~{val_calc:.2f} USD"
        else:
            return None

        def limpa(v):
            if pd.isna(v) or v == "N/A": return "N/A"
            try:
                return round(float(v), 2)
            except:
                return "N/A"

        if val_rs_num is not None:
            if val_rs_num >= 80:
                status_rs = "🔥 ELITE (RS >= 80 - Vento a Favor)"
            elif val_rs_num >= 50:
                status_rs = "⚖️ NEUTRO (RS 50-79 - Acompanha o Mercado)"
            else:
                status_rs = "⚠️ FRACO / LAGGARD (RS < 50 - Vento Contra)"
        else:
            status_rs = "❓ SEM DADO DE RS"

        linha_comboio = (
            f"{ticker},Nome: {nome_empresa},Setor: {setor},Preço: {limpa(preco)},"
            f"RS Score: {rs_score} ({status_rs}),"
            f"DataEarnings: {data_earnings_str},VarDia: {limpa(var_perc)}%,RVOL: {limpa(rvol)},"
            f"Estado: {estado},Ordem: BUY STOP,Entrada: {limpa(entrada)},Stop: {limpa(stop_loss)},"
            f"Take-Profit: {limpa(alvo_tp)},Qtd: {qtd_acoes},ValorInvestir: {valor_investir},"
            f"Data: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
        )

        return {
            "ticker": ticker,
            "preco": limpa(preco),
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
    
    ativos, configs = buscar_watchlist()
    if not ativos:
        sys.exit(1)
        
    try:
        capital_total_conta = float(configs.get("CAPITAL_TOTAL_CONTA", 10400.00))
        alvo_volatilidade_anual = float(configs.get("ALVO_VOLATILIDADE_ANUAL", 0.05))
    except (ValueError, TypeError):
        capital_total_conta = 10400.00
        alvo_volatilidade_anual = 0.05

    volatilidade_alvo_diaria_usd = (capital_total_conta * alvo_volatilidade_anual) / 16.0

    print(f"[CONFIG] Capital Total da Conta: ${capital_total_conta:,.2f}")
    print(f"[CONFIG] Alvo Volatilidade Anual: {alvo_volatilidade_anual*100:.1f}%")
    print(f"[CONFIG] Orçamento Diário de Volatilidade: ${volatilidade_alvo_diaria_usd:.2f}\n")

    for ativo_info in ativos:
        ticker = ativo_info.get("ticker")
        if not ticker or ticker == "#N/A": continue
        
        res = analisar_earnings_drift(ativo_info, volatilidade_alvo_diaria_usd)
        
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
            resposta = requests.post(WEBHOOK_URL, data=json.dumps(payload_sheets), headers=headers)
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
        "- 🔢 DADOS EXATOS: Entrada: X | Stop: X | TP: X | Qtd: X | Valor a Investir: X\n"
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
    # 5. NOTIFICAÇÃO TELEGRAM DEBUG (CONTROLADA PELA FLAG DE CONFIGS)
    # ===================================================================
    debug_telegram_ativado = str(configs.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

    if debug_telegram_ativado:
        print("A enviar notificação de Debug para o Telegram via função modular...")
        mensagem_debug = "📊 *MOTOR DE EARNINGS DRIFT (PEAD)*\n\n🔍 [DEBUG] Execução concluída com sucesso. Relatório de Earnings gerado e enviado por e-mail."
        enviar_alerta(mensagem_debug)

if __name__ == "__main__":
    executar_motor()
