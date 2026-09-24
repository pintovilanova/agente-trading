import os
import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google import genai

# ==========================================
# 1. CONFIGURAÇÕES (Lidas do GitHub Secrets)
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")
ASSUNTO_DO_EMAIL = os.environ.get("ASSUNTO_DO_EMAIL")

IMAP_SERVER = "imap.gmail.com"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# Configurar o cliente da IA (Gemini 3.6-flash)
client = genai.Client(api_key=GEMINI_API_KEY)

# ==========================================
# 2. LER O ÚLTIMO EMAIL DO EXCEL
# ==========================================
def extrair_dados_do_email():
    print("A ligar à caixa de correio para ler os dados...")
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")
        
        # Pesquisa com UTF-8 para lidar com acentos no português
        status, messages = mail.search("UTF-8", f'(SUBJECT "{ASSUNTO_DO_EMAIL}")')
        
        email_ids = messages[0].split()
        if not email_ids:
            print("Nenhum email do Excel encontrado hoje com esse assunto.")
            return None
            
        ultimo_id = email_ids[-1]
        res, msg = mail.fetch(ultimo_id, "(RFC822)")
        
        for response in msg:
            if isinstance(response, tuple):
                msg_formatada = email.message_from_bytes(response[1])
                
                if msg_formatada.is_multipart():
                    for part in msg_formatada.walk():
                        if part.get_content_type() == "text/plain":
                            return part.get_payload(decode=True).decode()
                else:
                    return msg_formatada.get_payload(decode=True).decode()
                    
    except Exception as e:
        print(f"Erro ao ler o email: {e}")
        return None

# ==========================================
# 3. O CÉREBRO: INVOCAR A IA COM O PROMPT
# ==========================================
import time

def analisar_com_ia(dados_mercado):
    print("A enviar lista para análise tática do Gemini...")
    
    prompt_sistema = """
    És um assistente de trading sistemático e mecânico. O utilizador procura preservar capital e usa um rácio de risco de 1.2x.
    
    Missão:
    1. Lê a lista de ativos gerada pelo Excel.
    2. Destaca os 3 melhores (priorizando Força Consolidada, Alerta Iminente, ADX > 25, RVOL > 1 e RSI > 50).
    3. Alerta para os que devem ser evitados (RSI fraco ou Momentum muito negativo).
    4. Para os 3 melhores, extrai a dimensão da posição e calcula os alvos exatos considerando:
       - Risco = Preço Atual - Stop Loss.
       - Take-Profit = Preço de Entrada + (Risco * 1.2).
       - Break-Even = Ponto intermédio exato entre Entrada e Take-Profit.
       - Quantidade (Qtd) = Apresenta o valor exato extraído dos dados originais.
    5. OBRIGATÓRIO: Em cada um dos 3 melhores ativos apresentados, inclui obrigatoriamente no final a linha do "comboio" de dados original correspondente, para servir de referência técnica.
    
    Sê direto, apresenta listas claras e extrai os valores exatos gerados. Não assumas fundamentais da empresa.
    """
    
    prompt_completo = f"{prompt_sistema}\n\nAqui estão os ativos enviados pelo Excel:\n{dados_mercado}"
    
    # NOVAS CONFIGURAÇÕES DE PROTEÇÃO
    tentativas = 5       # Aumentamos para 5 tentativas
    espera_base = 15     # Segundos base

    for tentativa in range(tentativas):
        try:
            resposta = client.models.generate_content(
                model='gemini-3.5-flash',  # Mantém o teu modelo
                contents=prompt_completo
            )
            return resposta.text
            
        except Exception as e:
            erro_str = str(e)
            print(f"Tentativa {tentativa + 1} falhou: {erro_str}")
            
            if tentativa < tentativas - 1:
                # Se for erro 503 (Servidores cheios) ou 429 (Too many requests)
                if "503" in erro_str or "UNAVAILABLE" in erro_str or "429" in erro_str:
                    # Backoff Exponencial: 15s -> 30s -> 60s -> 120s
                    tempo_espera = espera_base * (2 ** tentativa)
                    print(f"Servidores da Google sobrecarregados. A aguardar {tempo_espera} segundos antes de tentar novamente...")
                    time.sleep(tempo_espera)
                else:
                    # Se for um erro crítico (ex: API key inválida), não vale a pena esperar
                    print("Erro não relacionado com tráfego. A abortar imediatamente.")
                    raise e
            else:
                print("Todas as tentativas falharam. Os servidores não recuperaram a tempo.")
                raise e

# ==========================================
# 4. ENVIAR O RELATÓRIO DE VOLTA POR EMAIL
# ==========================================
def enviar_email_resposta(relatorio_texto):
    print("A enviar o relatório tático por email...")
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_USER # Envia para ti próprio
        msg['Subject'] = "Relatório Tático Diário - Concluído"
        
        msg.attach(MIMEText(relatorio_texto, 'plain', 'utf-8'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
        server.quit()
        print("Email de resposta enviado com sucesso!")
    except Exception as e:
        print(f"Erro ao enviar o email de resposta: {e}")

# ==========================================
# 5. EXECUÇÃO DO AGENTE
# ==========================================
if __name__ == "__main__":
    conteudo_email = extrair_dados_do_email()
    
    if conteudo_email:
        analise_final = analisar_com_ia(conteudo_email)
        
        # Imprime no terminal (caso corra localmente)
        print("\n" + "="*50)
        print("RELATÓRIO TÁTICO DIÁRIO")
        print("="*50)
        print(analise_final)
        
        # Envia também por email
        enviar_email_resposta(analise_final)
