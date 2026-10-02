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

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# ===================================================================
# 1. FUNÇÃO DE ENVIO DE EMAIL
# ===================================================================
def enviar_email_para_agente_ia(relatorio_texto, assunto="tradingRelatorioIA US"):
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
# 2. BUSCAR A WATCHLIST E POSIÇÕES ATIVAS (Google Sheets via Webhook)
# ===================================================================
print("A carregar a Watchlist e Posições Ativas a partir do Google Sheets...")
try:
    resposta_webhook = requests.get(WEBHOOK_URL)
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
            print(f"[SUCESSO] {len(ativos_data)} ativos carregados da Watchlist.")
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

        alerta_earnings = "OK"
        setor = "Desconhecido"
        try:
            ticker_obj = yf.Ticker(ticker)
            setor = ticker_obj.info.get('sector', 'Desconhecido')
            
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

        # Adicionados os novos indicadores aqui
        df.ta.rsi(length=14, append=True)
        df.ta.adx(length=14, append=True)
        df.ta.atr(length=14, append=True)
        df.ta.sma(length=200, append=True)
        df.ta.sma(length=20, append=True)
        df.ta.mom(length=14, append=True)
        df.ta.ema(length=9, append=True)  # <-- NOVO: EMA 9 Períodos

        # Cálculo do Volume em relação à média de 20 (RVOL > 1 significa Volume > Média 20)
        media_volume_20 = df['Volume'].rolling(window=20).mean()
        df['RVOL'] = df['Volume'] / media_volume_20

        ultimo_dia = df.iloc[-1]
        dia_anterior = df.iloc[-2]

        preco = ultimo_dia['Close']
        preco_anterior = dia_anterior['Close']
        var_perc = ((preco - preco_anterior) / preco_anterior) * 100
        
        sma20 = ultimo_dia['SMA_20']
        dist_mm20 = ((preco - sma20) / sma20) * 100
        
        # <-- NOVO: Extração dos valores da EMA9 para o cruzamento
        ema9 = ultimo_dia['EMA_9']
        ema9_anterior = dia_anterior['EMA_9']
        
        cruzou_ema9 = (preco > ema9) and (preco_anterior <= ema9_anterior)
        acima_ema9 = preco > ema9

        rvol = ultimo_dia['RVOL']
        adx = ultimo_dia['ADX_14']
        rsi = ultimo_dia['RSI_14']
        atr = ultimo_dia['ATRr_14']
        momentum = ultimo_dia['MOM_14']

        atr_perc = round((atr / preco) * 100, 2)

        recomendacao = "Observar"
        preco_entrada = "N/A"
        preco_stop = "N/A"
        preco_tp = "N/A"
        preco_be = "N/A"
        qtd_acoes = "N/A"
        multiplicador_atr = 1.0

        trailing_base = preco - (atr * multiplicador_trailing_ts)
        trailing_final = round(trailing_base, 2)

        preco_caiu_hoje = preco < preco_anterior
        volume_despejo = rvol > 1.20

        # ===================================================================
        # GUILHOTINA MATEMÁTICA - OTIMIZADA PARA SUBIDAS EMINENTES E EMA9
        # ===================================================================
        if (preco_caiu_hoje and volume_despejo) or (momentum <= 0.5):
            recomendacao = "Observar"
            
        elif var_perc > 0 and adx < 25 and not cruzou_ema9:
            recomendacao = "Aguardar Recuo"
            preco_entrada = round(preco - (atr * 0.4), 2)
            multiplicador_atr = 1.0
            
        # NOVA REGRA: Antecipação de Tendência (Cruzou EMA9 hoje, Momentum Positivo, Volume > Média 20)
        elif cruzou_ema9 and rvol > 1.00 and momentum > 0.50 and rsi > 50:
            recomendacao = "Ignicao EMA9"
            preco_entrada = round(preco - (atr * 0.1), 2)  # Queremos entrar cedo, logo desconto mínimo
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

        # VERIFICAÇÃO SE JÁ EXISTE POSIÇÃO ATIVA NO DIÁRIO DE BORDO
        if ticker in posicoes_ativas:
            pos_info = posicoes_ativas[ticker]
            info_carteira = f"SIM (Entrada: {pos_info['precoEntrada']}, StopAtual: {pos_info['stopAtual']}, Qtd: {pos_info['quantidade']})"
        else:
            info_carteira = "NÃO"

        # DADOS PARA O GOOGLE SHEETS
        linha_comboio_completa = (
            f"{ticker},Nome: {nome_empresa},Setor: {setor},Preço: {round(preco, 2)},"
            f"Dist MM20: {round(dist_mm20, 2)}%,Momentum: {round(momentum, 2)},"
            f"RSI: {round(rsi, 2)},ADX: {round(adx, 2)},ATR: {round(atr, 2)} (Vol: {atr_perc}%),"
            f"RVOL: {round(rvol, 2)},Estado: {recomendacao},Entrada: {preco_entrada_str},"
            f"Stop: {preco_stop},Take-Profit: {preco_tp},Break-Even: {preco_be},"
            f"Qtd: {qtd_acoes},Trailing: {trailing_final},Earnings: {alerta_earnings},"
            f"PosicaoAtiva: {info_carteira},Data: {data_atual}"
        )

        resultados_para_sheets.append({
            "ticker": ticker,
            "preco": round(preco, 2),
            "momentum": round(momentum, 2),
            "rsi": round(rsi, 2),
            "adx": round(adx, 2),
            "atr": round(atr, 2),
            "time": data_atual,
            "comboio": linha_comboio_completa
        })

        # GUARDAR PARA O COMBOIO DA IA
        comboio_ia.append({
            "ticker": ticker,
            "nome": nome_empresa,
            "setor": setor,
            "estado": recomendacao,
            "preco": round(preco, 2),
            "rsi": round(rsi, 2),
            "adx": round(adx, 2),
            "rvol": round(rvol, 2),
            "atr": round(atr, 2),
            "atr_perc": atr_perc,
            "momentum": round(momentum, 2),
            "dist_mm20": round(dist_mm20, 2),
            "entrada": round(preco_entrada, 2) if isinstance(preco_entrada, float) else preco_entrada,
            "stop": preco_stop,
            "alvo": preco_tp,
            "be": preco_be,
            "quantidade": qtd_acoes,
            "trailing": trailing_final,
            "earnings": alerta_earnings,
            "posicao_ativa": info_carteira,
            "data": data_atual
        })
        
        print(f"[OK] {ticker} analisado. Estado: {recomendacao} | Posição Ativa: {info_carteira}")

    except Exception as e:
        print(f"[ERRO] Falha ao processar {ticker}: {e}")

