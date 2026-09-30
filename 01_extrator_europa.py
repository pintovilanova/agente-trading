from datetime import datetime
from zoneinfo import ZoneInfo
import yfinance as yf
import pandas_ta as ta
import pandas as pd
import requests
import os
import sys
import smtplib
import numpy as np
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ===================================================================
# 0.1 TRAVA DE FIM DE SEMANA (Não corre ao Sábado e Domingo)
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O mercado está fechado. O Agente vai descansar.")
    sys.exit(0)

hoje_e_sexta = "SIM" if dia_da_semana == 4 else "NÃO"

# ===================================================================
# 0. CONFIGURAÇÕES E CREDENCIAIS (Lidas do GitHub Secrets)
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")
NOME_ABA_EUROPA = "Analise Compra EU"

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# ===================================================================
# 1. FUNÇÃO DE ENVIO DE EMAIL
# ===================================================================
def enviar_email_para_agente_ia(relatorio_texto, assunto="tradingRelatorioIA Europa"):
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
print(f"A carregar a Watchlist da Europa a partir do Google Sheets (Aba: {NOME_ABA_EUROPA})...")
try:
    url_get = f"{WEBHOOK_URL}?aba={NOME_ABA_EUROPA}"
    resposta_tickers = requests.get(url_get)
    if resposta_tickers.status_code == 200:
        ativos_data = resposta_tickers.json()
        if isinstance(ativos_data, list) and len(ativos_data) > 0:
            print(f"[SUCESSO] {len(ativos_data)} ativos europeus carregados.")
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
    
    if not ticker or ticker == "#N/A":
        continue
    
    try:
        df = yf.download(ticker, period="2y", interval="1d", progress=False)
        if df.empty:
            print(f"[AVISO] Sem dados para {ticker}.")
            continue
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        alerta_earnings = "OK"
        setor = "Europa"
        try:
            ticker_obj = yf.Ticker(ticker)
            setor = ticker_obj.info.get('sector', 'Europa')
            
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

        atr_perc = round((atr / preco) * 100, 2) if pd.notna(atr) and pd.notna(preco) and preco > 0 else "N/A"

        recomendacao = "Observar"
        preco_entrada = "N/A"
        preco_stop = "N/A"
        preco_tp = "N/A"
        preco_be = "N/A"
        qtd_acoes = "N/A"
        multiplicador_atr = 1.0

        trailing_base = preco - (atr * multiplicador_trailing_ts) if pd.notna(preco) and pd.notna(atr) else "N/A"
        trailing_final = round(trailing_base, 2) if trailing_base != "N/A" else "N/A"

        preco_caiu_hoje = preco < preco_anterior if pd.notna(preco) and pd.notna(preco_anterior) else False
        volume_despejo = rvol > 1.20 if pd.notna(rvol) else False

        # ===================================================================
        # GUILHOTINA MATEMÁTICA - OTIMIZADA PARA SUBIDAS EMINENTES
        # ===================================================================
        if pd.isna(momentum) or pd.isna(adx) or pd.isna(rvol) or pd.isna(rsi) or pd.isna(dist_mm20) or pd.isna(atr):
             recomendacao = "Observar"
        elif (preco_caiu_hoje and volume_despejo) or (momentum <= 0.5):
            recomendacao = "Observar"
            
        elif var_perc > 0 and adx < 25:
            recomendacao = "Aguardar Recuo"
            preco_entrada = round(preco - (atr * 0.4), 2)  
            multiplicador_atr = 1.0
            
        elif var_perc > 0 and adx >= 30 and rvol >= 1.20 and (55.00 <= rsi <= 72.00) and (0.00 <= dist_mm20 <= 3.50) and momentum > 1.50:
            recomendacao = "Forca Consolidada"
            preco_entrada = round(preco - (atr * 0.1), 2)  
            multiplicador_atr = 1.3 
            
        elif adx >= 25 and rvol >= 1.00 and (50.00 <= rsi <= 75.00) and (-1.00 <= dist_mm20 <= 4.00) and momentum > 0.50:
            recomendacao = "Alerta Iminente"
            preco_entrada = round(preco - (atr * 0.2), 2)  
            multiplicador_atr = 1.2
            
        else:
            recomendacao = "Observar"

        # GESTÃO DE RISCO PARA ATIVOS ACIONADOS
        if recomendacao != "Observar" and preco_entrada != "N/A":
            preco_stop_calc = preco_entrada - (atr * multiplicador_atr)
            
            # ESCUDO DINÂMICO DA EMA 20
            if preco_stop_calc > sma20 and preco > sma20:
                preco_stop_calc = sma20 * 0.995
            
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
                
                trailing_final = round(max(trailing_base, preco_stop_calc), 2)

        data_atual = datetime.now(ZoneInfo("Europe/Lisbon")).strftime('%d/%m/%Y %H:%M:%S')
        preco_entrada_str = f"{preco_entrada:.2f}" if isinstance(preco_entrada, (int, float)) else preco_entrada

        # ==========================================================
        # CORREÇÃO CRÍTICA: Função limpa() Inderrotável
        # ==========================================================
        def limpa(v):
            try:
                if v == "N/A" or pd.isna(v):
                    return "N/A"
                val = float(v)
                if np.isnan(val):
                    return "N/A"
                return round(val, 2)
            except:
                return "N/A"

        p_preco = limpa(preco)
        p_dist = limpa(dist_mm20)
        p_mom = limpa(momentum)
        p_rsi = limpa(rsi)
        p_adx = limpa(adx)
        p_atr = limpa(atr)
        p_rvol = limpa(rvol)
        p_atr_perc = limpa(atr_perc)

        # DADOS PARA O GOOGLE SHEETS
        linha_comboio_completa = (
            f"{ticker},Nome: {nome_empresa},Setor: {setor},Preço: {p_preco},"
            f"Dist MM20: {p_dist}%,Momentum: {p_mom},"
            f"RSI: {p_rsi},ADX: {p_adx},ATR: {p_atr} (Vol: {p_atr_perc}%),"
            f"RVOL: {p_rvol},Estado: {recomendacao},Entrada: {preco_entrada_str},"
            f"Stop: {preco_stop},Take-Profit: {preco_tp},Break-Even: {preco_be},"
            f"Qtd: {qtd_acoes},Trailing: {trailing_final},Earnings: {alerta_earnings},Data: {data_atual}"
        )

        resultados_para_sheets.append({
            "ticker": ticker,
            "preco": p_preco,
            "momentum": p_mom,
            "rsi": p_rsi,
            "adx": p_adx,
            "atr": p_atr,
            "time": data_atual,
            "comboio": linha_comboio_completa
        })

        # GUARDAR PARA O COMBOIO DA IA
        comboio_ia.append({
            "ticker": ticker,
            "nome": nome_empresa,
            "setor": setor,
            "estado": recomendacao,
            "preco": p_preco,
            "rsi": p_rsi,
            "adx": p_adx,
            "rvol": p_rvol,
            "atr": p_atr,
            "atr_perc": p_atr_perc,
            "momentum": p_mom,
            "dist_mm20": p_dist,
            "entrada": round(preco_entrada, 2) if isinstance(preco_entrada, float) else preco_entrada,
            "stop": preco_stop,
            "alvo": preco_tp,
            "be": preco_be,
            "quantidade": qtd_acoes,
            "trailing": trailing_final,
            "earnings": alerta_earnings,
            "data": data_atual
        })
        
        print(f"[OK] {ticker} analisado. Estado: {recomendacao}")

    except Exception as e:
        print(f"[ERRO] Falha ao processar {ticker}: {e}")

