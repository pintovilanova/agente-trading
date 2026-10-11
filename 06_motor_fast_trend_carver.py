# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR FAST TREND (ROBERT CARVER)
# ===================================================================================
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
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O motor Carver vai descansar.")
    #sys.exit(0)

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
def buscar_dados_completos():
    print("A carregar a Watchlist e Posições Ativas a partir do Google Sheets...")
    if not WEBHOOK_URL: 
        print("[ERRO] WEBHOOK_URL não configurado.")
        return [], {}
    try:
        # Garante que apanha a aba correta se necessário, ou usa a raiz
        url_alvo = WEBHOOK_URL if "?" in WEBHOOK_URL else f"{WEBHOOK_URL}?aba=Analise Compra"
        resp = requests.get(url_alvo)
        
        if resp.status_code == 200:
            try:
                dados = resp.json()
            except json.JSONDecodeError:
                print(f"[ERRO] O Webhook não retornou um JSON válido. Resposta: {resp.text[:200]}")
                return [], {}

            if isinstance(dados, dict):
                ativos = dados.get("ativos", [])
                posicoes = dados.get("posicoesAtivas", {})
                return ativos, posicoes
            elif isinstance(dados, list):
                return dados, {}
                
        print(f"[AVISO] Webhook retornou status {resp.status_code}. Resposta: {resp.text[:200]}")
        return [], {}
    except Exception as e:
        print(f"[ERRO CRÍTICO] Sheets: {e}")
        return [], {}

# ===================================================================
# FUNÇÃO DE ENVIO DE EMAIL (Com Sistema Anti-Falhas)
# ===================================================================
def enviar_email_bruto(conteudo):
    print("\nA enviar o relatório de dados brutos do Carver para o Agente IA via email...")
    
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] Credenciais de email em falta. A saltar envio.")
        return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = "tradingRelatorioIA US - FAST TREND CARVER"
    
    msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
    
    # Sistema de Tolerância a Falhas (Retry) com Timeout
    max_tentativas = 3
    for tentativa in range(max_tentativas):
        try:
            # Adicionado timeout de 15 segundos para proteger contra bloqueios do Gmail
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
            server.quit()
            
            print(f"[SUCESSO] Email bruto do Carver enviado na tentativa {tentativa + 1}!")
            break  # Sai do loop por sucesso
            
        except Exception as e:
            print(f"[ERRO] Falha ao enviar o email (tentativa {tentativa + 1} de {max_tentativas}): {e}")
            if tentativa < max_tentativas - 1:
                print("A aguardar 5 segundos antes de tentar novamente...")
                time.sleep(5)
            else:
                print("[ERRO CRÍTICO] O servidor Gmail fechou a ligação definitivamente. Falha no envio.")

# ===================================================================
# 3. MOTOR MATEMÁTICO: CÁLCULO NATIVO
# ===================================================================
def calcular_indicadores_tecnicos(ticker):
    try:
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if df.empty or len(df) < 50:
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        df['EMA_8'] = df['Close'].ewm(span=8, adjust=False).mean()
        df['EMA_32'] = df['Close'].ewm(span=32, adjust=False).mean()

        high = df['High']
        low = df['Low']
        close = df['Close']
        
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['ATR_36'] = tr.rolling(window=36).mean()

        ultimo = df.iloc[-1]
        return {
            "preco": float(ultimo['Close']),
            "ema8": float(ultimo['EMA_8']),
            "ema32": float(ultimo['EMA_32']),
            "atr36": float(ultimo['ATR_36'])
        }
    except Exception as e:
        print(f"[ERRO] Falha ao descarregar dados para {ticker}: {e}")
        return None