# ===================================================================
# 5. ENVIO PARA O GOOGLE SHEETS
# ===================================================================
if resultados_para_sheets and WEBHOOK_URL:
    print("\nA atualizar o Google Sheets (Aba: Analise Compra)...")
    try:
        payload_sheets = {
            "acao": "atualizar_colunas_todas",
            "aba": "Analise Compra",
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

# FILTRO ATUALIZADO: Inclui sinais de compra OU ativos que já tenhas em carteira (mesmo em "Observar")
ativos_acionados = [
    item for item in comboio_ia 
    if item["estado"] != "Observar" or not item["posicao_ativa"].startswith("NÃO")
]

prompt_sistema_embutido = f"""MODO DIÁRIO ATIVO - PREDADOR DE BREAKOUTS: Avalia os seguintes ativos da minha watchlist.
(INFO SISTEMA - Hoje é Sexta-feira? {hoje_e_sexta})
Contexto: O teu mandato principal é a PRESERVAÇÃO DE CAPITAL e a gestão de risco assimétrica. A tua missão é atuar como auditor do motor matemático: procura ativamente falhas na estrutura de cada trade, expõe o risco e aprova exclusivamente os arranques que demonstrem força institucional inegável.

Regras Operacionais Estritas de Triagem, Carteira e Ataque:

1. AVALIAÇÃO MACRO E ADAPTAÇÃO DE RISCO: Olha primeiro para a lista completa. Se a esmagadora maioria dos ativos estiver em 'Aguardar Recuo' (ADX < 25 e baixo RVOL), o panorama geral é considerado de Alto Risco. 
   - Se o panorama for de Alto Risco E NÃO houver ativos em alerta, inicia o e-mail com [MERCADO ESTAGNADO - POSTURA DEFENSIVA] e salta para o passo 7.
   - Se o panorama for de Alto Risco, MAS existirem ativos em 'Forca Consolidada' ou 'Alerta Iminente', analisa-os, mas emite obrigatoriamente a bandeira 🚩 [AMBIENTE MACRO HOSTIL - EXIGIDO LOTE REDUZIDO A 50%].

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
   - SEXTA-FEIRA: Lê a (INFO SISTEMA). Se for Sexta-feira ('SIM'), exige Lote Reduzido à tarde.
   - CORRELAÇÃO: Se 2 ou mais ativos do Top 3 forem do mesmo Setor, emite "[AVISO DE CORRELAÇÃO] - Risco concentrado" e escolhe apenas o melhor.

6. GESTÃO DE POSIÇÕES ATIVAS E ESTRUTURA VISUAL OBRIGATÓRIA (CRÍTICO):
   - Verifica o campo 'PosicaoAtiva' em cada linha do comboio.
   - **REGRA DE OURO:** Se a PosicaoAtiva indicar **SIM**, é **estritamente proibido** sugerir nova entrada ou alocação de capital. O foco é 100% a gestão da posição existente.
   - **GESTÃO DO STOP LOSS:** Compara o 'StopAtual' indicado na posição ativa com o valor de 'Trailing' calculado pelo sistema. 
     * Se o 'Trailing' for superior ao 'StopAtual', emite obrigatoriamente a recomendação: [AJUSTE DE STOP: Subir o Stop Loss atual de X para o novo valor de Trailing Y].
     * Se o 'StopAtual' já for superior ou se o trailing ainda estiver abaixo, indica: [MANUTENÇÃO DE STOP: Manter stop atual em X].
   - Usa obrigatoriamente este template para cada ativo validado:

   🎯 [TICKER] - [Nome da Empresa] ([Setor])
   - 🚩 BANDEIRAS: (Lista aqui os avisos da regra 3 e 5, ou "Limpo" se não houver)
   - ⚠️ ESTADO NA CARTEIRA: [Se POSIÇÃO JÁ ATIVA: "POSIÇÃO ATIVA (Entrada: X | Stop Atual: Y | Qtd: Z). Análise de Trailing abaixo." | Se NÃO: "Nenhuma posição aberta"]
   - ⚙️ EXECUÇÃO / DEFESA: (Indica claramente se deves subir o Stop Loss comparando o Stop Atual com o Trailing, ou mantê-lo)
   - 🛡️ TAMANHO DA POSIÇÃO: [Se já tens posição: "N/A - Já em Carteira" | Se não tens: "Lote Completo" ou "Lote Reduzido a 50%"]
   - 🔢 DADOS EXATOS: Entrada: X | Stop: X | TP: X | BE: X | Trailing: X | Qtd: X | Valor a Investir: [Se já tens posição: "N/A - Posição Existente" | Se não tens: ~X$]
   - 📋 REFERÊNCIA: (Cola a linha original do comboio aqui)

7. SAÚDE DO MERCADO E MANDATO FINAL: 
   Termina o email com uma frase sobre o estado do mercado E inclui SEMPRE de forma isolada e a negrito no fim do email:
   **"TÁTICA DE EXECUÇÃO OBRIGATÓRIA: Não executar ordens antes das 15h00. Deixar a volatilidade inicial queimar os amadores e confirmar a verdadeira direção institucional."**
"""

bloco_texto_ia = f"{prompt_sistema_embutido}\n\n--------------------------------------------------\n"

if not ativos_acionados:
    bloco_texto_ia += "[MERCADO ESTAGNADO - POSTURA DEFENSIVA] - Nenhum ativo preencheu os requisitos mínimos de entrada.\n"
else:
    bloco_texto_ia += "DADOS DOS ATIVOS ACIONADOS (COMBOIO):\n\n"
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
            f"PosicaoAtiva: {item['posicao_ativa']},Data: {item['data']}"
        )
        bloco_texto_ia += linha + "\n"

with open("comboio_temp.txt", "w", encoding="utf-8") as f:
    f.write(bloco_texto_ia)
    
enviar_email_para_agente_ia(bloco_texto_ia, assunto="tradingRelatorioIA US")
