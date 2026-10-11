# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR DE BREAKOUTS (EUROPA)
# ===================================================================
from datetime import datetime
from zoneinfo import ZoneInfo
import yfinance as yf
import pandas_ta as ta
import pandas as pd
import requests
import os
import sys
import smtplib
import json
import numpy as np
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ===================================================================
# 0.1 TRAVA DE FIM DE SEMANA (Não corre ao Sábado e Domingo)
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O mercado está fechado. O Agente vai descansar.")
    #sys.exit(0)

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
# 1. FUNÇÃO DE ENVIO DE EMAIL (Com Sistema Anti-Falhas)
# ===================================================================
def enviar_email_para_agente_ia(relatorio_texto, assunto="🇪🇺🎯 tradingRelatorioIA Europa 🛡️"):
    print(f"\nA enviar email para o Agente IA (Assunto: '{assunto}')...")
    
    # Validação de segurança das credenciais
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] Credenciais de email em falta. A saltar envio.")
        return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = assunto
    
    msg.attach(MIMEText(relatorio_texto, 'plain', 'utf-8'))
    
    # Sistema de Tolerância a Falhas (Retry) com Timeout
    max_tentativas = 3
    for tentativa in range(max_tentativas):
        try:
            # Adicionado timeout=15 para evitar que a ligação encrave
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
            server.quit()
            
            print(f"[SUCESSO] Email enviado na tentativa {tentativa + 1}! O teu Agente IA já pode ler a caixa de entrada.")
            break  # Se enviou com sucesso, quebra o loop e avança
            
        except Exception as e:
            print(f"[ERRO] Falha ao enviar o email (tentativa {tentativa + 1} de {max_tentativas}): {e}")
            if tentativa < max_tentativas - 1:
                print("A aguardar 5 segundos antes de tentar novamente...")
                time.sleep(5)
            else:
                print("[ERRO CRÍTICO] O servidor Gmail fechou a ligação definitivamente. Falha no envio.")

# ===================================================================
# 2. BUSCAR A WATCHLIST E POSIÇÕES ATIVAS (Google Sheets via Webhook)
# ===================================================================
print(f"A carregar a Watchlist e Posições Ativas da Europa a partir do Google Sheets (Aba: {NOME_ABA_EUROPA})...")
try:
    url_get = f"{WEBHOOK_URL}?aba={NOME_ABA_EUROPA}"
    resposta_webhook = requests.get(url_get)
    if resposta_webhook.status_code == 200:
        dados_webhook = resposta_webhook.json()
        
        if isinstance(dados_webhook, dict) and "ativos" in dados_webhook:
            ativos_data = dados_webhook.get("ativos", [])
            posicoes_ativas = dados_webhook.get("posicoesAtivas", {})
        elif isinstance(dados_webhook, list):
            ativos_data = dados_webhook
            posicoes_ativas = {}
        else:
            ativos_data = []
            posicoes_ativas = {}

        if len(ativos_data) > 0:
            print(f"[SUCESSO] {len(ativos_data)} ativos europeus carregados da Watchlist.")
            print(f"[SUCESSO] {len(posicoes_ativas)} posições ativas detetadas no Diário de Bordo.")
        else:
            print("[ERRO] A lista de ativos veio vazia.")
            sys.exit(1)
    else:
        print(f"[ERRO] Falha ao descarregar dados: {resposta_webhook.status_code}")
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

dados_temporarios = []

