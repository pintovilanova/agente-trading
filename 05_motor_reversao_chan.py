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
import time
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
    print("[INFO] Fim de semana detetado. O mercado está fechado. O Motor Connors-Chan vai descansar.")
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
# 2. FUNÇÕES DE REDE
# ===================================================================
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
                
            print(f"[SUCESSO] {len(ativos)} ativos carregados para motor Connors-Chan.")
            return ativos, configs
        else:
            print(f"[ERRO] Falha ao descarregar dados: {resp.status_code}")
            return [], {}
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha de comunicação com Sheets: {e}")
        return [], {}

def enviar_email(conteudo):
    print("\nA enviar email do Motor Connors-Chan para o Agente IA...")
    
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] Credenciais de email em falta. A saltar envio.")
        return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = "🧲 tradingRelatorioIA US - CONNORS-CHAN REVERSÃO 🏹"
    
    msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
    
    max_tentativas = 3
    for tentativa in range(max_tentativas):
        try:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
            server.quit()
            
            print(f"[SUCESSO] Email enviado na tentativa {tentativa + 1}! O Agente IA tem novos alvos estatísticos.")
            break
            
        except Exception as e:
            print(f"[ERRO] Falha ao enviar email (tentativa {tentativa + 1} de {max_tentativas}): {e}")
            if tentativa < max_tentativas - 1:
                print("A aguardar 5 segundos antes de tentar novamente...")
                time.sleep(5)
            else:
                print("[ERRO CRÍTICO] O servidor Gmail fechou a ligação definitivamente. Falha no envio.")

# ===================================================================
# 3. MOTOR MATEMÁTICO: CONNORS-CHAN (RSI(2) + BANDAS DE BOLLINGER)
# ===================================================================
def analisar_connors_chan(ativo_info, vol_alvo_diaria_usd):
    try:
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

        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if df.empty:
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])
        if len(df) < 25:
            return None

        ultimo_dia = df.iloc[-1]
        preco = ultimo_dia['Close']

        if pd.isna(preco) or preco < 3.00:
            print(f"[FILTRADO] {ticker} rejeitado por preço baixo (Preço: {preco}).")
            return None

        alerta_earnings = "OK"
        try:
            ticker_obj = yf.Ticker(ticker)
            
            if setor in ["Desconhecido", "N/A", "", "NONE"]:
                setor_yf = ticker_obj.info.get('sector')
                if setor_yf:
                    setor = setor_yf

            calendario = ticker_obj.calendar
            if isinstance(calendario, dict) and 'Earnings Date' in calendario:
                proxima_data = calendario['Earnings Date'][0]
                if hasattr(proxima_data, 'date'):
                    proxima_data = proxima_data.date()
                
                hoje = datetime.now(ZoneInfo("Europe/Lisbon")).date()
                dias_restantes = (proxima_data - hoje).days
                
                if 0 <= dias_restantes <= 3:
                    alerta_earnings = f"PERIGO (em {dias_restantes} dias)"
        except Exception:
            pass

        if setor and any(termo in str(setor).lower() for termo in ["real estate", "reit", "mortgage"]):
            print(f"[FILTRADO] {ticker} rejeitado por pertencer ao setor REIT/Imobiliário.")
            return None

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

        df = df.dropna(subset=[nome_bbl, nome_bbm, nome_rsi, nome_atr])
        if df.empty:
            return None

        ultimo_dia = df.iloc[-1]

        bbl_inferior = ultimo_dia.get(nome_bbl, np.nan)
        bb_media = ultimo_dia.get(nome_bbm, np.nan)
        rsi_2 = ultimo_dia.get(nome_rsi, np.nan)
        atr = ultimo_dia.get(nome_atr, np.nan)
        minimo = ultimo_dia.get('Low', preco)

        estado = "Observar"
        entrada = "N/A"
        alvo_tp = "N/A"
        stop_loss = "N/A"
        qtd_acoes = "N/A"
        valor_investir = "N/A"
        
        if pd.notna(bbl_inferior) and pd.notna(rsi_2) and (preco < bbl_inferior) and (rsi_2 < 10.0):
            estado = "EXAUSTÃO ESTATÍSTICA - Connors-Chan"
            entrada = round(preco, 2)
            
            alvo_tp = round(bb_media, 2) if pd.notna(bb_media) else round(preco * 1.03, 2)
            
            stop_calc = preco - (atr * 1.5) if pd.notna(atr) else minimo * 0.98
            stop_loss = round(min(stop_calc, minimo * 0.99), 2)
            
            risco = entrada - stop_loss
            recompensa = alvo_tp - entrada
            
            if recompensa < risco or risco <= 0:
                estado = "Rejeitado (Rácio de Risco Negativo)"
                entrada = alvo_tp = stop_loss = "N/A"
            else:
                if pd.notna(atr) and atr > 0:
                    qtd_calc = round(vol_alvo_diaria_usd / atr, 2)
                else:
                    qtd_calc = round(vol_alvo_diaria_usd / risco, 2) if risco > 0 else 0

                if qtd_calc <= 0:
                    estado = "Rejeitado (Quantidade Nula)"
                    entrada = alvo_tp = stop_loss = "N/A"
                else:
                    qtd_acoes = qtd_calc
                    val_calc = entrada * qtd_acoes
                    valor_investir = f"~{val_calc:.2f} USD"

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
            f"BBLower: {limpa(bbl_inferior)},RSI2: {limpa(rsi_2)},"
            f"Estado: {estado},Ordem: BUY LIMIT,Entrada: {limpa(entrada)},"
            f"Stop: {limpa(stop_loss)},Take-Profit: {limpa(alvo_tp)},"
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
    ativos, configs = buscar_watchlist()
    if not ativos:
        print("[AVISO] Nenhum ativo carregado. A terminar a execução sem erro.")
        sys.exit(0)
        
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

    ativos_acionados = []
    total_analisados = 0
    
    for ativo_info in ativos:
        ticker = ativo_info.get("ticker")
        if not ticker or ticker == "#N/A": continue
        
        total_analisados += 1
        res = analisar_connors_chan(ativo_info, volatilidade_alvo_diaria_usd)
        
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
 2. CONTEXTO INSTITUCIONAL (RS SCORE): Avalia o RS Score reportado. Se o ativo tiver RS Score de Elite (>= 80), o ressalto beneficia de suporte forte; se for laggard (< 50), exige cautela ou veto.