def analisar_tendencia_carver(ativo_info):
    ticker = ativo_info.get("ticker")
    nome_empresa = ativo_info.get("nome", "N/A")
    setor = ativo_info.get("setor", "Desconhecido")
    rs_score = ativo_info.get("rs_score", "N/A")

    ind = calcular_indicadores_tecnicos(ticker)
    if not ind: return None
    
    preco, ema8, ema32, atr36 = ind['preco'], ind['ema8'], ind['ema32'], ind['atr36']
    if pd.isna(ema8) or pd.isna(ema32) or pd.isna(atr36) or atr36 == 0:
        return None

    diferenca_bruta = ema8 - ema32
    forecast_carver = (diferenca_bruta / atr36) * 5.0
    
    if forecast_carver < 10.0:
        return None

    multiplicador = min(forecast_carver / 10.0, 2.0)
    estado_str = "FAST TREND - Carver Momentum"
    entrada = round(preco, 2)
    stop_loss = round(entrada - (atr36 * 1.5), 2)
    alvo_tp = round(entrada + ((entrada - stop_loss) * 2.5), 2)
    
    qtd_bruta = (VOLATILIDADE_ALVO_DIARIA_USD / atr36) * multiplicador
    qtd_acoes = round(qtd_bruta, 2)
    val_calc = entrada * qtd_acoes
    valor_investir = f"~{val_calc:.2f} USD"

    def limpa(v): return round(float(v), 2)

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
        f"EMA8: {limpa(ema8)},EMA32: {limpa(ema32)},ATR36: {limpa(atr36)},"
        f"Forecast: {limpa(forecast_carver)},Multiplicador: x{limpa(multiplicador)},"
        f"Estado: {estado_str},Entrada: {limpa(entrada)},Stop: {limpa(stop_loss)},"
        f"Take-Profit: {limpa(alvo_tp)},Qtd: {qtd_acoes},ValorInvestir: {valor_investir},"
        f"Data: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
    )

    return {
        "ticker": ticker,
        "forecast": forecast_carver,
        "comboio_str": linha_comboio
    }

def monitorizar_posicao_ativa(ticker, nome_empresa, status_atual, dados_posicao):
    ind = calcular_indicadores_tecnicos(ticker)
    if not ind: return None
    
    preco, ema8, ema32, atr36 = ind['preco'], ind['ema8'], ind['ema32'], ind['atr36']
    trailing_stop_calculado = round(preco - (atr36 * 1.5), 2)
    
    preco_entrada = dados_posicao.get("precoEntrada", "N/A")
    quantidade = dados_posicao.get("quantidade", "N/A")
    stop_atual_registado = dados_posicao.get("stopAtual", None)
    
    # REGRA DE OURO BLINDADA: O stop nunca desce, só sobe ou mantém-se
    stop_final = trailing_stop_calculado
    instrucao_risco = f"Atualizar stop para {trailing_stop_calculado}"
    
    if stop_atual_registado is not None and str(stop_atual_registado).strip() != "":
        try:
            stop_atual_val = float(stop_atual_registado)
            if stop_atual_val >= trailing_stop_calculado:
                stop_final = stop_atual_val
                instrucao_risco = f"MANTER o Stop atual em {stop_atual_val} (o cálculo matemático de hoje ({trailing_stop_calculado}) é inferior, aplicando-se a regra de inércia do trailing stop)."
            else:
                instrucao_risco = f"SUBIR o Stop do valor anterior ({stop_atual_val}) para o novo patamar ({trailing_stop_calculado})."
        except ValueError:
            pass

    diferenca_bruta = ema8 - ema32
    forecast_atual = (diferenca_bruta / atr36) * 5.0 if atr36 > 0 else 0

    linha_monitorizacao = (
        f"📌 [POSIÇÃO ATIVA - {status_atual}] {ticker} ({nome_empresa}) | "
        f"Qtd: {quantidade} | Entrada: {preco_entrada} | Preço Atual: {preco:.2f} | "
        f"EMA8: {ema8:.2f} | EMA32: {ema32:.2f} | Forecast: {forecast_atual:.2f} | "
        f"Stop Atual: {stop_atual_registado} | Novo Stop Sugerido: {stop_final} | "
        f"🛑 AÇÃO: {instrucao_risco} (ATR: {atr36:.2f})"
    )
    return linha_monitorizacao