# ===================================================================
# 4. MOTOR MATEMÁTICO V2 (Para todos os Ativos)
# ===================================================================
for ativo_info in ativos_data:
    ticker = ativo_info.get("ticker")
    nome_empresa = ativo_info.get("nome", "N/A")
    rs_score = ativo_info.get("rs_score", "N/A")
    
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
        df.ta.ema(length=9, append=True)

        media_volume_20 = df['Volume'].rolling(window=20).mean()
        df['RVOL'] = df['Volume'] / media_volume_20

        ultimo_dia = df.iloc[-1]
        dia_anterior = df.iloc[-2]

        preco = ultimo_dia['Close']
        preco_anterior = dia_anterior['Close']
        var_perc = ((preco - preco_anterior) / preco_anterior) * 100
        
        sma20 = ultimo_dia['SMA_20']
        dist_mm20 = ((preco - sma20) / sma20) * 100
        
        ema9 = ultimo_dia['EMA_9']
        ema9_anterior = dia_anterior['EMA_9']
        
        cruzou_ema9 = (preco > ema9) and (preco_anterior <= ema9_anterior) if pd.notna(ema9) and pd.notna(ema9_anterior) else False
        acima_ema9 = preco > ema9 if pd.notna(ema9) else False

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

        if pd.isna(momentum) or pd.isna(adx) or pd.isna(rvol) or pd.isna(rsi) or pd.isna(dist_mm20) or pd.isna(atr):
             recomendacao = "Observar"
        elif (preco_caiu_hoje and volume_despejo) or (momentum <= 0.5):
            recomendacao = "Observar"
            
        elif var_perc > 0 and adx < 25 and not cruzou_ema9:
            recomendacao = "Aguardar Recuo"
            preco_entrada = round(preco - (atr * 0.4), 2)
            multiplicador_atr = 1.0
            
        elif cruzou_ema9 and rvol > 1.00 and momentum > 0.50 and rsi > 50:
            recomendacao = "Ignicao EMA9"
            preco_entrada = round(preco - (atr * 0.1), 2)
            multiplicador_atr = 1.2
            
        elif var_perc > 0 and adx >= 30 and rvol >= 1.20 and (55.00 <= rsi <= 72.00) and (0.00 <= dist_mm20 <= 3.50) and momentum > 1.50 and acima_ema9:
            recomendacao = "Forca Consolidada"
            preco_entrada = round(preco - (atr * 0.1), 2)
            multiplicador_atr = 1.3 
            
        elif adx >= 25 and rvol >= 1.00 and (50.00 <= rsi <= 75.00) and (-1.00 <= dist_mm20 <= 4.00) and momentum > 0.50 and acima_ema9:
            recomendacao = "Alerta Iminente"
            preco_entrada = round(preco - (atr * 0.2), 2)
            multiplicador_atr = 1.2
            
        else:
            recomendacao = "Observar"

        if recomendacao != "Observar" and preco_entrada != "N/A":
            preco_stop_calc = preco_entrada - (atr * multiplicador_atr)
            if preco_stop_calc > sma20 and preco > sma20:
                preco_stop_calc = sma20 * 0.995
            
            preco_stop = round(preco_stop_calc, 2)
            risco_por_acao = preco_entrada - preco_stop_calc
            
            if risco_por_acao > 0:
                tp_calc = preco_entrada + (risco_por_acao * racio_tp_base)
                preco_tp = round(tp_calc, 2)
                qtd_acoes = round(risco_maximo_dolares / risco_por_acao, 2) if risco_por_acao > 0 else "N/A"
                dist_tp = preco_tp - preco_entrada
                preco_be = round(preco_entrada + (dist_tp / 2), 2)
                trailing_final = round(max(trailing_base, preco_stop_calc), 2)

        data_atual = datetime.now(ZoneInfo("Europe/Lisbon")).strftime('%d/%m/%Y %H:%M:%S')

        # GESTÃO DE POSIÇÃO ATIVA COM FILTRAGEM DE ATIVA_FAST
        if ticker in posicoes_ativas:
            pos_info = posicoes_ativas[ticker]
            status_pos = pos_info.get('status', 'ATIVA')
            if status_pos == 'ATIVA_FAST':
                info_carteira = f"NÃO (Gerido pelo modelo FAST - ATIVA_FAST)"
            else:
                info_carteira = f"SIM (Entrada: {pos_info['precoEntrada']}, StopAtual: {pos_info['stopAtual']}, Qtd: {pos_info['quantidade']})"
        else:
            info_carteira = "NÃO"

        def limpa(v):
            try:
                if v == "N/A" or pd.isna(v): return "N/A"
                val = float(v)
                if np.isnan(val): return "N/A"
                return round(val, 2)
            except:
                return "N/A"

        # Análise contextual do RS Score
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

        dados_temporarios.append({
            "ticker": ticker,
            "nome": nome_empresa,
            "setor": setor,
            "rs_score": rs_score,
            "status_rs": status_rs,
            "preco": limpa(preco),
            "dist_mm20": limpa(dist_mm20),
            "ema9": limpa(ema9),
            "momentum": limpa(momentum),
            "rsi": limpa(rsi),
            "adx": limpa(adx),
            "atr": limpa(atr),
            "atr_perc": limpa(atr_perc),
            "rvol": limpa(rvol),
            "estado": recomendacao,
            "entrada": round(preco_entrada, 2) if isinstance(preco_entrada, float) else preco_entrada,
            "stop": preco_stop,
            "tp": preco_tp,
            "be": preco_be,
            "qtd_bruta": qtd_acoes,
            "trailing": trailing_final,
            "earnings": alerta_earnings,
            "posicao_ativa": info_carteira,
            "data": data_atual
        })
        
        print(f"[OK] {ticker} analisado. Estado: {recomendacao}")

    except Exception as e:
        print(f"[ERRO] Falha ao processar {ticker}: {e}")

