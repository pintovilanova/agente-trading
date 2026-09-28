import yfinance as yf
import pandas as pd
import pandas_ta as ta
import requests
import json
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# Configurações de Variáveis de Ambiente
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")
NOME_FICHEIRO_TXT = "comboio_europa.txt"

def calcular_indicadores(ticker):
    try:
        df = yf.download(ticker, period="2y", interval="1d", progress=False)
        if df.empty or len(df) < 20:
            return None
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df['MM20'] = ta.sma(df['Close'], length=20)
        df['RSI'] = ta.rsi(df['Close'], length=14)
        df['ADX'] = ta.adx(df['High'], df['Low'], df['Close'], length=14)['ADX_14']
        df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        df['Momentum'] = df['Close'] - df['Close'].shift(10)
        
        ultimo = df.iloc[-1]
        
        return {
            "preco": round(float(ultimo['Close']), 2),
            "dist_mm20": round(((float(ultimo['Close']) - float(ultimo['MM20'])) / float(ultimo['MM20'])) * 100, 2),
            "momentum": round(float(ultimo['Momentum']), 2),
            "rsi": round(float(ultimo['RSI']), 2),
            "adx": round(float(ultimo['ADX']), 2),
            "atr": round(float(ultimo['ATR']), 2)
        }
    except Exception as e:
        print(f"Erro ao processar {ticker}: {e}")
        return None

def enviar_email(linhas_comboio):
    print("A preparar o envio do e-mail de segurança (Plano B)...")
    if not EMAIL_USER or not EMAIL_PASS:
        print("Erro: Credenciais de e-mail não encontradas nas variáveis de ambiente.")
        return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER 
    msg['Subject'] = f"PROMPT EUROPA PRONTO A USAR - {datetime.now().strftime('%d/%m/%Y')}"
    
    # Verifica se hoje é sexta-feira para preencher o prompt dinamicamente
    hoje_e_sexta = "SIM" if datetime.today().weekday() == 4 else "NÃO"
    
    # Constrói o corpo do e-mail com o PROMPT COMPLETO + DADOS
    corpo_email = f"""MODO DIÁRIO ATIVO - PREDADOR DE BREAKOUTS (EUROPA): Avalia os seguintes ativos da minha watchlist europeia.
(INFO SISTEMA - Hoje é Sexta-feira? {hoje_e_sexta})
Contexto: O mercado europeu está sujeito a aberturas armadilhadas e sofre forte influência da abertura americana à tarde. A tua missão é PROTEGER O CAPITAL, desconfiar do motor matemático e expor ativamente o risco de cada trade, priorizando apenas os arranques com força institucional real.

Regras Operacionais Estritas de Triagem e Ataque:
1. FILTRO CÉTICO INICIAL: Analisa apenas ativos com 'Forca Consolidada' ou 'Alerta Iminente'. Se o panorama geral for fraco (maioria com ADX < 25 e RVOL baixo), REJEITA TUDO e inicia o e-mail APENAS com: [MERCADO CHOPPY - FICA DE FORA HOJE].
2. OS 3 MELHORES ALVOS: Se existirem oportunidades reais, foca-te num máximo de 3 ativos. Se um ativo detetar EARNINGS = PERIGO, ele é sumariamente desclassificado e não pode ser recomendado.
3. ANÁLISE DE VULNERABILIDADE E POTENCIAL (CRÍTICO):
   - REGRA DA MOLA (MM20): Se 'Dist MM20' > 2.5%, alerta [AVISO: PREÇO ESTICADO - Risco de Pullback].
   - COMPRESSÃO (ATR vs RVOL): Se o RVOL > 1.5 e Momentum sólido, marca [POTENCIAL DE COMPRESSÃO] (alta prioridade).
   - EXAUSTÃO: Se RSI > 70 mas Momentum < 1.0 ou RVOL < 1.3, alerta [AVISO DE EXAUSTÃO - Sem Combustível].
   - BARREIRAS INSTITUCIONAIS: Se Entrada ou Take-Profit estiverem a <1% de um número redondo maior (ex: 10.00, 50.00, 100.00), alerta [PAREDE INSTITUCIONAL - Risco de rejeição].
   - ATIVOS ERRÁTICOS: Lê 'Vol' junto ao ATR. Se Vol > 5%, alerta [ATIVO ERRÁTICO - Alta Volatilidade].
4. TÁTICA DE EXECUÇÃO EUROPA:
   - GAPS DE ABERTURA: Inclui: "Se abrir em Gap > 1% da entrada, ABORTA."
   - GESTÃO DE LUCRO: Se ADX > 35, instrui: "[TENDÊNCIA EXTREMA] Ignora TP, gere pelo Trailing". Se ADX < 30: "[TENDÊNCIA MODERADA] Respeita o TP fixo."
5. RISCOS DE CALENDÁRIO E CORRELAÇÃO:
   - SEXTA-FEIRA: Lê a (INFO SISTEMA). Se for Sexta-feira ('SIM'), exige Lote Reduzido.
   - CORRELAÇÃO: Se 2 ou mais ativos do Top 3 forem do mesmo País/Setor, emite "[AVISO DE CORRELAÇÃO] - Risco concentrado" e escolhe apenas o melhor.
6. ESTRUTURA VISUAL OBRIGATÓRIA:
   🎯 [TICKER] - [Nome da Empresa] ([Setor/País])
   - 🚩 BANDEIRAS: (Lista aqui os avisos da regra 3 e 5, ou "Limpo" se não houver)
   - ⚙️ EXECUÇÃO: (Menciona a regra dos Gaps e Gestão de Lucro)
   - 🛡️ TAMANHO DA POSIÇÃO: (Recomenda Lote Completo ou Lote Reduzido a 50%)
   - 🔢 DADOS EXATOS: Entrada: X | Stop: X | TP: X | BE: X | Trailing: X | Qtd: X
   - 📋 REFERÊNCIA: (Cola a linha original do comboio aqui)
7. SAÚDE DO MERCADO E MANDATO FINAL:
   Termina o email com uma frase sobre o estado do mercado E inclui SEMPRE de forma isolada e a negrito no fim do email:
   **"TÁTICA DE EXECUÇÃO EUROPA: Não executar ordens antes das 09h00 (Hora de Lisboa). Deixar a volatilidade da primeira hora queimar os amadores. Atenção máxima a partir das 14h30 com a abertura de Wall Street."**

--------------------------------------------------
DADOS DOS ATIVOS (COMBOIO EUROPA):
""" + "\n".join(linhas_comboio)

    msg.attach(MIMEText(corpo_email, 'plain', 'utf-8'))
    
    try:
        servidor = smtplib.SMTP('smtp.gmail.com', 587)
        servidor.starttls()
        servidor.login(EMAIL_USER, EMAIL_PASS)
        servidor.send_message(msg)
        servidor.quit()
        print("E-mail de segurança (prompt + dados) enviado com sucesso!")
    except Exception as e:
        print(f"Falha ao enviar e-mail: {e}")

