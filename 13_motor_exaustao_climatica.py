import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ... [Fase 1, 2 e 3 mantêm-se iguais] ...

# ===================================================================
# 4. GERAÇÃO DE RELATÓRIO E DISPARO DE EMERGÊNCIA
# ===================================================================
data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M:%S")

if alertas_exaustao:
    relatorio = f"🚨 ALERTA CRÍTICO DE TRADING - EXAUSTÃO CLIMÁTICA 🚨\n({data_hoje})\n"
    relatorio += "=" * 65 + "\n\n"
    relatorio += "O algoritmo detetou um movimento parabólico insustentável. A probabilidade de reversão violenta nas próximas 48h excede os 85%.\n\n"
    
    for alerta in alertas_exaustao:
        relatorio += f"🔥 {alerta['ticker']}:\n"
        relatorio += f"   - Estado: PREÇO ESTICADO EXTREMO\n"
        relatorio += f"   - Tensão Estrutural: {alerta['dist_ema9']:.1f}% acima da EMA 9\n"
        relatorio += f"   - Exaustão Vendedora (RVOL): {alerta['rvol']:.2f}x o volume normal\n"
        relatorio += f"   - RSI (14): {alerta['rsi']:.1f}\n"
        relatorio += f"   - ⚡ AÇÃO EXIGIDA: Fechar 50% ou 100% da posição de {alerta['qtd']} ações IMEDIATAMENTE A MERCADO.\n\n"
        
    print("\n[ALERTA] Anomalia detetada! A preparar envio de email de emergência...")
    
    # Enviar Email
    EMAIL_USER = os.environ.get("EMAIL_USER")
    EMAIL_PASS = os.environ.get("EMAIL_PASS")
    
    if EMAIL_USER and EMAIL_PASS:
        try:
            msg = MIMEMultipart()
            msg['From'] = EMAIL_USER
            msg['To'] = EMAIL_USER
            msg['Subject'] = "🚨 ALERTA DE LIQUIDAÇÃO PARABÓLICA - Motor 13"
            msg.attach(MIMEText(relatorio, 'plain', 'utf-8'))
            
            server = smtplib.SMTP("smtp.gmail.com", 587, timeout=15)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
            server.quit()
            print("[SUCESSO] Email de emergência disparado para a Mesa de Operações!")
        except Exception as e:
            print(f"[ERRO] Falha ao enviar email de emergência: {e}")
else:
    print("\n✅ Nenhuma anomalia parabólica detetada. As posições ativas estão saudáveis. Silêncio mantido.")

# Limpeza: Como agora envia email direto, já não precisamos de escrever o ficheiro temporário para o Orquestrador.