# ===================================================================
# 4.1. AUDITORIA MACRO E CORTE MATEMÁTICO DE LOTES
# ===================================================================
total_ativos = len(dados_temporarios)
ativos_estagnados = sum(1 for d in dados_temporarios if d["estado"] in ["Observar", "Aguardar Recuo"])
macro_hostil = False

if hoje_e_sexta == "SIM":
    macro_hostil = True
elif total_ativos > 0 and (ativos_estagnados / total_ativos) >= 0.70:
    macro_hostil = True

tipo_lote = "Reduzido a 50%" if macro_hostil else "Completo"

resultados_para_sheets = []
comboio_ia = []

for d in dados_temporarios:
    qtd_final = d["qtd_bruta"]
    
    if qtd_final != "N/A" and macro_hostil:
        qtd_final = round(float(qtd_final) / 2, 2)
        
    valor_investir = "N/A - Posição Existente"
    if d['posicao_ativa'].startswith("NÃO") and d['entrada'] != "N/A" and qtd_final != "N/A":
        val_calc = float(d['entrada']) * float(qtd_final)
        valor_investir = f"~{val_calc:.2f} EUR"

    entrada_str = f"{d['entrada']:.2f}" if isinstance(d['entrada'], (int, float)) else d['entrada']
    
    linha_comboio = (
        f"{d['ticker']},Nome: {d['nome']},Setor: {d['setor']},Preço: {d['preco']},"
        f"RS Score: {d['rs_score']} ({d['status_rs']}),"
        f"Dist MM20: {d['dist_mm20']}%,EMA9: {d['ema9']},Momentum: {d['momentum']},"
        f"RSI: {d['rsi']},ADX: {d['adx']},ATR: {d['atr']} (Vol: {d['atr_perc']}%),"
        f"RVOL: {d['rvol']},Estado: {d['estado']},Entrada: {entrada_str},"
        f"Stop: {d['stop']},Take-Profit: {d['tp']},Break-Even: {d['be']},"
        f"Qtd: {qtd_final},ValorInvestir: {valor_investir},Trailing: {d['trailing']},Lote: {tipo_lote},Earnings: {d['earnings']},"
        f"PosicaoAtiva: {d['posicao_ativa']},Data: {d['data']}"
    )
    
    resultados_para_sheets.append({
        "ticker": d['ticker'],
        "preco": d['preco'],
        "rs_score": d['rs_score'],
        "momentum": d['momentum'],
        "rsi": d['rsi'],
        "adx": d['adx'],
        "atr": d['atr'],
        "time": d['data'],
        "comboio": linha_comboio
    })

    comboio_ia.append(d)
    comboio_ia[-1]["quantidade"] = qtd_final
    comboio_ia[-1]["valor_investir"] = valor_investir
    comboio_ia[-1]["lote"] = tipo_lote
    comboio_ia[-1]["comboio_str"] = linha_comboio

# ===================================================================
# 5. ENVIO PARA O GOOGLE SHEETS
# ===================================================================
if resultados_para_sheets and WEBHOOK_URL:
    print(f"\nA atualizar o Google Sheets (Aba: {NOME_ABA_EUROPA})...")
    try:
        payload_sheets = {
            "acao": "atualizar_colunas_todas",
            "aba": NOME_ABA_EUROPA,
            "dados": resultados_para_sheets
        }
        headers = {'Content-Type': 'application/json'}
        resposta = requests.post(WEBHOOK_URL, data=json.dumps(payload_sheets), headers=headers)
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

