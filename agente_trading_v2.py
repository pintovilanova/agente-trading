from datetime import datetime
from zoneinfo import ZoneInfo
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
        multiplicador_atr = 1.0

        # CÁLCULO BASE DO TRAILING APLICADO A TODOS OS ATIVOS (Correção face ao V1)
        trailing_base = preco - (atr * multiplicador_trailing_ts)
        trailing_final = round(trailing_base, 2)

        preco_caiu_hoje = preco < preco_anterior
        volume_despejo = rvol > 1.20

        # ===================================================================
        # GUILHOTINA MATEMÁTICA - OTIMIZADA PARA SUBIDAS EMINENTES
        # ===================================================================
        
        # 1. REJEIÇÃO IMEDIATA: Preço em queda com volume, ou MOMENTUM NEGATIVO ou ZERO
        if (preco_caiu_hoje and volume_despejo) or (momentum <= 0.5):
            recomendacao = "Observar"
            
        # 2. CONSOLIDAÇÃO FRACA: Tem variação positiva, mas a tendência geral é fraca (ADX < 25)
        elif var_perc > 0 and adx < 25:
            recomendacao = "Aguardar Recuo"
            preco_entrada = preco - (atr * 0.4) 
            multiplicador_atr = 1.0
            
        # 3. FORÇA CONSOLIDADA: ADX forte (> 30), Volume Elevado (> 1.20), Momentum robusto (> 1.5)
        elif var_perc > 0 and adx >= 30 and rvol >= 1.20 and (55.00 <= rsi <= 72.00) and (0.00 <= dist_mm20 <= 3.50) and momentum > 1.50:
            recomendacao = "Forca Consolidada"
            preco_entrada = preco - (atr * 0.1) 
            multiplicador_atr = 1.3 
            
        # 4. ALERTA IMINENTE: Volume começa a entrar (>= 1.00), ADX em tendência (>= 25) e Momentum positivo (> 0.50)
        elif adx >= 25 and rvol >= 1.00 and (50.00 <= rsi <= 75.00) and (-1.00 <= dist_mm20 <= 4.00) and momentum > 0.50:
            recomendacao = "Alerta Iminente"
            preco_entrada = preco - (atr * 0.2)
            multiplicador_atr = 1.2
            
        else:
            recomendacao = "Observar"

        # GESTÃO DE RISCO PARA ATIVOS ACIONADOS
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
                
            # Se for uma recomendação ativa, o trailing nunca pode ser pior que o Stop inicial
            trailing_final = round(max(trailing_base, preco_stop_calc), 2)

        # Captura a data e hora ajustada para o fuso horário de Portugal
        data_atual = datetime.now(ZoneInfo("Europe/Lisbon")).strftime('%d/%m/%Y %H:%M:%S')

        # Matriz Completa para o Google Sheets (Aba V2) - 17 Colunas
        linha_sheets = [
            ticker, nome_empresa, 
            round(preco, 2), round(rsi, 2), round(adx, 2), round(atr, 2), 
            round(rvol, 2), round(dist_mm20, 2), round(momentum, 2), 
            recomendacao, 
            round(preco_entrada, 2) if isinstance(preco_entrada, float) else preco_entrada, 
            preco_stop, preco_tp, preco_be, qtd_acoes, trailing_final,
            data_atual
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
            "trailing": trailing_final,
            "data": data_atual
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
# 6. GERAR BLOCO DE TEXTO E ENVIAR PARA O TEU AGENTE IA (COM PROMPT EMBUTIDO)
# ===================================================================
print("\nA construir o bloco unificado (Prompt + Comboio) para o email...")

# Prompt blindado - MODO GESTOR DE RISCO CÉTICO
prompt_sistema_embutido = """MODO DIÁRIO ATIVO - GESTOR DE RISCO: Avalia os seguintes ativos da minha watchlist.
O mercado recente tem registado um elevado número de falsos breakouts e quebras de momentum (ativos "sem fogo" após a entrada). A tua missão principal é PROTEGER O CAPITAL e desconfiar dos sinais do motor matemático.

Regras Operacionais Estritas:
1. Analisa os ativos marcados como 'Forca Consolidada' ou 'Alerta Iminente'. Em vez de os aceitares cegamente, atua como um Advogado do Diabo: procura falhas na força deles. 
2. SELEÇÃO CÉTICA: Escolhe os 3 melhores, mas se o RVOL estiver muito no limite (perto de 1.20) ou o Momentum for baixo, coloca um [ALERTA DE FALSO BREAKOUT] ao lado do nome e explica o motivo da tua desconfiança. Se nenhum prestar, diz abertamente que não recomendas operar.
3. TÍTULO: No cabeçalho, identifica o Ticker e o nome da empresa (ex: PFE - Pfizer Inc.).
4. ANÁLISE CRÍTICA: Em 2 ou 3 frases, justifica o que está forte (ex: ADX alto), mas foca-te OBRIGATORIAMENTE no ponto mais vulnerável da trade (ex: preço demasiado longe da MM20, exaustão possível, volume não é convincente).
5. EXTRACÇÃO EXATA: Extrai e lista os valores EXATOS fornecidos na string de dados para: Entrada, Stop, Take-Profit, Break-Even, Trailing e Qtd. (NÃO recalcules nada).
6. REFERÊNCIA: Inclui obrigatoriamente a linha do 'comboio' de dados original correspondente.
7. LEITURA DE CONTEXTO GERAL: Se notares que a maioria dos ativos na lista está com Momentum negativo, ADX baixo (<20) ou apenas a 'Observar', escreve um alerta vermelho no topo do email a avisar: "MERCADO GERAL FRACO/LATERAL: Elevado risco de falsos breakouts. Considerar não entrar ou reduzir o tamanho das posições."
"""

# Monta o corpo unificado do email
bloco_texto_ia = f"{prompt_sistema_embutido}\n\n--------------------------------------------------\n"
bloco_texto_ia += "DADOS DOS ATIVOS (COMBOIO):\n\n"

for item in comboio_ia:
    dist_mm20_str = f"{item.get('dist_mm20', 'N/A')}%" if item.get('dist_mm20') != "N/A" else "N/A"
    
    linha = (
        f"{item['ticker']},Nome: {item['nome']},Preço: {item['preco']},"
        f"Dist MM20: {dist_mm20_str},Momentum: {item.get('momentum', 'N/A')},"
        f"RSI: {item['rsi']},ADX: {item['adx']},ATR: {item.get('atr', 'N/A')},"
        f"RVOL: {item['rvol']},Estado: {item['estado']},Entrada: {item['entrada']},"
        f"Stop: {item['stop']},Take-Profit: {item['alvo']},Break-Even: {item.get('be', 'N/A')},"
        f"Qtd: {item['quantidade']},Trailing: {item['trailing']},"
        f"Data: {item['data']}"
    )
    bloco_texto_ia += linha + "\n"

# Guarda uma cópia local para o Passo 2 ler instantaneamente (sem falhas de IMAP)
with open("comboio_temp.txt", "w", encoding="utf-8") as f:
    f.write(bloco_texto_ia)
    
# Envia o email unificado para a caixa de correio
enviar_email_para_agente_ia(bloco_texto_ia, assunto="tradingRelatorioIA")