# ===================================================================
# 5. ENVIO PARA O GOOGLE SHEETS
# ===================================================================
if resultados_para_sheets and WEBHOOK_URL:
    print(f"\nA enviar atualizações para o Google Sheets (Aba: {NOME_ABA_EUROPA})...")
    try:
        payload_sheets = {
            "acao": "atualizar_colunas_todas",
            "aba": NOME_ABA_EUROPA,
            "dados": resultados_para_sheets
        }
        resposta = requests.post(WEBHOOK_URL, json=payload_sheets)
        if resposta.status_code == 200:
            print("[SUCESSO] Google Sheets atualizado com sucesso!")
        else:
            print(f"[ERRO] Status HTTP: {resposta.status_code} - {resposta.text}")
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha HTTP Sheets: {e}")

# ===================================================================
# 6. GERAR BLOCO DE TEXTO E ENVIAR PARA O AGENTE IA
# ===================================================================
print("\nA construir o bloco unificado (Prompt + Comboio) para o email...")

# FILTRO: Seleciona apenas ativos que NÃO estão em "Observar"
ativos_acionados = [item for item in comboio_ia if item["estado"] != "Observar"]

prompt_sistema_embutido = f"""MODO DIÁRIO ATIVO - PREDADOR DE BREAKOUTS (EUROPA): Avalia os seguintes ativos da minha watchlist europeia.
(INFO SISTEMA - Hoje é Sexta-feira? {hoje_e_sexta})
Contexto: O mercado europeu é volátil e reage fortemente à abertura americana. A tua missão é PROTEGER O CAPITAL, desconfiar do motor matemático e expor ativamente o risco de cada trade, priorizando apenas os arranques com força institucional real.

Regras Operacionais Estritas de Triagem e Ataque:

1. FILTRO CÉTICO INICIAL: Analisa apenas ativos com 'Forca Consolidada' ou 'Alerta Iminente'. Se o panorama geral for fraco (maioria com ADX < 25 e RVOL baixo), REJEITA a lista de ativos, inicia a resposta com a tag [MERCADO ESTAGNADO - POSTURA DEFENSIVA] e passa diretamente para o passo 7 (Saúde do Mercado).

2. OS 3 MELHORES ALVOS: Se existirem oportunidades reais, foca-te num máximo de 3 ativos. Se um ativo detetar EARNINGS = PERIGO, ele é sumariamente desclassificado e não pode ser recomendado.

3. ANÁLISE DE VULNERABILIDADE E POTENCIAL (CRÍTICO):
   Cruza os dados e aplica as seguintes bandeiras táticas:
   - REGRA DA MOLA (MM20): Se 'Dist MM20' > 2.5%, alerta [AVISO: PREÇO ESTICADO - Risco de Pullback].
   - COMPRESSÃO (ATR vs RVOL): Se o RVOL > 1.5 e Momentum sólido, marca [POTENCIAL DE COMPRESSÃO] (alta prioridade).
   - EXAUSTÃO: Se RSI > 70 mas Momentum < 1.0 ou RVOL < 1.3, alerta [AVISO DE EXAUSTÃO - Sem Combustível].
   - BARREIRAS INSTITUCIONAIS: Se Entrada ou Take-Profit estiverem a <1% de um número redondo maior (ex: 50.00, 100.00), alerta [PAREDE INSTITUCIONAL - Risco de rejeição].
   - ATIVOS ERRÁTICOS: Lê 'Vol' junto ao ATR no comboio. Se Vol > 5%, alerta [ATIVO ERRÁTICO - Alta Volatilidade].

4. TÁTICA DE EXECUÇÃO:
   - GAPS DE ABERTURA: Inclui: "Se abrir em Gap > 1% da entrada, ABORTA."
   - GESTÃO DE LUCRO: Se ADX > 35, instrui: "[TENDÊNCIA EXTREMA] Ignora TP, gere pelo Trailing". Se ADX < 30: "[TENDÊNCIA MODERADA] Respeita o TP fixo."

5. RISCOS DE CALENDÁRIO E CORRELAÇÃO:
   - SEXTA-FEIRA: Lê a (INFO SISTEMA). Se for Sexta-feira ('SIM'), exige Lote Reduzido.
   - CORRELAÇÃO: Se 2 ou mais ativos do Top 3 forem do mesmo Setor/País, emite "[AVISO DE CORRELAÇÃO] - Risco concentrado" e escolhe apenas o melhor.

6. ESTRUTURA VISUAL OBRIGATÓRIA (Usa exatamente este template para cada ativo validado):
   
   🎯 [TICKER] - [Nome da Empresa] ([Setor])
   - 🚩 BANDEIRAS: (Lista aqui os avisos da regra 3 e 5, ou "Limpo" se não houver)
   - ⚙️ EXECUÇÃO: (Menciona a regra dos Gaps e Gestão de Lucro)
   - 🛡️ TAMANHO DA POSIÇÃO: (Recomenda Lote Completo ou Lote Reduzido a 50%)
   - 🔢 DADOS EXATOS: Entrada: X | Stop: X | TP: X | BE: X | Trailing: X | Qtd: X (Se Lote Reduzido, indica Qtd original / 2)
   - 📋 REFERÊNCIA: (Cola a linha original do comboio aqui)

7. SAÚDE DO MERCADO E MANDATO FINAL: 
   Gera sempre, no final do e-mail, uma secção "Saúde do Mercado:" com 2 ou 3 frases sobre o estado geral dos ativos analisados (mesmo que tenham sido todos rejeitados). 
   De seguida, inclui SEMPRE de forma isolada e a negrito no fim do email a seguinte tática:
   **"TÁTICA DE EXECUÇÃO EUROPA: Não executar ordens antes das 09h00 (Hora de Lisboa). Deixar a volatilidade inicial queimar os amadores. Atenção máxima a partir das 14h30 com a abertura de Wall Street."**
"""

