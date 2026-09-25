import yfinance as yf
import pandas_ta as ta
import pandas as pd
import requests
import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ===================================================================
# 0. CONFIGURAÇÕES E CREDENCIAIS (Lidas do GitHub Secrets)
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# ===================================================================
# 1. FUNÇÃO DE ENVIO DE EMAIL (Para alimentar o teu Agente IA)
# ===================================================================
def enviar_email_para_agente_ia(relatorio_texto, assunto="tradingRelatorioIA"):
    print(f"\nA enviar email para o Agente IA (Assunto: '{assunto}')...")
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_USER
        msg['Subject'] = assunto
        
        msg.attach(MIMEText(relatorio_texto, 'plain', 'utf-8'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
        server.quit()
        print(f"[SUCESSO] Email enviado! O teu Agente IA já pode ler a caixa de entrada.")
    except Exception as e:
        print(f"[ERRO] Falha ao enviar o email para o Agente IA: {e}")

# ===================================================================
# 2. BUSCAR A WATCHLIST DINAMICAMENTE (Google Sheets)
# ===================================================================
print("A carregar a Watchlist a partir do Google Sheets...")
try:
    resposta_tickers = requests.get(WEBHOOK_URL)
    if resposta_tickers.status_code == 200:
        ativos_data = resposta_tickers.json()
        if isinstance(ativos_data, list) and len(ativos_data) > 0:
            print(f"[SUCESSO] {len(ativos_data)} ativos carregados (com nomes).")
        else:
            print("[ERRO] A lista de ativos veio vazia.")
            sys.exit(1)
    else:
        print(f"[ERRO] Falha ao descarregar watchlist: {resposta_tickers.status_code}")
        sys.exit(1)
except Exception as e:
    print(f"[ERRO CRÍTICO] Falha de comunicação com Sheets: {e}")
    sys.exit(1)

# ===================================================================
# 3. VETO MACRO (SPY FLASH CRASH & BEAR MARKET)
# ===================================================================
print("\nA verificar Veto Macro (SPY)...")
try:
    df_spy = yf.download("SPY", period="2y", interval="1d", progress=False)
    if isinstance(df_spy.columns, pd.MultiIndex):
        df_spy.columns = df_spy.columns.droplevel(1)
        
    df_spy.ta.sma(length=200, append=True)
    spy_hoje = df_spy.iloc[-1]
    spy_ontem = df_spy.iloc[-2]
    
    preco_spy = spy_hoje['Close']
    preco_spy_ontem = spy_ontem['Close']
    sma200_spy = spy_hoje['SMA_200']
    
    queda_spy = ((preco_spy - preco_spy_ontem) / preco_spy_ontem) * 100
    
    if queda_spy <= -1.50:
        print(f"[BLOQUEIO] SPY em Pânico: Caiu {queda_spy:.2f}%. Execução abortada.")
        sys.exit(0)
        
    if preco_spy < sma200_spy:
        print(f"[BLOQUEIO] SPY em Baixa: Preço ({preco_spy:.2f}) abaixo da SMA200 ({sma200_spy:.2f}). Execução abortada.")
        sys.exit(0)
        
    print("[OK] SPY Saudável. A iniciar extração...\n")
except Exception as e:
    print(f"Erro na validação do SPY: {e}")

# Configurações de Risco
risco_maximo_dolares = 25.00
multiplicador_trailing_ts = 1.5
racio_tp_base = 1.2

resultados_para_sheets = []
comboio_ia = []

# ===================================================================
# 4. MOTOR MATEMÁTICO V2 (Para todos os Ativos)
# ===================================================================
for ativo_info in ativos_data:
    ticker = ativo_info.get("ticker")
    nome_empresa = ativo_info.get("nome", "N/A")
    
    try:
        df = yf.download(ticker, period="2y", interval="1d", progress=False)
        if df.empty:
            print(f"[AVISO] Sem dados para {ticker}.")
            continue
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        df.ta.rsi(length=14, append=True)
        df.ta.adx(length=14, append=True)
        df.ta.atr(length=14, append=True)
        df.ta.sma(length=200, append=True)
        df.ta.sma(length=20, append=True)
        df.ta.mom(length=14, append=True)

        media_volume_20 = df['Volume'].rolling(window=20).mean()
        df['RVOL'] = df['Volume'] / media_volume_20

        ultimo_dia = df.iloc[-1]
        dia_anterior = df.iloc[-2]

        preco = ultimo_dia['Close']
        preco_anterior = dia_anterior['Close']
        var_perc = ((preco - preco_anterior) / preco_anterior) * 100
        
        sma20 = ultimo_dia['SMA_20']
        dist_mm20 = ((preco - sma20) / sma20) * 100

        rvol = ultimo_dia['RVOL']
        adx = ultimo_dia['ADX_14']
        rsi = ultimo_dia['RSI_14']
        atr = ultimo_dia['ATRr_14']
        momentum = ultimo_dia['MOM_14']

        recomendacao = "Observar"
        preco_entrada = "N/A"
        preco_stop = "N/A"
        preco_tp = "N/A"
        preco_be = "N/A"
        qtd_acoes = "N/A"
        trailing_final = "N/A"
        multiplicador_atr = 1.0

        preco_caiu_hoje = preco < preco_anterior
        volume_despejo = rvol > 1.20

        if (preco_caiu_hoje and volume_despejo) or (momentum < -3.00):
            recomendacao = "Observar"
        elif var_perc > 0 and adx < 20:
            recomendacao = "Aguardar Recuo"
            preco_entrada = preco - (atr * 0.4)
            multiplicador_atr = 1.0
        elif var_perc > 0 and adx >= 25 and rvol >= 1.00 and (50.00 <= rsi <= 70.00) and (-1.00 <= dist_mm20 <= 2.50):
            recomendacao = "Forca Consolidada"
            preco_entrada = preco - (atr * 0.2)
            multiplicador_atr = 1.2
        elif adx >= 20 and rvol >= 0.85 and (48.00 <= rsi <= 75.00) and (-2.00 <= dist_mm20 <= 3.50):
            recomendacao = "Alerta Iminente"
            preco_entrada = preco - (atr * 0.2)
            multiplicador_atr = 1.2

        if recomendacao != "Observar" and preco_entrada != "N/A":
            preco_stop_calc = preco_entrada - (atr * multiplicador_atr)
            preco_stop = round(preco_stop_calc, 2)
            risco_por_acao = preco_entrada - preco_stop_calc
            
            if risco_por_acao > 0:
                risco_alocado = risco_maximo_dolares
                if rvol >= 3.00: risco_alocado += (risco_maximo_dolares * 0.5)
                if adx >= 35.00: risco_alocado += (risco_maximo_dolares * 0.5)
                tp_calc = preco_entrada + (risco_por_acao * racio_tp_base)
                preco_tp = round(tp_calc, 2)
                qtd_acoes = round(risco_alocado / risco_por_acao, 2)
                dist_tp = preco_tp - preco_entrada
                preco_be = round(preco_entrada + (dist_tp / 2), 2)
                
            trailing_calculado = preco - (atr * multiplicador_trailing_ts)
            trailing_final = round(max(trailing_calculado, preco_stop_calc), 2)

        # Matriz Completa para o Google Sheets (Aba V2)
        linha_sheets = [
            ticker, nome_empresa, 
            round(preco, 2), round(rsi, 2), round(adx, 2), round(atr, 2), 
            round(rvol, 2), round(dist_mm20, 2), round(momentum, 2), 
            recomendacao, 
            round(preco_entrada, 2) if isinstance(preco_entrada, float) else preco_entrada, 
            preco_stop, preco_tp, preco_be, qtd_acoes, trailing_final
        ]
        resultados_para_sheets.append(linha_sheets)

        # Guardar para o Comboio da IA
        comboio_ia.append({
            "ticker": ticker,
            "nome": nome_empresa,
            "estado": recomendacao,
            "preco": round(preco, 2),
            "rsi": round(rsi, 2),
            "adx": round(adx, 2),
            "rvol": round(rvol, 2),
            "atr": round(atr, 2),
            "momentum": round(momentum, 2),
            "dist_mm20": round(dist_mm20, 2),
            "entrada": round(preco_entrada, 2) if isinstance(preco_entrada, float) else preco_entrada,
            "stop": preco_stop,
            "alvo": preco_tp,
            "be": preco_be,
            "quantidade": qtd_acoes,
            "trailing": trailing_final
        })
        
        print(f"[OK] {ticker} analisado. Estado: {recomendacao}")

    except Exception as e:
        print(f"[ERRO] Falha ao processar {ticker}: {e}")

# ===================================================================
# 5. ENVIO PARA O GOOGLE SHEETS
# ===================================================================
if resultados_para_sheets and WEBHOOK_URL:
    print("\nA enviar matriz completa para o Google Sheets (Análise Compra V2)...")
    try:
        resposta = requests.post(WEBHOOK_URL, json=resultados_para_sheets)
        if resposta.status_code == 200:
            print("[SUCESSO] Radar atualizado na folha!")
        else:
            print(f"[ERRO] Status HTTP: {resposta.status_code}")
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha HTTP: {e}")

# ===================================================================
# 6. GERAR BLOCO DE TEXTO E ENVIAR PARA O TEU AGENTE IA
# ===================================================================
print("\nA construir o bloco de dados para a IA...")

prompt_sistema = """Modo Diário Ativo: Avalia os seguintes ativos da minha watchlist 'Força Consolidada'. Destaca os 3 melhores (com base no ADX > 25, RVOL > 1 e RSI > 50) e alerta para os que devo evitar (Momentum muito negativo ou RSI fraco). Na tua recomendação tática para os 3 melhores, é estritamente proibido arredondar ou usar linguagem aproximada. Extrai e lista os valores EXATOS fornecidos na string de dados para: Entrada, Stop, Take-Profit, Break-Even, Trailing e Qtd. Inclui obrigatoriamente em cada um dos 3 melhores ativos apresentados a linha do 'comboio' de dados original correspondente para servir de referência técnica. Mantém a análise focada na minha estratégia de Math.max e trailing stop."""

bloco_texto_ia = f"{prompt_sistema}\n\n--------------------------------------------------\n"
bloco_texto_ia += "DADOS DOS ATIVOS (COMBOIO):\n\n"

for item in comboio_ia:
    dist_mm20_str = f"{item.get('dist_mm20', 'N/A')}%" if item.get('dist_mm20') != "N/A" else "N/A"
    
    linha = (
        f"{item['ticker']},Nome: {item['nome']},Preço: {item['preco']},"
        f"Dist MM20: {dist_mm20_str},Momentum: {item.get('momentum', 'N/A')},"
        f"RSI: {item['rsi']},ADX: {item['adx']},ATR: {item.get('atr', 'N/A')},"
        f"RVOL: {item['rvol']},Estado: {item['estado']},Entrada: {item['entrada']},"
        f"Stop: {item['stop']},Take-Profit: {item['alvo']},Break-Even: {item.get('be', 'N/A')},"
        f"Qtd: {item['quantidade']},Trailing: {item.get('trailing', 'N/A')},"
        f"Data: {pd.Timestamp.now().strftime('%d/%m/%Y %H:%M:%S')}"
    )
    bloco_texto_ia += linha + "\n"

# Envia o email que o teu outro script de IA vai apanhar!
enviar_email_para_agente_ia(bloco_texto_ia, assunto="tradingRelatorioIA")
