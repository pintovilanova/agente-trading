import os
import sys
import time
import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from zoneinfo import ZoneInfo
import warnings
warnings.filterwarnings("ignore")

# Importação da biblioteca Gemini com suporte a nova e antiga API
try:
    from google import genai
    USE_NEW_GENAI = True
except ImportError:
    import google.generativeai as genai
    USE_NEW_GENAI = False

# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - AGENTE IA ORQUESTRADOR (PIPELINE)
# ===================================================================

# 1. CREDENCIAIS (GitHub Secrets)
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
IMAP_SERVER = "imap.gmail.com"

if not GEMINI_API_KEY:
    print("[ERRO] GEMINI_API_KEY não encontrada nas variáveis de ambiente.")
    sys.exit(1)

# Função Auxiliar de Envio de Email (SMTP)
def enviar_email(assunto, corpo_texto):
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] EMAIL_USER ou EMAIL_PASS não definidos. Email não enviado.")
        return False
        
    max_tentativas = 3
    for tentativa in range(max_tentativas):
        try:
            msg = MIMEMultipart()
            msg['From'] = EMAIL_USER
            msg['To'] = EMAIL_USER
            msg['Subject'] = assunto
            msg.attach(MIMEText(corpo_texto, 'plain', 'utf-8'))
            
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
            server.quit()
            
            print(f"[SUCESSO] Email '{assunto}' enviado com sucesso na tentativa {tentativa + 1}!")
            return True
        except Exception as e:
            print(f"[ERRO] Falha ao enviar email (tentativa {tentativa + 1} de {max_tentativas}): {e}")
            if tentativa < max_tentativas - 1:
                time.sleep(5)
    return False

# Função Auxiliar para Ler o Último Email de Backup no Gmail (IMAP)
def obter_conteudo_ultimo_email_backup():
    if not EMAIL_USER or not EMAIL_PASS:
        print("[ERRO] EMAIL_USER ou EMAIL_PASS não definidos nas variáveis de ambiente.")
        return None
    try:
        print("\n[IMAP] A ligar ao servidor de e-mail para procurar o último backup...")
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")

        status, data = mail.search(None, 'SUBJECT "DADOS BRUTOS PARA IA"')
        if status != "OK" or not data[0]:
            print("[IMAP] Nenhum e-mail de backup encontrado na caixa de entrada.")
            mail.logout()
            return None

        email_ids = data[0].split()
        ultimo_id = email_ids[-1]

        print(f"[IMAP] E-mail de backup mais recente encontrado (ID: {ultimo_id.decode()}). A extrair dados...")

        status, msg_data = mail.fetch(ultimo_id, "(RFC822)")
        if status != "OK":
            print("[IMAP] Erro ao carregar a mensagem de e-mail.")
            mail.logout()
            return None

        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        content_disposition = str(part.get("Content-Disposition"))
                        if content_type == "text/plain" and "attachment" not in content_disposition:
                            payload = part.get_payload(decode=True)
                            if payload:
                                body = payload.decode('utf-8', errors='ignore')
                                break
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body = payload.decode('utf-8', errors='ignore')
                
                mail.logout()
                return body.strip()

        mail.logout()
    except Exception as e:
        print(f"[ERRO IMAP] Falha ao ler e-mail de backup: {e}")
    return None

# ===================================================================
# 2. DEFINIR FICHEIROS ALVO DOS MOTORES (ATUALIZADO COM MOTOR 15 E 16)
# ===================================================================
ficheiros_alvo = [
    "comboio_temp.txt",             # Extrator US
    "comboio_europa.txt",           # Extrator Europa
    "comboio_vcp_temp.txt",         # Motor 07 (VCP Breakout)
    "comboio_reversao_temp.txt",    # Motor 03 (Pânico)
    "comboio_earnings_temp.txt",    # Motor 04 (PEAD)
    "comboio_connors_temp.txt",     # Motor 05 (REVERSAO)
    "comboio_carver_temp.txt",      # Motor 06 (Fast Trend Carver)
    "comboio_holygrail_temp.txt",   # Motor 10 (Holy Grail Pullbacks)
    "comboio_rotacao_temp.txt",     # Motor 11 (Rotação Setorial)    
    "comboio_correlacao_temp.txt",  # Motor 12 (Correlação de Risco)
    "comboio_exaustao_temp.txt",    # Motor 13 (Exaustão Climática)
    "comboio_sazonalidade_temp.txt",# Motor 14 (Sazonalidade)
    "comboio_harvest_temp.txt",     # Motor 15 (Profit Harvest & Rebalancing)
    "comboio_vix_temp.txt"          # Motor 16 (Volatility Regime & VIX)
]

