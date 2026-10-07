import os
import requests
import json
from datetime import datetime
from zoneinfo import ZoneInfo

# Podes colar temporariamente a tua URL do webhook aqui para testar (ou garantir que a tens nas variáveis de ambiente)
WEBHOOK_URL = os.environ.get('WEBHOOK_URL') 

def testar_escrita_sheets():
    if not WEBHOOK_URL:
        print("[ERRO] WEBHOOK_URL não está definido nas variáveis de ambiente.")
        return

    # Dados falsos (mock) simulando uma oportunidade detetada pelo motor PEAD
    dados_falsos = [
        {
            "ticker": "TEST",
            "preco": 150.25,
            "data_earnings": "05/10/2026",
            "var_perc": "4.50%",
            "rvol": 3.2,
            "estado": "EARNINGS MOMENTUM - Teste Manual",
            "entrada": 150.25,
            "stop": 145.00,
            "tp": 160.75,
            "qtd": 4.76,
            "valor_investir": "~715.19 USD",
            "comboio": "TEST,Nome: Empresa Teste Lda,Setor: Tecnologia,Preço: 150.25,DataEarnings: 05/10/2026,VarDia: 4.5%,RVOL: 3.2,Estado: TESTE"
        }
    ]

    payload_sheets = {
        "acao": "atualizar_earnings_drift",
        "aba": "Earnings Drift",
        "dados": dados_falsos
    }

    headers = {'Content-Type': 'application/json'}
    
    print("A enviar dados de teste para o Google Sheets via Webhook...")
    try:
        resposta = requests.post(WEBHOOK_URL, data=json.dumps(payload_sheets), headers=headers)
        print(f"Status HTTP recebido: {resposta.status_code}")
        print(f"Resposta do Webhook: {resposta.text}")
        
        if resposta.status_code == 200:
            print("[SUCESSO] Pedido aceite! Vai ao teu Google Sheets verificar se a linha 'TEST' apareceu na aba 'Earnings Drift'.")
        else:
            print("[ERRO] O Google Sheets rejeitou o pedido.")
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha na comunicação: {e}")

if __name__ == "__main__":
    testar_escrita_sheets()