def processar_europa():
    print("A iniciar extração de dados da Europa...")
    
    resposta = requests.get(WEBHOOK_URL)
    ativos = resposta.json()
    
    linhas_txt = []
    atualizacoes_sheets = []
    data_atual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    for ativo in ativos:
        ticker = ativo.get("ticker")
        nome = ativo.get("nome")
        
        if not ticker or ticker == "#N/A":
            continue
            
        print(f"A analisar: {ticker}")
        dados = calcular_indicadores(ticker)
        
        if dados:
            linha_comboio = f"{ticker},Nome: {nome},Setor: Europa,Preço: {dados['preco']},Dist MM20: {dados['dist_mm20']}%,Momentum: {dados['momentum']},RSI: {dados['rsi']},ADX: {dados['adx']},ATR: {dados['atr']},Data: {data_atual}"
            linhas_txt.append(linha_comboio)
            
            atualizacoes_sheets.append({
                "ticker": ticker,
                "preco": dados['preco'],
                "momentum": dados['momentum'],
                "rsi": dados['rsi'],
                "adx": dados['adx'],
                "atr": dados['atr'],
                "time": data_atual,
                "comboio": linha_comboio
            })

    if linhas_txt:
        with open(NOME_FICHEIRO_TXT, "w", encoding="utf-8") as f:
            f.write("\n".join(linhas_txt))
        print(f"Ficheiro {NOME_FICHEIRO_TXT} gerado com sucesso!")

        # Envia o e-mail de backup (Prompt + Dados prontos a copiar)
        enviar_email(linhas_txt)

    if atualizacoes_sheets:
        print("A enviar atualizações detalhadas para o Google Sheets...")
        payload = {
            "acao": "atualizar_colunas_todas",
            "dados": atualizacoes_sheets
        }
        headers = {'Content-Type': 'application/json'}
        r = requests.post(WEBHOOK_URL, data=json.dumps(payload), headers=headers)
        if r.status_code == 200:
            print("Google Sheets atualizado com sucesso!")
        else:
            print(f"Erro ao atualizar Sheets: {r.status_code} - {r.text}")

if __name__ == "__main__":
    processar_europa()