conteudo_bruto_total = ""
veio_do_email = False

print("A procurar relatórios dos extratores e motores na máquina virtual...")

ficheiros_existentes = [f for f in ficheiros_alvo if os.path.exists(f)]

if not ficheiros_existentes:
    print("\n[AVISO] Nenhum ficheiro 'comboio' encontrado no disco da máquina virtual.")
    print("A tentar recuperar os dados do último e-mail de backup via IMAP...")
    
    conteudo_backup = obter_conteudo_ultimo_email_backup()
    if conteudo_backup:
        print("[SUCESSO] Dados brutos recuperados do e-mail de backup com sucesso!")
        conteudo_bruto_total = conteudo_backup
        veio_do_email = True
    else:
        print("[ERRO CRÍTICO] Não existem ficheiros no disco e não foi possível obter o e-mail de backup.")
        sys.exit(1)
else:
    for ficheiro in ficheiros_alvo:
        if os.path.exists(ficheiro):
            with open(ficheiro, "r", encoding="utf-8") as f:
                dados = f.read().strip()
                
                conteudo_bruto_total += f"\n\n==================================\n"
                conteudo_bruto_total += f"📁 FONTE: {ficheiro}\n"
                conteudo_bruto_total += f"==================================\n"
                
                if dados and "Nenhum ativo" not in dados and "[SEM OPORTUNIDADES]" not in dados:
                    conteudo_bruto_total += f"{dados}\n"
                    print(f"[ENCONTRADO] Dados detetados no {ficheiro}.")
                else:
                    conteudo_bruto_total += "[SEM SINAIS OU OPORTUNIDADES PARA ESTA ESTRATÉGIA HOJE]\n"
                    print(f"[VAZIO] {ficheiro} lido, adicionado como sem sinais ao relatório.")
        else:
            conteudo_bruto_total += f"\n\n==================================\n"
            conteudo_bruto_total += f"📁 FONTE: {ficheiro}\n"
            conteudo_bruto_total += f"==================================\n"
            
            # TRATAMENTO ESPECIAL BLINDADO PARA MOTORES EM MODO SILÊNCIO
            if ficheiro == "comboio_exaustao_temp.txt":
                conteudo_bruto_total += "✅ Nenhuma anomalia parabólica detetada. As posições ativas estão saudáveis e dentro dos parâmetros normais. (Modo Silêncio ativo).\n"
                print(f"[SILÊNCIO] {ficheiro} não encontrado (Motor de Exaustão sem alertas, posições saudáveis).")
            elif ficheiro == "comboio_harvest_temp.txt":
                conteudo_bruto_total += "✅ Nenhuma posição atingiu o patamar de 2R para colheita de lucro hoje. Gestão normal. (Modo Silêncio ativo).\n"
                print(f"[SILÊNCIO] {ficheiro} não encontrado (Motor 15 sem colheitas ativas).")
            elif ficheiro == "comboio_vix_temp.txt":
                conteudo_bruto_total += "📊 VIX em modo padrão/não disponível. Assumir Lote de 100% para novas entradas. (Modo Silêncio ativo).\n"
                print(f"[SILÊNCIO] {ficheiro} não encontrado (Motor 16 em fallback para 100%).")
            else:
                conteudo_bruto_total += "[ERRO: FICHEIRO NÃO ENCONTRADO - MOTOR PODE TER FALHADO]\n"
                print(f"[FALTA] {ficheiro} não encontrado.")

if not conteudo_bruto_total.strip():
    print("\n[INFO] Nenhum dado gerado. A pipeline termina de forma silenciosa.")
    sys.exit(0)

data_hoje = datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')

if not veio_do_email:
    assunto_backup = f"tradingRelatorioIA - 📦 DADOS BRUTOS PARA IA / BACKUP ({data_hoje})"
    print("\nA enviar dados brutos consolidados para o Email de Backup...")
    enviar_email(assunto_backup, conteudo_bruto_total)

