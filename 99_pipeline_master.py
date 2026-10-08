# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - 99. PIPELINE MESTRE UNIFICADO
# ===================================================================
# Descrição Geral:
# Este script centraliza e executa de forma sequencial todo o ecossistema 
# quantitativo da nuvem (GitHub Actions) e as respetivas auditorias IA:
# 00 - Disjuntor Macro (SPY)
# 01 - Motor V2 (Breakouts)
# 03 - Motor Mean Reversion / Pânico Profundo
# 04 - Motor Earnings Drift / PEAD
# 05 - Motor Connors-Chan / Exaustão de Curto Prazo
# 02 - Orquestrador IA Final (Auditoria Gemini e Envio de Relatório)
# ===================================================================

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

def executar_pipeline_mestre():
    print("="*60)
    print("INÍCIO DO PIPELINE MESTRE DE TRADING INSTITUCIONAL")
    print("="*60)
    
    # 0. Trava de Fim de Semana
    dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
    if dia_da_semana >= 5:
        print("[INFO] Fim de semana detetado. O mercado está fechado. Pipeline em repouso.")
        sys.exit(0)

    # 1. Executar Disjuntor Macro (Regime de Mercado / SPY)
    print("\n[PASSO 1] A verificar Regime de Mercado (Disjuntor Macro)...")
    ret_macro = os.system("python 00_motor_regime_mercado.py")
    if ret_macro != 0:
        print("[BLOQUEIO] O Disjuntor Macro interrompeu o pipeline. Condições desfavoráveis.")
        sys.exit(0)

    # 2. Executar Motor V2 (Breakouts) + Auditoria IA
    print("\n[PASSO 2] A executar Motor V2 (Breakouts)...")
    os.system("python 01_extrator_dados.py")
    print("-> A auditar Breakouts com o Agente IA...")
    os.system("python 02_agente_gemini.py")

    # 3. Executar Motor de Reversão / Pânico Profundo (03) + Auditoria IA
    print("\n[PASSO 3] A executar Motor Mean Reversion (Pânico)...")
    os.system("python 03_motor_mean_reversion.py")
    print("-> A auditar Pânico e Reversão com o Agente IA...")
    os.system("python 02_agente_gemini.py")

    # 4. Executar Motor de Earnings Drift / PEAD (04) + Auditoria IA
    print("\n[PASSO 4] A executar Motor Earnings Drift...")
    os.system("python 04_motor_earnings_drift.py")
    print("-> A auditar Earnings Drift com o Agente IA...")
    os.system("python 02_agente_gemini.py")

    # 5. Executar Motor Connors-Chan / Exaustão de Curto Prazo (05) + Auditoria IA
    print("\n[PASSO 5] A executar Motor Connors-Chan...")
    os.system("python 05_motor_reversao_chan.py")
    print("-> A auditar Connors-Chan com o Agente IA...")
    os.system("python 02_agente_gemini.py")

    print("\n" + "="*60)
    print("PIPELINE MESTRE CONCLUÍDO COM SUCESSO!")
    print("="*60)

if __name__ == "__main__":
    executar_pipeline_mestre()