ativos_acionados = [
    item for item in comboio_ia 
    if item["estado"] != "Observar" or item["posicao_ativa"] != "NÃO"
]

prompt_sistema_embutido = f"""🇪🇺 MODO DIÁRIO ATIVO - PREDADOR DE BREAKOUTS (EUROPA): Avalia os seguintes ativos da minha watchlist europeia.
(INFO SISTEMA - Hoje é Sexta-feira? {hoje_e_sexta})
Contexto: O teu mandato principal é a PRESERVAÇÃO DE CAPITAL e a gestão de risco assimétrica em euros. A tua missão é atuar como auditor do motor matemático: procura ativamente falhas na estrutura de cada trade, expõe o risco e aprova exclusivamente os arranques que demonstrem força institucional inegável.

Regras Operacionais Estritas de Triagem, Carteira e Ataque:

1. AVALIAÇÃO MACRO E ADAPTAÇÃO DE RISCO: Olha primeiro para a lista completa. Se a esmagadora maioria dos ativos estiver em 'Aguardar Recuo' (ADX < 25 e baixo RVOL), o panorama geral é considerado de Alto Risco. 
   - Se o panorama for de Alto Risco E NÃO houver ativos em alerta, inicia o e-mail com [MERCADO ESTAGNADO - POSTURA DEFENSIVA], mas passa obrigatoriamente pelo Passo 6 para auditar a carteira ativa, e só depois conclui.
   - Se o panorama for de Alto Risco, MAS existirem ativos em 'Forca Consolidada', 'Ignicao EMA9' ou 'Alerta Iminente', analisa-os, mas emite obrigatoriamente a bandeira 🚩 [AMBIENTE MACRO HOSTIL - EXIGIDO LOTE REDUZIDO A 50%].

2. OS ALVOS (3 PRINCIPAIS + 2 SUPLENTES): Seleciona o Top 3 absoluto das melhores oportunidades para ataque. Se existirem mais configurações de elite, podes adicionar até 2 ativos extra classificados estritamente como 'SUPLENTE' para o caso de os principais abortarem na abertura. Se um ativo detetar EARNINGS = PERIGO, ele é sumariamente desclassificado.

3. ANÁLISE DE VULNERABILIDADE E POTENCIAL (CRÍTICO):
   Cruza os dados e aplica as seguintes bandeiras táticas:
   - REGRA DA MOLA (MM20): Se 'Dist MM20' > 2.5%, alerta [AVISO: PREÇO ESTICADO - Risco de Pullback].
   - CONTEXTO INSTITUCIONAL (RS SCORE): Presta especial atenção ao RS Score e estado de força relativa reportados em cada ativo para filtrar se o mercado apoia o arranque.
   - ANTECIPAÇÃO (EMA9): Se o estado for 'Ignicao EMA9', o motor está a tentar apanhar o movimento no início. Valida se o RVOL > 1.0 e se o Momentum apoia. Se sim, marca 🚀 [IGNIÇÃO EMA9 - Ponto de Entrada Antecipado].
   - COMPRESSÃO (ATR vs RVOL): Se o RVOL > 1.5 e Momentum sólido, marca [POTENCIAL DE COMPRESSÃO] (alta prioridade).
   - EXAUSTÃO: Se RSI > 70 mas Momentum < 1.0 ou RVOL < 1.3, alerta [AVISO DE EXAUSTÃO - Sem Combustível].
   - BARREIRAS INSTITUCIONAIS: Se Entrada ou Take-Profit estiverem a <1% de um número redondo maior (ex: 50.00, 100.00), alerta [PAREDE INSTITUCIONAL - Risco de rejeição].
   - ATIVOS ERRÁTICOS: Lê 'Vol' junto ao ATR no comboio. Se Vol > 5%, alerta [ATIVO ERRÁTICO - Alta Volatilidade].

4. TÁTICA DE EXECUÇÃO:
   - GAPS DE ABERTURA: Inclui: "Se abrir em Gap > 1% da entrada, ABORTA."
   - GESTÃO DE LUCRO: Se estado for 'Ignicao EMA9', o objetivo é capturar a explosão inicial; gere de perto pelo Trailing. Se ADX > 35: "[TENDÊNCIA EXTREMA] Ignora TP, gere pelo Trailing". Se ADX < 30: "[TENDÊNCIA MODERADA] Respeita o TP fixo."

5. RISCOS DE CALENDÁRIO E CORRELAÇÃO:
   - SEXTA-FEIRA: Lê a (INFO SISTEMA). Se for Sexta-feira ('SIM'), exige Lote Reduzido à tarde.
   - CORRELAÇÃO: Se os ativos escolhidos forem do mesmo Setor, emite "[AVISO DE CORRELAÇÃO] - Risco concentrado".

6. GESTÃO DE POSIÇÕES ATIVAS E ESTRUTURA VISUAL OBRIGATÓRIA (CRÍTICO):
   - Verifica o campo 'PosicaoAtiva' em cada linha do comboio.
   - **REGRA DE OURO:** Se a PosicaoAtiva indicar **SIM**, é **estritamente proibido** sugerir nova entrada ou alocação de capital. O foco é 100% a gestão da posição existente. (Nota: Se indicar 'Gerido pelo modelo FAST', desconsidera para efeitos de gestão de Breakouts).
   - **GESTÃO DO STOP LOSS:** Compara o 'StopAtual' com o 'Trailing'. Se o 'Trailing' for superior, recomenda subir o Stop. Se for igual ou inferior, indica manutenção.
   - Usa obrigatoriamente este template exato:

   🇪🇺🎯 [TICKER] - [Nome da Empresa] ([Setor]) [Adicionar tag (SUPLENTE) se aplicável]
   - 🚩 BANDEIRAS: (Avisos ou "Limpo")
   - 📊 CONTEXTO INSTITUCIONAL: RS Score e respetivo estado de Força Relativa.
   - ⚠️ ESTADO NA CARTEIRA: [POSIÇÃO ATIVA... ou Nenhuma posição aberta]
   - ⚙️ EXECUÇÃO / DEFESA: (Regra dos Gaps e Gestão de Stop)
   - 🛡️ TAMANHO DA POSIÇÃO: Lê o campo 'Lote' da linha de referência e transcreve (Ex: 'Lote Reduzido a 50%' ou 'Lote Completo').
   - 🔢 DADOS EXATOS: Entrada: X | Stop: X | TP: X | BE: X | Trailing: X | Qtd: X | Valor a Investir: [Lê o campo 'ValorInvestir' da referência e transcreve diretamente]. NÃO FAÇAS CÁLCULOS.
   - 📋 REFERÊNCIA: (Cola a linha original do comboio aqui)

7. SAÚDE DO MERCADO E MANDATO FINAL: 
   Termina com a frase obrigatória a negrito:
   **"TÁTICA DE EXECUÇÃO OBRIGATÓRIA: Não executar ordens antes das 09h00 (hora de Lisboa). Deixar a volatilidade inicial europeia queimar os amadores e confirmar a verdadeira direção institucional."**
"""

bloco_texto_ia = f"🇪🇺 RELATÓRIO DE DADOS BRUTOS - EUROPEAN BREAKOUTS 🛡️\n\n{prompt_sistema_embutido}\n\n--------------------------------------------------\n"

if not ativos_acionados:
    bloco_texto_ia += "[MERCADO ESTAGNADO - POSTURA DEFENSIVA] - Nenhum ativo europeu preencheu os requisitos mínimos de entrada.\n"
else:
    bloco_texto_ia += "DADOS DOS ATIVOS ACIONADOS (COMBOIO):\n\n"
    for item in ativos_acionados:
        bloco_texto_ia += item["comboio_str"] + "\n"

with open("comboio_europa.txt", "w", encoding="utf-8") as f:
    f.write(bloco_texto_ia)
    
enviar_email_para_agente_ia(bloco_texto_ia, assunto="🇪🇺🎯 tradingRelatorioIA Europa 🛡️")
