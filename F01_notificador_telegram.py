# F01_notificador_telegram.py

import os
import requests

def enviar_alerta(mensagem, parse_mode=None):
    """
    Função genérica para enviar mensagens para o Telegram.
    Lê o Token e o Chat ID das variáveis de ambiente do sistema/GitHub Secrets.
    """
    token = os.environ.get('TELEGRAM_BOT_TOKEN_GERAL')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    
    if not token or not chat_id:
        print("[AVISO] Variáveis TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não configuradas.")
        return False
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": mensagem
    }
    
    # Opcional: se quiseres usar Markdown em alguma mensagem específica
    if parse_mode:
        payload["parse_mode"] = parse_mode
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            print("[SUCESSO] Notificação enviada via Telegram!")
            return True
        else:
            print(f"[AVISO] Falha ao enviar Telegram: {resp.text}")
            return False
    except Exception as e:
        print(f"[ERRO] Erro de rede ao enviar Telegram: {e}")
        return False