bloco_texto_ia = f"{prompt_sistema_embutido}\n\n--------------------------------------------------\n"

if not ativos_acionados:
    bloco_texto_ia += "[MERCADO CHOPPY - FICA DE FORA HOJE] - Nenhum ativo europeu preencheu os requisitos mínimos de entrada.\n"
else:
    bloco_texto_ia += "DADOS DOS ATIVOS ACIONADOS (COMBOIO EUROPA):\n\n"
    for item in ativos_acionados:
        dist_mm20_str = f"{item.get('dist_mm20', 'N/A')}%" if item.get('dist_mm20') != "N/A" else "N/A"
        
        linha = (
            f"{item['ticker']},Nome: {item['nome']},Setor: {item['setor']},Preço: {item['preco']},"
            f"Dist MM20: {dist_mm20_str},Momentum: {item.get('momentum', 'N/A')},"
            f"RSI: {item['rsi']},ADX: {item['adx']},ATR: {item.get('atr', 'N/A')} (Vol: {item['atr_perc']}%),"
            f"RVOL: {item['rvol']},Estado: {item['estado']},Entrada: {item['entrada']},"
            f"Stop: {item['stop']},Take-Profit: {item['alvo']},Break-Even: {item.get('be', 'N/A')},"
            f"Qtd: {item['quantidade']},Trailing: {item['trailing']},"
            f"Earnings: {item.get('earnings', 'OK')},"
            f"Data: {item['data']}"
        )
        bloco_texto_ia += linha + "\n"

with open("comboio_europa.txt", "w", encoding="utf-8") as f:
    f.write(bloco_texto_ia)
    
# ASSUNTO DE SISTEMA CORRIGIDO (O Agente 02 vai procurar por isto)
enviar_email_para_agente_ia(bloco_texto_ia, assunto="tradingRelatorioIA Europa")
