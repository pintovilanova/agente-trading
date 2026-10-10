# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - AGENTE ORQUESTRADOR IA (GEMINI)
# ===================================================================
# Descrição Geral:
# Este script atua como o "Cérebro Analítico" e auditor final do sistema. 
# O seu papel é extrair os dados processados pelo motor matemático (seja 
# por ficheiro local ou via IMAP/Email), submetê-los a um modelo de IA de 
# alta performance (Google Gemini) com prompts estritos de gestão de risco, 
# e reenviar o relatório tático final pronto para leitura e tomada de decisão.
#
# Pilares Técnicos e Arquitetura:
# 1. Travas de Segurança e Calendário:
#    - Trava de Fim de Semana: Interrompe a execução aos sábados e domingos.
# 2. Extração Inteligente com Fallback (Local + IMAP):
#    - Deteção automática do mercado em análise com base nos ficheiros 
#      de texto disponíveis (Europa, Pânico, Connors, Earnings, Carver ou VCP Breakouts).
# 3. Mecanismo de Alta Disponibilidade e Fallback de Modelos de IA:
#    - Sistema de re-tentativas com espera exponencial (Backoff) para lidar 
#      com restrições de API ou erros de indisponibilidade (503 / 429).
#    - Mudança automática para modelos de contingência (gemini-3.8-flash) 
#      caso o modelo principal esgote a quota.
# 4. Distribuição do Relatório Final:
#    - Envio automatizado do relatório de auditoria tática por email, formatado 
#      com títulos dinâmicos e bandeiras de risco de acordo com o mercado/estratégia.
# ===================================================================
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
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O mercado está fechado. O Agente vai descansar.")
    #sys.exit(0)

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
# 2. EXTRAÇÃO INTELIGENTE (Local + Fallback IMAP) - ATUALIZADA
# ==========================================
def extrair_dados_do_market():
    # Verifica qual o ficheiro de comboio disponível na pasta com prioridade exata
    if os.path.exists("comboio_europa.txt"):
        ficheiro = "comboio_europa.txt"
        assunto_alvo = "tradingRelatorioIA Europa"
        tag_mercado = "EUROPA"
    elif os.path.exists("comboio_reversao_temp.txt"):
        ficheiro = "comboio_reversao_temp.txt"
        assunto_alvo = "tradingRelatorioIA US - PÂNICO E REVERSÃO"
        tag_mercado = "US-PANICO"
    elif os.path.exists("comboio_connors_temp.txt"):
        ficheiro = "comboio_connors_temp.txt"
        assunto_alvo = "tradingRelatorioIA US - CONNORS-CHAN"
        tag_mercado = "US-CONNORS"
    elif os.path.exists("comboio_earnings_temp.txt"):
        ficheiro = "comboio_earnings_temp.txt"
        assunto_alvo = "tradingRelatorioIA US - EARNINGS DRIFT"
        tag_mercado = "US-EARNINGS"
    elif os.path.exists("comboio_carver_temp.txt"):
        ficheiro = "comboio_carver_temp.txt"
        assunto_alvo = "tradingRelatorioIA US - FAST TREND CARVER"
        tag_mercado = "US-CARVER"
    elif os.path.exists("comboio_vcp_temp.txt"):
        ficheiro = "comboio_vcp_temp.txt"
        assunto_alvo = "tradingRelatorioIA US - VCP BREAKOUT SQUEEZE"
        tag_mercado = "US-VCP"
    elif os.path.exists("comboio_rs_temp.txt"):
        ficheiro = "comboio_rs_temp.txt"
        assunto_alvo = "tradingRelatorioIA US - RS SCORE"
        tag_mercado = "US-RS-SCORE"
    else:
        ficheiro = "comboio_temp.txt"
        assunto_alvo = "tradingRelatorioIA US"
        tag_mercado = "US"
    
    print(f"A processar mercado/estratégia: {tag_mercado} (Ficheiro: {ficheiro})...")

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

    modelo_atual = 'gemini-3.6-flash'

    for tentativa in range(tentativas):
        try:
            if tentativa == 2:
                print(f"[AVISO] O modelo {modelo_atual} está indisponível ou sem cota.")
                print("[TÁTICA] A mudar o motor para o Fallback 'gemini-3.8-flash'...")
                modelo_atual = 'gemini-3.8-flash'

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
                        
                    if "429" in erro_str and tentativa < 2:
                        tempo_espera = 5

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
    if tag_mercado == "EUROPA":
        assunto_email = "🇪🇺🎯 IA Predador: Relatório Tático EUROPA 🛡️"
    elif tag_mercado == "US-PANICO":
        assunto_email = "🚨 IA Predador: Relatório Pânico e Reversão ⚡"
    elif tag_mercado == "US-CONNORS":
        assunto_email = "🧲 IA Predador: Relatório Connors-Chan 🏹"
    elif tag_mercado == "US-EARNINGS":
        assunto_email = "📊 IA Predador: Relatório Earnings Drift 🚀"
    elif tag_mercado == "US-CARVER":
        assunto_email = "🏄‍♂️ IA Predador: Relatório Carver Fast Trend 🚀"
    elif tag_mercado == "US-VCP":
        assunto_email = "🗜️ IA Predador: Relatório VCP Breakout Squeeze 🎯"
    elif tag_mercado == "US-RS-SCORE":
        assunto_email = "🧭 IA Predador: Relatório de Força Relativa e Setores (RS Score) 👑"    
    else:
        assunto_email = "🦅 IA Predador: Relatório Tático WALL STREET 🗽"

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
