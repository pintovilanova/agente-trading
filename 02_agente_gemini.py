import os
import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google import genai
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import sys

# ===================================================================
# 0.1 TRAVA DE FIM DE SEMANA (Não corre ao Sábado e Domingo)
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()

# ATIVADO: Se for sábado (5) ou domingo (6), o script para aqui.
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O mercado está fechado. O Agente vai descansar.")
    sys.exit(0)

# ==========================================
# 1. CONFIGURAÇÕES (Lidas do GitHub Secrets)
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")

IMAP_SERVER = "imap.gmail.com"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# Configurar o cliente da IA
client = genai.Client(api_key=GEMINI_API_KEY)

# ==========================================
# 2. EXTRAÇÃO INTELIGENTE (Local + Fallback IMAP)
# ==========================================
def extrair_dados_do_market():
    if os.path.exists("comboio_europa.txt"):
        ficheiro = "comboio_europa.txt"
        assunto_alvo = "tradingRelatorioIA Europa" # O que a IA vai procurar na caixa de entrada
        tag_mercado = "EUROPA"
    else:
        ficheiro = "comboio_temp.txt"
        assunto_alvo = "tradingRelatorioIA US" # O que a IA vai procurar na caixa de entrada
        tag_mercado = "US"

    print(f"A processar mercado: {tag_mercado} (Ficheiro: {ficheiro})...")

    if os.path.exists(ficheiro):
        print(f"A carregar os dados localmente a partir de '{ficheiro}'...")
        try:
            with open(ficheiro, "r", encoding="utf-8") as f:
                conteudo = f.read()
                print("[SUCESSO] Dados locais carregados com sucesso.")
                return conteudo, tag_mercado
        except Exception as e:
            print(f"Erro ao ler o ficheiro local: {e}. A tentar via IMAP...")

    print(f"A ligar à caixa de correio via IMAP para procurar por: '{assunto_alvo}'...")
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")
        
        status, messages = mail.search("UTF-8", f'(SUBJECT "{assunto_alvo}")')
        
        email_ids = messages[0].split()
        if not email_ids:
            print("Nenhum email encontrado com esse assunto.")
            return None, tag_mercado
            
        ultimo_id = email_ids[-1]
        res, msg = mail.fetch(ultimo_id, "(RFC822)")
        
        for response in msg:
            if isinstance(response, tuple):
                msg_formatada = email.message_from_bytes(response[1])
                
                if msg_formatada.is_multipart():
                    for part in msg_formatada.walk():
                        if part.get_content_type() == "text/plain":
                            return part.get_payload(decode=True).decode(), tag_mercado
                else:
                    return msg_formatada.get_payload(decode=True).decode(), tag_mercado
                    
    except Exception as e:
        print(f"Erro ao ler o email via IMAP: {e}")
        return None, tag_mercado

    return None, tag_mercado

# ==========================================
# 3. O CÉREBRO: INVOCAR A IA COM O PROMPT PREDADOR
# ==========================================
def analisar_com_ia(dados_mercado):
    print("A enviar lista para análise tática do Gemini...")
    prompt_completo = f"""{dados_mercado}"""
    
    tentativas = 10
    espera_base = 15
    espera_maxima = 300

    # Começa com o teu modelo de eleição
    modelo_atual = 'gemini-3.6-flash'

    for tentativa in range(tentativas):
        try:
            # Estratégia de Fallback: Se falhar 2 vezes seguidas, salta para o modelo de alta disponibilidade
            if tentativa == 2:
                print(f"[AVISO] O modelo {modelo_atual} está indisponível ou sem cota (limite 20/dia).")
                print("[TÁTICA] A mudar o motor para o Fallback 'gemini-3.8-flash' para garantir o relatório...")
                modelo_atual = 'gemini-3.8-flash'  # Podes usar 'gemini-3.0-flash' se o 2.5 também der 404

            print(f"A tentar gerar relatório com o modelo: {modelo_atual}...")
            resposta = client.models.generate_content(
                model=modelo_atual,
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
                        
                    # Se deu erro 429 na primeira ou segunda tentativa, não vale a pena esperar muito, força o ciclo a avançar para o Fallback
                    if "429" in erro_str and tentativa < 2:
                        tempo_espera = 5
                        print("Cota excedida no modelo VIP. A avançar rápido para o modelo de contingência...")

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
def enviar_email_resposta(relatorio_texto, tag_mercado):
    # Aqui sim, definimos o assunto "bonito" que te vai aparecer no telemóvel/computador
    if tag_mercado == "EUROPA":
        assunto_email = "🇪🇺 IA Predador: Relatório Tático EUROPA"
    else:
        assunto_email = "🇺🇸 IA Predador: Relatório Tático WALL STREET"

    print(f"A enviar o relatório tático final para ti (Assunto: {assunto_email})...")
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_USER
        msg['Subject'] = assunto_email
        
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
    conteudo_dados, tag_mercado = extrair_dados_do_market()
    
    if conteudo_dados:
        analise_final = analisar_com_ia(conteudo_dados)
        
        print("\n" + "="*50)
        print(f"RELATÓRIO TÁTICO DIÁRIO - PREDADOR ({tag_mercado})")
        print("="*50)
        print(analise_final)
        
        enviar_email_resposta(analise_final, tag_mercado)
