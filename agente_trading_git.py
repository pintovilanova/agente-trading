import os
import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google import genai
import time

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

# Configurar o cliente da IA
client = genai.Client(api_key=GEMINI_API_KEY)

# ==========================================
# 2. EXTRAÇÃO INTELIGENTE (Local + Fallback IMAP)
# ==========================================
def extrair_dados_do_email():
    # Abordagem Híbrida: Tenta ler primeiro do ficheiro gerado pelo Passo 1 (Ideal para GitHub Actions)
    if os.path.exists("comboio_temp.txt"):
        print("A carregar os dados localmente a partir de 'comboio_temp.txt'...")
        try:
            with open("comboio_temp.txt", "r", encoding="utf-8") as f:
                conteudo = f.read()
                print("[SUCESSO] Dados locais carregados com sucesso.")
                return conteudo
        except Exception as e:
            print(f"Erro ao ler o ficheiro local: {e}. A tentar via IMAP...")

    # Fallback: Se o ficheiro não existir (ex: execução manual no PC), liga-se ao IMAP
    print("A ligar à caixa de correio via IMAP para ler os dados...")
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")
        
        # Pesquisa com UTF-8 para lidar com acentos no português
        status, messages = mail.search("UTF-8", f'(SUBJECT "{ASSUNTO_DO_EMAIL}")')
        
        email_ids = messages[0].split()
        if not email_ids:
            print("Nenhum email encontrado com esse assunto.")
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
        print(f"Erro ao ler o email via IMAP: {e}")
        return None

# ==========================================
# 3. O CÉREBRO: INVOCAR A IA COM O PROMPT
# ==========================================
def analisar_com_ia(dados_mercado):
    print("A enviar lista para análise tática do Gemini...")
    
    prompt_sistema = """
    És um assistente de trading sistemático e mecânico. O utilizador procura preservar capital e usa um rácio de risco de 1.2x.
    
    Abaixo encontrarás as instruções operacionais específicas fornecidas, seguidas pelos dados do comboio de ativos de mercado. Cumpre rigorosamente todas as diretrizes indicadas.
    """
    
    prompt_completo = f"{prompt_sistema}\n\nAqui estão os ativos analíticos:\n{dados_mercado}"
    
    # Sistema de Retry (Blindagem contra Picos de Tráfego 503)
    tentativas = 10
    espera_base = 15
    espera_maxima = 300

    for tentativa in range(tentativas):
        try:
            resposta = client.models.generate_content(
                model='gemini-3.8-flash', # Podes ajustar para o modelo que preferires
                contents=prompt_completo
            )
            return resposta.text
            
        except Exception as e:
            erro_str = str(e)
            print(f"Tentativa {tentativa + 1} falhou: {erro_str}")
            
            if tentativa < tentativas - 1:
                if "503" in erro_str or "UNAVAILABLE" in erro_str or "429" in erro_str:
                    tempo_espera = espera_base * (2 ** tentativa)
                    if tempo_espera > espera_maxima:
                        tempo_espera = espera_maxima
                        
                    print(f"Bloqueio de API. A aguardar {tempo_espera} segundos...")
                    time.sleep(tempo_espera)
                else:
                    print("Erro estrutural. A abortar imediatamente.")
                    raise e
            else:
                print("Todas as tentativas esgotadas. Falha crítica.")
                raise e

# ==========================================
# 4. ENVIAR O RELATÓRIO DE VOLTA POR EMAIL
# ==========================================
def enviar_email_resposta(relatorio_texto):
    print("A enviar o relatório tático por email...")
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_USER
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
    conteudo_dados = extrair_dados_do_email()
    
    if conteudo_dados:
        analise_final = analisar_com_ia(conteudo_dados)
        
        print("\n" + "="*50)
        print("RELATÓRIO TÁTICO DIÁRIO")
        print("="*50)
        print(analise_final)
        
        enviar_email_resposta(analise_final)
