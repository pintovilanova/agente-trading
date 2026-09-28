import yfinance as yf
import pandas as pd
import pandas_ta as ta
import requests
import json
import os
from datetime import datetime

WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
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

def processar_europa():
    print("A iniciar extração de dados da Europa...")
    
    # 1. Obter a lista do Google Sheets (GET)
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
            linha_comboio = f"{ticker},Nome: {nome},Setor: N/A,Preço: {dados['preco']},Dist MM20: {dados['dist_mm20']}%,Momentum: {dados['momentum']},RSI: {dados['rsi']},ADX: {dados['adx']},ATR: {dados['atr']},Data: {data_atual}"
            linhas_txt.append(linha_comboio)
            
            # AGORA ENVIAMOS TODOS OS DADOS SOLTOS TAMBÉM
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

    # Gravar o TXT localmente no GitHub
    with open(NOME_FICHEIRO_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas_txt))

    # 2. Enviar de volta para o Google Sheets (POST)
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