# ===================================================================
# 4. EXECUÇÃO PRINCIPAL
# ===================================================================
def executar_motor():
    ativos, posicoes_ativas_dict = buscar_dados_completos()
    if not ativos and not posicoes_ativas_dict:
        print("[ERRO] Nenhum dado carregado do Sheets. A terminar.")
        sys.exit(1)
        
    ativos_acionados = []
    posicoes_em_gestao = []

    # 1. Analisa novos sinais (ignora qualquer ativo que já esteja no dicionário de posições ativas)
    for ativo_info in ativos:
        ticker = ativo_info.get("ticker")
        if not ticker or ticker == "#N/A": continue

        if ticker in posicoes_ativas_dict:
            continue

        res = analisar_tendencia_carver(ativo_info)
        if res:
            ativos_acionados.append(res)
            
    # 2. Processa posições ativas APENAS se o estado for ATIVA_FAST (ignora as 'ATIVA' de outros scripts)
    for ticker, dados_pos in posicoes_ativas_dict.items():
        status_atual = dados_pos.get("status", "").strip().upper()
        
        if status_atual != "ATIVA_FAST":
            continue
            
        nome = dados_pos.get("nome", ticker)
        monitorizacao = monitorizar_posicao_ativa(ticker, nome, status_atual, dados_pos)
        if monitorizacao:
            posicoes_em_gestao.append(monitorizacao)

    ativos_acionados = sorted(ativos_acionados, key=lambda k: k['forecast'], reverse=True)

    prompt_ia = (
        "MODO ACELERADOR ESTATÍSTICO (CARVER FAST TREND)\n"
        "O teu mandato é auditar as entradas geradas e monitorizar as posições ativas do portefólio.\n"
        "Presta especial atenção ao RS Score institucional anexado aos dados de cada novo sinal para avaliar o contexto de força do mercado.\n"
        "ATENÇÃO À GESTÃO DE RISCO: Respeita estritamente a regra de inércia do trailing stop nas posições ativas "
        "(o stop nunca desce, se o stop atual registado já for superior ao novo cálculo sugerido, a instrução deve ser obrigatoriamente manter o valor atual).\n\n"
        "REGRAS ESTRITAS:\n"
        "- 🔄 GESTÃO DE ESTADOS NO SHEETS (LEMBRETE OBRIGATÓRIO): Termina o teu relatório com uma secção de 'Lembrete Operacional' contendo exatamente estas duas notas:\n"
        "  1. \"🟢 NOVAS ENTRADAS: Assim que abrires uma nova posição sugerida neste relatório, altera o seu estado no Google Sheets para 'ATIVA_FAST' para que eu inicie o cálculo diário do Trailing Stop.\"\n"
        "  2. \"🔴 SAÍDAS/STOPS: Se uma posição ativa atingir o Trailing Stop, altera o estado no Sheets para 'WIN' (se a trade fechou com lucro) ou 'LOSS' (se fechou com prejuízo) para as tuas estatísticas. Ao mudares o estado, eu deixarei de a monitorizar automaticamente.\"\n"
    )
    
    bloco_texto_ia = f"📊 RELATÓRIO DE DADOS BRUTOS - FAST TREND CARVER 🏄‍♂️\n\n{prompt_ia}\n\n--------------------------------------------------\n"

    if posicoes_em_gestao:
        bloco_texto_ia += "GESTÃO DE POSIÇÕES ATIVAS (TRAILING STOP SUGERIDO & QUANTIDADES):\n\n"
        for pos in posicoes_em_gestao:
            bloco_texto_ia += pos + "\n"
        bloco_texto_ia += "\n--------------------------------------------------\n"

    if not ativos_acionados:
        bloco_texto_ia += "[MERCADO LENTO] - Nenhum novo ativo apresenta aceleração matemática (Forecast > 10).\n"
    else:
        bloco_texto_ia += "NOVOS DADOS DE ENTRADA (COMBOIO):\n\n"
        for item in ativos_acionados:
            bloco_texto_ia += item["comboio_str"] + "\n"

    with open("comboio_carver_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco_texto_ia)

    enviar_email_bruto(bloco_texto_ia)

if __name__ == "__main__":
    executar_motor()