3. VETO FUNDAMENTAL: Emite veto obrigatório caso exista um rácio de risco negativo ou se o ativo apresentar EARNINGS = PERIGO.
4. TÁTICA DE SAÍDA: O alvo de Take-Profit é cravado na Banda Central de Bollinger (SMA20).
5. TÁTICA DE ENTRADA: Execução com alocação rígida baseada em volatilidade (Carver).

Estrutura Visual Obrigatória:
🎯 [TICKER] - [Nome da Empresa] ([Setor])
- 🚨 SINAL CONNORS-CHAN: [Destacar BBLower e RSI(2) extremo]
- 📊 CONTEXTO INSTITUCIONAL (RS SCORE): [Incluir o RS Score e o respetivo estado institucional reportado]
- ⚙️ TÁTICA: SWING REVERSION. Alvo na SMA20 / Banda Média.
- 🔢 DADOS EXATOS: Entrada: X | Stop: X | TP (SMA20): X | Qtd: X | Valor a Investir: X
- 📋 REFERÊNCIA: [Linha do Comboio exata]
"""
    
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

    # ===================================================================
    # 5. NOTIFICAÇÃO TELEGRAM DEBUG (CONTROLADA PELA FLAG DE CONFIGS)
    # ===================================================================
    debug_telegram_ativado = str(configs.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

    if debug_telegram_ativado:
        print("A enviar notificação de Debug para o Telegram via função modular...")
        total_acionados = len(ativos_acionados)
        mensagem_debug = (
            f"05 🧲 *MOTOR CONNORS-CHAN (REVERSÃO)*\n\n"
            f"🔍 [DEBUG] Execução concluída com sucesso.\n"
            f"📊 Ativos analisados: *{total_analisados}* | Acionados: *{total_acionados}*\n"
            f"✉️ Relatório Connors-Chan gerado e enviado por e-mail."
        )
        enviar_alerta(mensagem_debug)

if __name__ == "__main__":
    executar_motor()