# ===================================================================
# PROMPT DE ORQUESTRAÇÃO COM TABELA DE SÍNTESE OBRIGATÓRIA
# ===================================================================
prompt_orquestrador = f"""
És o Analista Quantitativo Principal (Agente Orquestrador).
Abaixo estão os relatórios em bruto e os dados gerados dinamicamente pelos Extratores de Mercado (US e Europa) e pelos vários Motores de Estratégia no fecho do mercado de hoje, incluindo o Motor 15 (Profit Harvest & Rebalancing) e o Motor 16 (Regime de Volatilidade VIX).

A tua missão é ler integralmente este conteúdo, processar todos os ativos e compilar um ÚNICO relatório consolidado, limpo, detalhado e altamente profissional para o Gestor de Conta aprovar na corretora.

🚨 REGRAS ESTRITAS DE ESTRUTURA E FECHO 🚨

1. REGIME DE VOLATILIDADE VIX (MOTOR 16): Lê a diretriz do Motor 16 e indica explicitamente no topo do relatório o Regime do VIX. Aplica a percentagem de lote indicada pelo Motor 16 (100%, 75%, 50% ou 0%) ao calcular o tamanho e alocação de TODAS as novas sugestões de entrada.
2. ZERO CRIATIVIDADE DE DADOS: Não inventes preços, tickers, stops ou tamanhos de posição. Utiliza unicamente e na íntegra os dados fornecidos.
3. VETO DE SOBREPOSIÇÃO: Posições ativas na carteira (com 'PosicaoAtiva: SIM') NÃO PODEM ter novas ordens de compra sugeridas.
4. TABELA FINAL OBRIGATÓRIA (SÍNTESE DE ORDENS):
   É ESTRITAMENTE OBRIGATÓRIO terminar o relatório com uma secção final intitulada "## 12. SÍNTESE DE ORDENS PARA APROVAÇÃO DO GESTOR DE CONTA" contendo uma tabela Markdown formatada exatamente com esta estrutura:

   | Ticker | Estratégia | Tipo de Ordem | Preço Entrada | Stop Loss | Take Profit | Qtd | Alocação Est. | Notas Táticas |
   | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |

   - Inclui TODAS as ordens de colheita parcial de lucro a 2R (Profit Harvest) geradas pelo Motor 15 no topo da tabela.
   - Inclui TODAS as ações ativas em carteira que exijam fecho ou ajuste de stop (ex: fecho por Earnings).
   - Inclui TODAS as novas ordens aprovadas ajustadas pelo Lote Máximo do VIX (Motor 16).
   - Respeita rigorosamente a moeda de cada ativo (USD ou EUR).

DADOS RECOLHIDOS HOJE NOS FICHEIROS:
{conteudo_bruto_total}
"""

print("\nA enviar dados consolidados para o Gemini Auditar...")

relatorio_final = None

# Modelos recomendados e ativos pela API Gemini
modelos_para_testar = ['gemini-2.5-flash', 'gemini-3.8-flash', 'gemini-3.6-flash', 'gemini-1.5-flash']

for mod in modelos_para_testar:
    if relatorio_final:
        break
        
    print(f"\nA testar modelo Gemini: {mod}...")
    
    # Tenta até 3 vezes por modelo para superar erros 503 de alta procura
    for tentativa in range(1, 4):
        try:
            if USE_NEW_GENAI:
                client = genai.Client(api_key=GEMINI_API_KEY)
                response = client.models.generate_content(
                    model=mod,
                    contents=prompt_orquestrador,
                )
                relatorio_final = response.text
            else:
                genai.configure(api_key=GEMINI_API_KEY)
                modelo_ia = genai.GenerativeModel(mod)
                resposta = modelo_ia.generate_content(prompt_orquestrador)
                relatorio_final = resposta.text
                
            print(f"[SUCESSO] Relatório mestre gerado pela IA com o modelo {mod}!")
            break
        except Exception as e:
            err_msg = str(e)
            print(f"[AVISO] Tentativa {tentativa} no modelo {mod} falhou: {err_msg}")
            if "503" in err_msg or "UNAVAILABLE" in err_msg:
                print("Servidor temporariamente ocupado (503). A aguardar 4 segundos antes de tentar novamente...")
                time.sleep(4)
            else:
                break

if not relatorio_final:
    print("\n[ALERTA DE IA] Não foi possível obter resposta de nenhum modelo Gemini.")
    print("[INFO] A pipeline termina sem crash. O e-mail com os DADOS BRUTOS já está disponível para uso manual.")
    
    assunto_erro = f"tradingRelatorioIA - ⚠️ AVISO: FALHA NA IA ({data_hoje})"
    corpo_erro = f"""Ocorreu um erro ao comunicar com a API do Gemini (Alta procura temporária ou limite de quota).

Por favor, utiliza o e-mail de backup enviado anteriormente com o assunto '[DADOS BRUTOS PARA IA]' e cola o conteúdo no ChatGPT / Claude / Gemini Web para obter o relatório formatado."""
    
    enviar_email(assunto_erro, corpo_erro)
    sys.exit(0)

# ===================================================================
# 6. ENVIAR EMAIL DO RELATÓRIO FINAL DA IA
# ===================================================================
print("\nA preparar envio do Relatório Mestre Formatado pela IA...")
assunto_final = f"tradingRelatorioIA Global - 🤖 RELATÓRIO MESTRE ({data_hoje})"
enviar_email(assunto_final, relatorio_final)
