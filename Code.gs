function ANALISE_TACTICA_AUTO(ticker) {
  
  // 1. Valida se o Ticker é válido
  if (!ticker || ticker === "" || ticker.toString().indexOf("#") === 0) {
    return [["Aguardando Ticker...", "", "", "", "", "", "", "", "", "", "", "", "", "",""]];
  }

  // ===================================================================
  // LEITURA DINÂMICA DA FOLHA "CONFIGS"
  // ===================================================================
  var configs = {};
  var riscoMaximoDolares = 25.00;
  var racioTakeProfitGlobal = null; 
  var multiplicadorTrailing = null;

  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    if (ss) {
      var sheetConfigs = ss.getSheetByName("Configs");
      if (sheetConfigs) {
        var dadosConfigs = sheetConfigs.getDataRange().getValues();
        
        for (var i = 0; i < dadosConfigs.length; i++) {
          var chave = dadosConfigs[i][0] ? dadosConfigs[i][0].toString().trim().toLowerCase() : "";
          var valor = dadosConfigs[i][1];

          if ((valor === "" || valor === undefined) && chave.indexOf(":") !== -1) {
            var partes = chave.split(":");
            chave = partes[0].trim().toLowerCase();
            valor = partes[1].trim();
          } else if ((valor === "" || valor === undefined) && chave.indexOf("=") !== -1) {
            var partes = chave.split("=");
            chave = partes[0].trim().toLowerCase();
            valor = partes[1].trim();
          }

          if (chave !== "") {
            configs[chave] = valor;
          }
        }

        for (var k in configs) {
          if (k.indexOf("risco") !== -1) {
            var numLido = parseFloat(configs[k]);
            if (!isNaN(numLido) && numLido > 0) {
              riscoMaximoDolares = numLido;
            }
          }
          if (k.indexOf("trailing") !== -1) {
            var numLidoTS = parseFloat(configs[k]);
            if (!isNaN(numLidoTS) && numLidoTS > 0) {
              multiplicadorTrailing = numLidoTS;
            }
          }
        }
      }
    }
  } catch (e) {}

  // ===================================================================
  // BUSCA DINÂMICA DO STOP ATUAL NO DIÁRIO DE BORDO
  // ===================================================================
  var trailingAnterior = 0;
  
  try {
    var ss2 = SpreadsheetApp.getActiveSpreadsheet();
    if (ss2) {
      var sheetDiario = ss2.getSheetByName("Diario de Bordo") || ss2.getSheetByName("Diário de Bordo") || ss2.getSheetByName("2026 Trading"); 
      if (sheetDiario) {
        var dadosDiario = sheetDiario.getDataRange().getValues();
        
        for (var i = dadosDiario.length - 1; i >= 0; i--) {
          var linha = dadosDiario[i];
          var tickerLinha = linha[1];  
          var statusLinha = linha[22]; 
          
          if (tickerLinha && tickerLinha.toString().trim().toUpperCase() === ticker.toString().trim().toUpperCase()) {
            if (statusLinha && statusLinha.toString().trim().toUpperCase() === "ATIVA") {
              var stopAtualizado = parseFloat(linha[24]);  
              if (!isNaN(stopAtualizado) && stopAtualizado > 0) {
                 trailingAnterior = stopAtualizado;
              }
              break; 
            }
          }
        }
      }
    }
  } catch (e) {}

  // ===================================================================
  // INTEGRAÇÃO COM A API E CÁLCULO DE SINAIS
  // ===================================================================
  var apiKeys = [
    "26d40a7e4a474816bbda2b66639e1f83", 
    "2f5ab27e4dec4858b4f7b9b17f11ea37", 
    "909825477aa842a79067ca21edbb9108", 
    "b94570bd058c4129ab21931218c4add5", 
    "60c437d305ee400c8e49e04f01404735", 
    "29566e5809d94c509ca92e82d3db3cda", 
    "4fb93daab0054614a0f659c2bbb6bfed", 
    "eaff0f783fd2444f8f879f4b915d5053" 
  ];
  
  var validarTendenciaSPY = true; 

  for (var k = 0; k < apiKeys.length; k++) {
    var apiKey = apiKeys[k];
    
    try {
      if (validarTendenciaSPY) {
        var urlSPY = "https://api.twelvedata.com/time_series?symbol=SPY&interval=1day&outputsize=200&apikey=" + apiKey;
        var resSPY = UrlFetchApp.fetch(urlSPY, {"muteHttpExceptions": true});
        
        if (resSPY.getResponseCode() === 200) {
          var dSPY = JSON.parse(resSPY.getContentText());
          if (dSPY.status === "error") continue; 
          
          if (dSPY.values && dSPY.values.length >= 200) {
            var precoSPY = parseFloat(dSPY.values[0].close);
            var precoSPYOntem = parseFloat(dSPY.values[1].close);
            var quedaSPY = ((precoSPY - precoSPYOntem) / precoSPYOntem) * 100;
            
            var somaSPY200 = 0;
            for (var j = 0; j < 200; j++) { somaSPY200 += parseFloat(dSPY.values[j].close); }
            var sma200SPY = somaSPY200 / 200;
            
            if (quedaSPY <= -1.50) return [["#BLOQUEADO_SPY_PANICO", "SPY caiu " + quedaSPY.toFixed(2) + "%", "", "", "", "", "", "", "", "", "", "", "","", ""]];
            if (precoSPY < sma200SPY) return [["#BLOQUEADO_SPY_BAIXA", "Mercado < SMA200", "", "", "", "", "", "", "", "", "", "", "","", ""]];
          }
        } else {
          continue; 
        }
      }
      
      // ===================================================================
      // NOVO: EXTRAIR SETOR E EARNINGS DIRETAMENTE DO YAHOO FINANCE
      // ===================================================================
      var setorAtivo = "Desconhecido";
      var alertaEarnings = "OK";
      
      try {
        var urlYahoo = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/" + ticker + "?modules=summaryProfile,calendarEvents";
        var resYahoo = UrlFetchApp.fetch(urlYahoo, {
          "muteHttpExceptions": true,
          "headers": { "User-Agent": "Mozilla/5.0" }
        });
        
        if (resYahoo.getResponseCode() === 200) {
          var dYahoo = JSON.parse(resYahoo.getContentText());
          if (dYahoo.quoteSummary && dYahoo.quoteSummary.result && dYahoo.quoteSummary.result.length > 0) {
            var resultYF = dYahoo.quoteSummary.result[0];
            
            // 1. Puxar Setor
            if (resultYF.summaryProfile && resultYF.summaryProfile.sector) {
              setorAtivo = resultYF.summaryProfile.sector;
            }
            
            // 2. Puxar Earnings
            if (resultYF.calendarEvents && resultYF.calendarEvents.earnings && resultYF.calendarEvents.earnings.earningsDate) {
              var rawDate = resultYF.calendarEvents.earnings.earningsDate[0].raw;
              if (rawDate) {
                var agora = new Date().getTime();
                var dataEarnings = rawDate * 1000;
                var diffDias = Math.floor((dataEarnings - agora) / (1000 * 60 * 60 * 24));
                
                if (diffDias >= 0 && diffDias <= 3) {
                  alertaEarnings = "PERIGO (em " + diffDias + " dias)";
                }
              }
            }
          }
        }
      } catch (eYahoo) {} // Se o Yahoo falhar, segue caminho com Desconhecido/OK

      // Chamadas TwelveData
      var urlVolume = "https://api.twelvedata.com/time_series?symbol=" + ticker + "&interval=1day&outputsize=25&apikey=" + apiKey;
      var urlRSI    = "https://api.twelvedata.com/rsi?symbol=" + ticker + "&interval=1day&time_period=14&apikey=" + apiKey;
      var urlADX    = "https://api.twelvedata.com/adx?symbol=" + ticker + "&interval=1day&time_period=14&apikey=" + apiKey;

      var resVol = UrlFetchApp.fetch(urlVolume, {"muteHttpExceptions": true});
      var resRSI = UrlFetchApp.fetch(urlRSI, {"muteHttpExceptions": true});
      var resADX = UrlFetchApp.fetch(urlADX, {"muteHttpExceptions": true});
      
      if (resVol.getResponseCode() === 200 && resRSI.getResponseCode() === 200 && resADX.getResponseCode() === 200) {
        var dVol = JSON.parse(resVol.getContentText());
        var dRSI = JSON.parse(resRSI.getContentText());
        var dADX = JSON.parse(resADX.getContentText());
        
        if (dVol.status === "error" || dRSI.status === "error" || dADX.status === "error") continue; 
        
        var valores = dVol.values;
        var preco = parseFloat(valores[0].close);
        
        var somaPrecos20 = 0;
        for (var i = 0; i < 20; i++) { somaPrecos20 += parseFloat(valores[i].close); }
        
        var valDistMM20 = ((preco - (somaPrecos20 / 20)) / (somaPrecos20 / 20)) * 100;
        var distMM20 = valDistMM20.toFixed(2) + "%";
        
        var momentum = (preco - parseFloat(valores[14].close)).toFixed(2);
        
        var volUltimoDia = parseFloat(valores[0].volume);
        var somaVolumes = 0;
        for (var i = 0; i < 20; i++) { somaVolumes += parseFloat(valores[i].volume); }
        var rvol1 = (volUltimoDia / (somaVolumes / 20)).toFixed(2);
        
        var somaTr = 0;
        for (var i = 0; i < 14; i++) { somaTr += (parseFloat(valores[i].high) - parseFloat(valores[i].low)); }
        var atr = parseFloat((somaTr / 14).toFixed(2));
        
        // NOVO: Cálculo ATR % (Volatilidade)
        var atrPerc = ((atr / preco) * 100).toFixed(2);
        
        var rsi = parseFloat(dRSI.values[0].rsi).toFixed(2);
        var adx = parseFloat(dADX.values[0].adx).toFixed(2);
        
        var precoAnterior = parseFloat(valores[1].close);
        var varPerc = ((preco - precoAnterior) / precoAnterior) * 100;
        
        var recomendacao = "";
        var precoEntrada = "N/A";
        var precoStop = "N/A";
        var precoTakeProfit = "N/A";
        var qtdAcoes = "N/A";
        
        var multiplicadorATR = 1.0; 
        var racioTakeProfit = 1.2; 

        var valRVOL = parseFloat(rvol1);
        var valRSI = parseFloat(rsi);
        var valADX = parseFloat(adx);
        var valMomentum = parseFloat(momentum);

        // ===================================================================
        // GUILHOTINA MATEMÁTICA V2
        // ===================================================================
        var precoCaiuHoje = preco < precoAnterior;
        var volumeDespejo = valRVOL > 1.20; 

        if ((precoCaiuHoje && volumeDespejo) || valMomentum <= 0.5) {
          recomendacao = "Observar"; 
        }
        else if (varPerc > 0 && valADX < 25) {
          recomendacao = "Aguardar Recuo";
          precoEntrada = (preco - (atr * 0.4)).toFixed(2);
          multiplicadorATR = 1.0; 
        } 
        else if (varPerc > 0 && valADX >= 30 && valRVOL >= 1.20 && valRSI >= 55.00 && valRSI <= 72.00 && valDistMM20 >= 0.00 && valDistMM20 <= 3.50 && valMomentum > 1.50) { 
          recomendacao = "Forca Consolidada";
          precoEntrada = (preco - (atr * 0.1)).toFixed(2);
          multiplicadorATR = 1.3; 
        } 
        else if (valADX >= 25 && valRVOL >= 1.00 && valRSI >= 50.00 && valRSI <= 75.00 && valDistMM20 >= -1.00 && valDistMM20 <= 4.00 && valMomentum > 0.50) {
          recomendacao = "Alerta Iminente";
          precoEntrada = (preco - (atr * 0.2)).toFixed(2); 
          multiplicadorATR = 1.2; 
        } 
        else {
          recomendacao = "Observar";
        }

        // ===================================================================
        // GESTÃO DE RISCO
        // ===================================================================
        if (recomendacao !== "Observar" && precoEntrada !== "N/A") {
          var precoStopCalc = parseFloat(precoEntrada) - (atr * multiplicadorATR);
          precoStop = precoStopCalc.toFixed(2);
          var riscoPorAcao = parseFloat(precoEntrada) - precoStopCalc;
          
          if (riscoPorAcao > 0) {
            var riscoAlocado = riscoMaximoDolares; 
            if (valRVOL >= 3.00) { riscoAlocado += (riscoMaximoDolares * 0.5); } 
            if (valADX >= 35.00) { riscoAlocado += (riscoMaximoDolares * 0.5); } 

            var tp = parseFloat(precoEntrada) + (riscoPorAcao * racioTakeProfit);
            precoTakeProfit = tp.toFixed(2);
            qtdAcoes = (riscoAlocado / riscoPorAcao).toFixed(2); 
          }
        }
        
        var precoBreakeven = "N/A";
        if (precoEntrada !== "N/A" && precoTakeProfit !== "N/A") {
          var distanciaAteTP = parseFloat(precoTakeProfit) - parseFloat(precoEntrada);
          precoBreakeven = (parseFloat(precoEntrada) + (distanciaAteTP / 2)).toFixed(2);
        }

        var multiTS = multiplicadorTrailing || 1.5; 
        var trailingCalculado = preco - (atr * multiTS); 
        var trailingFinalNum;
        
        if (trailingAnterior > 0) {
          trailingFinalNum = Math.max(trailingCalculado, trailingAnterior);
        } else {
          var pisoNovaEntrada = (precoStop !== "N/A") ? parseFloat(precoStop) : 0;
          trailingFinalNum = Math.max(trailingCalculado, pisoNovaEntrada);
        }
        var precoTrailingStop = trailingFinalNum.toFixed(2);

        var apiDateTime = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "dd/MM/yyyy HH:mm:ss");
        
        // Colocamos Setor e Earnings formatados juntamente com a Data para a IA ler 
        // sem quebrar as colunas do teu Google Sheets!
        var stringDataFinal = apiDateTime + " | Setor: " + setorAtivo + " | Earnings: " + alertaEarnings;

        // --- PREPARAÇÃO DO PROMPT DA IA NO SHEETS (100% Automatizado) ---
        var diaSemana = new Date().getDay();
        var hojeESexta = (diaSemana === 5) ? "SIM" : "NÃO";

        var promptManual = "MODO DIÁRIO ATIVO - PREDADOR DE BREAKOUTS: Avalia os seguintes ativos da minha watchlist.\n" +
          "(INFO SISTEMA - Hoje é Sexta-feira? " + hojeESexta + ")\n" +
          "Contexto: O mercado recente está armadilhado com falsos breakouts. A tua missão é PROTEGER O CAPITAL, desconfiar do motor matemático e expor ativamente o risco de cada trade, priorizando apenas os arranques com força institucional real.\n\n" +
          "Regras Operacionais Estritas de Triagem e Ataque:\n\n" +
          "1. FILTRO CÉTICO INICIAL: Analisa apenas ativos com 'Forca Consolidada' ou 'Alerta Iminente'. Se o panorama geral for fraco, REJEITA TUDO e inicia a resposta APENAS com: [MERCADO CHOPPY - FICA DE FORA HOJE].\n" +
          "2. OS 3 MELHORES ALVOS: Foca-te num máximo de 3 ativos. Se um ativo detetar EARNINGS = PERIGO, ele é sumariamente desclassificado e não pode ser recomendado.\n" +
          "3. ANÁLISE DE VULNERABILIDADE E POTENCIAL (CRÍTICO):\n" +
          "   - REGRA DA MOLA (MM20): Se 'Dist MM20' > 2.5%, alerta [AVISO: PREÇO ESTICADO - Risco de Pullback].\n" +
          "   - COMPRESSÃO (ATR vs RVOL): Se RVOL > 1.5 e Momentum sólido, marca [POTENCIAL DE COMPRESSÃO] (alta prioridade).\n" +
          "   - EXAUSTÃO: Se RSI > 70 mas Momentum < 1.0 ou RVOL < 1.3, alerta [AVISO DE EXAUSTÃO - Sem Combustível].\n" +
          "   - BARREIRAS INSTITUCIONAIS: Se Entrada ou TP estiver a <1% de um número redondo maior, alerta [PAREDE INSTITUCIONAL].\n" +
          "   - ATIVOS ERRÁTICOS: Lê 'Vol' junto ao ATR no comboio. Se Vol > 5%, alerta [ATIVO ERRÁTICO - Alta Volatilidade].\n" +
          "4. TÁTICA DE EXECUÇÃO:\n" +
          "   - GAPS DE ABERTURA: Inclui: 'Se abrir em Gap > 1% da entrada, ABORTA.'\n" +
          "   - GESTÃO DE LUCRO: Se ADX > 35, instrui: '[TENDÊNCIA EXTREMA] Ignora TP, gere pelo Trailing'. Se ADX < 30: '[TENDÊNCIA MODERADA] Respeita o TP fixo.'\n" +
          "5. RISCOS DE CALENDÁRIO E CORRELAÇÃO:\n" +
          "   - EARNINGS: Lê o campo 'Earnings' no fim da string. Se disser 'PERIGO', REJEITA o ativo imediatamente.\n" +
          "   - SEXTA-FEIRA: Lê a (INFO SISTEMA). Se for Sexta-feira ('SIM'), exige Lote Reduzido à tarde.\n" +
          "   - CORRELAÇÃO: Compara o campo 'Setor' dos ativos validados. Se 2 ou mais forem do mesmo Setor, emite '[AVISO DE CORRELAÇÃO] - Risco concentrado' e escolhe apenas um.\n" +
          "6. ESTRUTURA VISUAL OBRIGATÓRIA (Usa exatamente este template para cada ativo validado):\n\n" +
          "   🎯 [TICKER] - [Nome da Empresa] ([Setor])\n" +
          "   - 🚩 BANDEIRAS: (Lista aqui os avisos da regra 3 e 5, ou 'Limpo')\n" +
          "   - ⚙️ EXECUÇÃO: (Menciona a regra dos Gaps e Gestão de Lucro)\n" +
          "   - 🛡️ TAMANHO DA POSIÇÃO: (Recomenda Lote Completo ou Lote Reduzido a 50%)\n" +
          "   - 🔢 DADOS EXATOS: Entrada: X | Stop: X | TP: X | BE: X | Trailing: X | Qtd: X (Se Lote Reduzido, divide a Qtd original por 2)\n" +
          "   - 📋 REFERÊNCIA: (Cola a linha original do comboio aqui)\n\n" +
          "7. SAÚDE DO MERCADO E MANDATO FINAL:\n" +
          "   Termina o relatório com uma frase sobre o estado do mercado E inclui SEMPRE de forma isolada e a negrito no fim:\n" +
          "   **'TÁTICA DE EXECUÇÃO OBRIGATÓRIA: Não executar ordens antes das 15h00. Deixar a volatilidade inicial queimar os amadores e confirmar a verdadeira direção institucional.'**\n\n" +
          "--------------------------------------------------\n" +
          "DADOS DOS ATIVOS (COMBOIO):\n\n";

        return [[ 
          "Preço: " + preco.toFixed(2), 
          "Dist MM20: " + distMM20, 
          "Momentum: " + momentum, 
          "RSI: " + rsi, 
          "ADX: " + adx, 
          "ATR: " + atr.toFixed(2) + " (Vol: " + atrPerc + "%)", 
          "RVOL: " + rvol1, 
          "Estado: " + recomendacao, 
          "Entrada: " + precoEntrada, 
          "Stop: " + precoStop, 
          "Take-Profit: " + precoTakeProfit, 
          "Break-Even: " + precoBreakeven, 
          "Qtd: " + qtdAcoes, 
          "Trailing: " + precoTrailingStop, 
          "Data: " + stringDataFinal 
        ]];
        
      } else {
        continue; 
      }
    } catch (erro) {
      continue; 
    }
  } 
  
  return [["#ERRO_API", "Limites esgotados", "N/A", "N/A", "N/A", "N/A", "N/A", "Observar", "N/A", "N/A", "N/A", "N/A", "N/A", "N/A", "N/A"]];
}
/**
 * Retorna os dados concatenados na célula e o dia/hora de execução da API na coluna ao lado.
 * @param {string} ticker O ticker da ação (Ex: E22)
 * @customfunction
 */
function ANALISE_TACTICA(ticker,podeExecutar) {
 // 1. Valida se o Ticker é válido
  if (!ticker || ticker === "" || ticker.toString().indexOf("#") === 0) {
    return [["Aguardando Ticker...", ""]];
  }
  // 2. Valida a Flag de Execução (Passada como argumento na célula)
  if (!podeExecutar) {
    return [["Análise Pausada", "Altera config para retomar"]];
  }

  // 3. Criar uma lista (Array) com todas as tuas chaves
  var apiKeys = [
    //"26d40a7e4a474816bbda2b66639e1f83", // DuarteVilanova
    //"2f5ab27e4dec4858b4f7b9b17f11ea37", // PintoDuarte
    //"909825477aa842a79067ca21edbb9108",  // Fashion
    //"b94570bd058c4129ab21931218c4add5", // Licita
    //"60c437d305ee400c8e49e04f01404735", // Vany Trading
    //"29566e5809d94c509ca92e82d3db3cda"  // Lara   
  ];
  
  var validarTendenciaSPY = true; 

  // 2. Iniciar o ciclo para tentar cada chave, uma a uma
  for (var k = 0; k < apiKeys.length; k++) {
    var apiKey = apiKeys[k];
    
    try {
      // -------------------------------------------------------------------
      // Validação de Tendência do S&P 500 (SPY vs SMA 200)
      // -------------------------------------------------------------------
      if (validarTendenciaSPY) {
        var urlSPY = "https://api.twelvedata.com/time_series?symbol=SPY&interval=1day&outputsize=200&apikey=" + apiKey;
        var resSPY = UrlFetchApp.fetch(urlSPY, {"muteHttpExceptions": true});
        
        if (resSPY.getResponseCode() === 200) {
          var dSPY = JSON.parse(resSPY.getContentText());
          
          // Se esta chave já esgotou o limite logo no SPY, salta para a próxima chave
          if (dSPY.status === "error") {
            continue; 
          }
          
          if (dSPY.values && dSPY.values.length >= 200) {
            var precoSPY = parseFloat(dSPY.values[0].close);
            var somaSPY200 = 0;
            for (var j = 0; j < 200; j++) {
              somaSPY200 += parseFloat(dSPY.values[j].close);
            }
            var sma200SPY = somaSPY200 / 200;
            
            if (precoSPY < sma200SPY) {
              return [["#BLOQUEADO_SPY_BAIXA", "Mercado Geral abaixo da SMA200"]];
            }
          }
        } else {
          continue; // Erro de HTTP, tenta a próxima chave
        }
      }
      
      // -------------------------------------------------------------------
      // Pedidos Principais do Ticker
      // -------------------------------------------------------------------
      var urlVolume = "https://api.twelvedata.com/time_series?symbol=" + ticker + "&interval=1day&outputsize=25&apikey=" + apiKey;
      var urlRSI    = "https://api.twelvedata.com/rsi?symbol=" + ticker + "&interval=1day&time_period=14&apikey=" + apiKey;
      var urlADX    = "https://api.twelvedata.com/adx?symbol=" + ticker + "&interval=1day&time_period=14&apikey=" + apiKey;

      var resVol = UrlFetchApp.fetch(urlVolume, {"muteHttpExceptions": true});
      var resRSI = UrlFetchApp.fetch(urlRSI, {"muteHttpExceptions": true});
      var resADX = UrlFetchApp.fetch(urlADX, {"muteHttpExceptions": true});
      
      if (resVol.getResponseCode() === 200 && resRSI.getResponseCode() === 200 && resADX.getResponseCode() === 200) {
        var dVol = JSON.parse(resVol.getContentText());
        var dRSI = JSON.parse(resRSI.getContentText());
        var dADX = JSON.parse(resADX.getContentText());
        
        // Se bater no limite de API nalgum destes indicadores, tenta a PRÓXIMA chave no ciclo
        if (dVol.status === "error" || dRSI.status === "error" || dADX.status === "error") {
          continue; 
        }
        
        var valores = dVol.values;
        var preco = parseFloat(valores[0].close);
        
        // --- Cálculos Matemáticos ---
        var somaPrecos20 = 0;
        for (var i = 0; i < 20; i++) { somaPrecos20 += parseFloat(valores[i].close); }
        var distMM20 = (((preco - (somaPrecos20 / 20)) / (somaPrecos20 / 20)) * 100).toFixed(2) + "%";
        
        var momentum = (preco - parseFloat(valores[14].close)).toFixed(2);
        
        var volUltimoDia = parseFloat(valores[0].volume);
        var somaVolumes = 0;
        for (var i = 0; i < 20; i++) { somaVolumes += parseFloat(valores[i].volume); }
        var rvol1 = (volUltimoDia / (somaVolumes / 20)).toFixed(2);
        
        var somaTr = 0;
        for (var i = 0; i < 14; i++) { somaTr += (parseFloat(valores[i].high) - parseFloat(valores[i].low)); }
        var atr = parseFloat((somaTr / 14).toFixed(2));
        
        var rsi = parseFloat(dRSI.values[0].rsi).toFixed(2);
        var adx = parseFloat(dADX.values[0].adx).toFixed(2);
        
        // --- Níveis Operacionais e Risco ---
        var precoAnterior = parseFloat(valores[1].close);
        var varPerc = ((preco - precoAnterior) / precoAnterior) * 100;
        
        var recomendacao = "";
        var precoEntrada = "N/A";
        var precoStop = "N/A";
        var precoTakeProfit = "N/A";
        var qtdAcoes = "N/A";
        var riscoMaximoDolares = 25.00;
        
        // NOVAS VARIÁVEIS DE GESTÃO DE RISCO
        var multiplicadorATR = 1.0; 
        var racioTakeProfit = 2.0; 

        // Converte as variáveis para números para a validação rigorosa
        var valRVOL = parseFloat(rvol1);
        var valRSI = parseFloat(rsi);
        var valADX = parseFloat(adx);

        if (varPerc > 0 && valADX < 20) {
          recomendacao = "Aguardar Recuo";
          precoEntrada = (preco - (atr * 0.4)).toFixed(2);
          multiplicadorATR = 1; 
          racioTakeProfit = racioTakeProfitGlobal || 2.0; 
          
        } else if (varPerc > 0 && valADX >= 20 && valRVOL >= 0.85 && valRSI >= 45.00 && valRSI <= 70.00) { 
          // A BLINDAGEM (FLEXIBILIZADA): Tendência >= 20, Volume >= 0.85 e RSI saudável (45 a 70)
          recomendacao = "Forca Consolidada";
          precoEntrada = (preco - (atr * 0.2)).toFixed(2);
          multiplicadorATR = 1.2; 
          racioTakeProfit = racioTakeProfitGlobal || 1.5;  
          
        } else {
          recomendacao = "Observar";
        }
        
        // Calcular Risco, Stop e Take Profit baseados nas variáveis dinâmicas
        if (recomendacao !== "Observar" && precoEntrada !== "N/A") {
          var precoStopCalc = parseFloat(precoEntrada) - (atr * multiplicadorATR);
          precoStop = precoStopCalc.toFixed(2);
          
          var riscoPorAcao = parseFloat(precoEntrada) - precoStopCalc;
          
          if (riscoPorAcao > 0) {
            // Multiplica o risco pela nova variável em vez do "2" fixo
            var tp = parseFloat(precoEntrada) + (riscoPorAcao * racioTakeProfit);
            precoTakeProfit = tp.toFixed(2);
            qtdAcoes = (riscoMaximoDolares / riscoPorAcao).toFixed(2);
          }
        }
        // NOVO: Cálculo do Preço de Alerta / Breakeven (Metade do caminho para o TP)
        var precoBreakeven = "N/A";
        if (precoEntrada !== "N/A" && precoTakeProfit !== "N/A") {
          var distanciaAteTP = parseFloat(precoTakeProfit) - parseFloat(precoEntrada);
          precoBreakeven = (parseFloat(precoEntrada) + (distanciaAteTP / 2)).toFixed(2);
        }
        var concatenatedData = [
          ticker.toUpperCase(), preco.toFixed(2), distMM20, momentum, 
          rsi, adx, atr.toFixed(2), rvol1, recomendacao, 
          precoEntrada, precoStop, precoTakeProfit, precoBreakeven, qtdAcoes
        ].join(",");
        
        var apiDateTime = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "dd/MM/yyyy HH:mm:ss");
        
        // Se chegou até aqui, deu tudo certo! Devolve os dados e sai da função.
        return [[concatenatedData, apiDateTime]];
        
      } else {
        continue; // Erro de HTTP 500 ou afins, tenta próxima chave
      }
    } catch (erro) {
      continue; // Erro de execução (ex: timeout), tenta a próxima chave
    }
  } // Fim do loop das chaves
  
  // 3. Se o script sair do loop, significa que tentou todas as chaves e todas falharam
  return [["#ERRO_LIMITE_TODAS_CHAVES", "Todas as 6 chaves esgotaram os limites"]];
}
/**
 * Executa a distribuição dos dados concatenados para as colunas à frente de forma estática.
 * Grava também a data de atualização e os dados brutos concatenados no fim de cada linha ativa.
 * Agenda esta função para rodar de 5 em 5 minutos.
 */
function distribuirDadosEstaticos() {
  // Ajusta o nome da tua aba caso não seja "Carteira"
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Analise Compra"); 
  var ultimaLinha = sheet.getLastRow();
  
  // Define a coluna onde está a tua fórmula (F = 19) e onde os dados devem começar a ser espalhados (G = 21)
  var colunaFormula = 19; 
  var colunaDestino = 21; 
  
  // Lê as fórmulas a partir da Linha 3
  var intervaloFormulas = sheet.getRange(3, colunaFormula, (ultimaLinha - 3) + 1, 1).getValues();
  
  // NOVA ADIÇÃO: Lê a coluna de destino (Drop Zone) para saber se já tem dados
  var intervaloDestino = sheet.getRange(3, colunaDestino, (ultimaLinha - 3) + 1, 1).getValues();
  
  // Criar o formato de data e hora atual (Ex: 17/07/2026 15:30:22)
  var dataAtual = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "dd/MM/yyyy HH:mm:ss");
  
  for (var i = 0; i < intervaloFormulas.length; i++) {
    var valorConcatenated = intervaloFormulas[i][0].toString().trim();
    var valorExistente = intervaloDestino[i][0].toString().trim(); // Lê o valor atual na drop zone
    var linhaActual = 3 + i;
    
    // PROTEÇÃO 1: Se a drop zone já tem valor, ignora esta linha e não atualiza
    if (valorExistente !== "") {
      Logger.log("Linha " + linhaActual + " já tem valor na drop zone. Bloqueada para nova atualização hoje.");
      continue; 
    }
    
    // PROTEÇÃO 2: Alterado para >= 15 para não bloquear agora que tens mais campos (são 16 com o Trailing e Data)
    if (valorConcatenated && valorConcatenated.split(",").length >= 15) {
      var partes = valorConcatenated.split(",");
      
      // Criamos a linha completa a escrever:
      var dadosParaEscrever = [
        partes[0],     // [0] Símbolo (Ação)
        partes[1],     // [1] Preço
        partes[2],     // [2] Dist_MM20%
        partes[3],     // [3] Momentum
        partes[4],     // [4] RSI
        partes[5],     // [5] ADX
        partes[6],     // [6] ATR
        partes[7],     // [7] RVOL1
        partes[14],    // ---> [NOVO] Adicionado o teu Trailing Stop aqui!
        dataAtual,     // Coluna seguinte: Data da Última Atualização
        valorConcatenated // Última coluna: Dados originais concatenados brutos
      ];
      
      // Escreve de forma física (estática) as colunas no Sheets (ajusta-se automaticamente ao novo tamanho)
      sheet.getRange(linhaActual, colunaDestino, 1, dadosParaEscrever.length).setValues([dadosParaEscrever]);
      
    } else {
      // Se a API falhar ou não houver dados válidos
      Logger.log("Linha " + linhaActual + " sem dados válidos.");
    }
  }
}
/**
 * Agrupa os dados concatenados da Coluna R, limpa espaços e linhas vazias,
 * e gera um bloco único de texto na Sheet "Rajada" para copiar para o Gemini.
 */
function gerarBlocoRajada() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheetOrigem = ss.getSheetByName("Analise Compra");
  var sheetDestino = ss.getSheetByName("Drop Zone"); // Cria esta aba no teu Sheets
  
  if (!sheetOrigem || !sheetDestino) {
    Logger.log("Erro: Verifica os nomes das abas 'Analise Compra' e 'Rajada'.");
    return;
  }
  
  var ultimaLinha = sheetOrigem.getLastRow();
  var linhaInicial = 3; // Linha onde começam as tuas fórmulas/dados
  
  // Se não houver dados abaixo da linha 22, para o script
  if (ultimaLinha < linhaInicial) return;
  
  // Lê toda a Coluna R (18) a partir da linha inicial
  var intervalo = sheetOrigem.getRange(linhaInicial, 30, (ultimaLinha - linhaInicial) + 1, 1).getValues();
  var linhasLimpas = [];
  
  for (var i = 0; i < intervalo.length; i++) {
    var valorRaw = intervalo[i][0];
    
    if (valorRaw) {
      // Remove todos os espaços em branco da linha
      var valorLimpo = valorRaw.toString().replace(/\s+/g, '');
      
      // Só adiciona se a linha tiver dados válidos (evita linhas que só têm erro ou vazias)
      if (valorLimpo && valorLimpo.split(",").length >= 7) {
        linhasLimpas.push(valorLimpo);
      }
    }
  }
  
  // Junta todas as linhas válidas com uma quebra de linha
  var blocoTextoFinal = linhasLimpas.join("\n");
  
  // Escreve o bloco pronto a copiar na Célula A2 da aba "Rajada"
  sheetDestino.getRange("A2").setValue(blocoTextoFinal);
  Logger.log("Bloco gerado com sucesso na aba Rajada!");
}
function limparCheckboxes() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  
  // ==============================================================
  // 1. LIMPAR CHECKBOXES NA ABA DE ANÁLISE
  // ==============================================================
  var folhaAnalise = ss.getSheetByName("Analise Compra"); 
  
  if (folhaAnalise) {
    // Limpa todas as caixas de verificação da Coluna R (a partir da linha 3)
    // Nota: Se os teus dados começarem na linha 2, altera "R3:R" para "R2:R"
    folhaAnalise.getRange("R3:R").setValue(false); 
  }

  // ==============================================================
  // 2. RESET DA CONFIGURAÇÃO "processarTudo" PARA FALSE
  // ==============================================================
  var folhaConfigs = ss.getSheetByName("Configs");
  
  if (folhaConfigs) {
    var configData = folhaConfigs.getRange("A:B").getValues();
    
    // Procura em qual linha está a palavra "processarTudo"
    for (var c = 0; c < configData.length; c++) {
      if (configData[c][0] === "processarTudo") {
        // Encontrou! Agora muda o valor na coluna 2 (B) da mesma linha para false
        // Usamos c + 1 porque o array começa em 0 mas o Google Sheets começa na linha 1
        folhaConfigs.getRange(c + 1, 2).setValue(false);
        break; // Sai do loop mal encontre e altere, para poupar processamento
      }
    }
  }
}
function limparDropZone() {
  var folha = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  // Limpa todas as caixas de verificação no intervalo definido
   folha.getRange("U3:U").setValue("");
   folha.getRange("V3:V").setValue("");
   folha.getRange("W3:W").setValue("");
   folha.getRange("X3:X").setValue("");
   folha.getRange("Y3:Y").setValue("");
   folha.getRange("Z3:Z").setValue("");
   folha.getRange("AA3:AA").setValue("");
   folha.getRange("AB3:AB").setValue("");
   folha.getRange("AC3:AC").setValue("");
   folha.getRange("AD3:AD").setValue(""); 
}
function processarListaComDelay() {
  // Ajusta para o nome exato da tua aba
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Analise Compra"); 
  var ultimaLinha = sheet.getLastRow();
  
  // CONFIGURAÇÕES
  var colunaCheck = 18; // Substitui pelo número da coluna onde vais escrever "check" (Ex: T = 20)
  var linhaInicial = 3; // Linha onde começam os teus ativos
  var tempoEsperaSegundos = 30; // Define o delay em segundos (Ex: 8 segundos)
  
  for (var i = linhaInicial; i <= ultimaLinha; i++) {
    
    // 1. Escreve a palavra "check" na célula
    sheet.getRange(i, colunaCheck).setValue(true);
    
    // 2. CRÍTICO: Obriga o Sheets a aplicar o valor fisicamente na folha AGORA,
    // o que faz a tua fórmula da API disparar para esta linha específica.
    SpreadsheetApp.flush();
    
    // 3. Aguarda o tempo definido antes de passar para a próxima linha
    // (Só faz a pausa se não for a última linha, para não esperar desnecessariamente no fim)
    if (i < ultimaLinha) {
      Logger.log("A aguardar " + tempoEsperaSegundos + " segundos antes da próxima linha...");
      Utilities.sleep(tempoEsperaSegundos * 1000); // sleep funciona em milissegundos
    }
  }
  
  Logger.log("Processamento concluído com sucesso!");
}
function processarLoteItems() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  
  // ==============================================================
  // 1. VALIDAÇÃO DA ABA DE CONFIGURAÇÕES
  // ==============================================================
  var sheetConfig = ss.getSheetByName("Configs");
  var configData = sheetConfig.getRange("A:B").getValues(); 
  var podeExecutar = false;

  for (var c = 0; c < configData.length; c++) {
    if (configData[c][0] === "processarLoteItems") {
      podeExecutar = (configData[c][1] === true); 
      break;
    }
  }

  // ==============================================================
  // 2. INÍCIO DO PROCESSAMENTO
  // ==============================================================
  var sheet = ss.getSheetByName("Analise Compra");
  var ultimaLinha = sheet.getLastRow();
  
  if (ultimaLinha < 2) return; 

  var colunaCheck = 18;  // Coluna R 
  var colunaStatus = 19; // Coluna S 
  
  var tamanhoLote = 20; 
  var processadosNesteLote = 0;
  var tempoEsperaSegundos = 15; 
  
  var valoresTicker = sheet.getRange(2, 5, ultimaLinha - 1, 1).getValues(); 
  var valoresCheck = sheet.getRange(2, colunaCheck, ultimaLinha - 1, 1).getValues();
  var valoresStatus = sheet.getRange(2, colunaStatus, ultimaLinha - 1, 1).getValues();

  var resumo = []; // Vai guardar o que foi feito para te mostrar no fim

  for (var i = 0; i < valoresCheck.length; i++) {
    var linhaAtual = i + 2; 
    var ticker = valoresTicker[i][0];
    var estadoCheck = valoresCheck[i][0];
    var estadoErro = valoresStatus[i][0];

    // Ignora linhas sem Ticker
    if (ticker === "") continue; 

    if (estadoCheck !== true ) {
      
      try {
        // ==============================================================
        // AQUI ENTRARÁ O CÓDIGO DA API
        // ==============================================================
        sheet.getRange(linhaAtual, colunaCheck).setValue(true);
        
        
      } catch (erro) {
        sheet.getRange(linhaAtual, colunaCheck).setValue(false);
        
      }
      
      SpreadsheetApp.flush(); 
      Utilities.sleep(tempoEsperaSegundos * 1000); 
      
      processadosNesteLote++;
      resumo.push("Linha " + linhaAtual + " -> " + ticker);

      if (processadosNesteLote >= tamanhoLote) {
        break; 
      }
    }
  }

  // ==============================================================
  // 3. AVISOS FINAIS NO ECRÃ
  // ==============================================================
 
  //if (processadosNesteLote === 0) {
  //  SpreadsheetApp.getUi().alert("NADA PROCESSADO.\n\nO script verificou até à linha " + ultimaLinha + " mas todas as linhas com Ticker já tinham a checkbox marcada a 'true'.");
  //} else {
   // SpreadsheetApp.getUi().alert("SUCESSO! Foram processados os seguintes " + processadosNesteLote + " ativos:\n\n" + resumo.join("\n"));
  //}

}

function resetConfigProcessarLote() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Configs");
  if (!sheet) return;
  
  var ultimaLinha = sheet.getLastRow();
  if (ultimaLinha < 1) return;

  // Lê as colunas A e B da aba Configs
  var dados = sheet.getRange(1, 1, ultimaLinha, 2).getValues();

  var flagsDesativadas = 0;

  for (var i = 0; i < dados.length; i++) {
    // Verifica se a linha corresponde a alguma das flags que queremos desativar
    if (dados[i][0] === "processarLoteItems_Short" || dados[i][0] === "processarTudo") {
      
      // Coloca a coluna B (coluna 2) a false
      sheet.getRange(i + 1, 2).setValue(false);
      flagsDesativadas++;
      
      // Se já encontrou as duas flags, pode parar o ciclo para poupar recursos
      if (flagsDesativadas === 2) {
        break; 
      }
    }
  }
}
function ativarConfigProcessarLote() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Configs");
  if (!sheet) return;
  
  var ultimaLinha = sheet.getLastRow();
  if (ultimaLinha < 1) return;

  // Lê as colunas A e B da aba Configs
  var dados = sheet.getRange(1, 1, ultimaLinha, 2).getValues();
  
  var flagsAtivadas = 0;

  for (var i = 0; i < dados.length; i++) {
    // Verifica se a linha corresponde a alguma das flags que queremos ativar - if (dados[i][0] === "processarLoteItems_Short" || dados[i][0] === "processarTudo") {
    if (dados[i][0] === "processarLoteItems_Short") {
      
      // Coloca a coluna B (coluna 2) a true
      sheet.getRange(i + 1, 2).setValue(true);
      flagsAtivadas++;
      
      // Se já encontrou as duas flags, pode parar o ciclo para poupar recursos
      if (flagsAtivadas === 1) {
        break; 
      }
    }
  }
}

function processarLoteItemsShort() {
  // --- INÍCIO DA BARREIRA DE FIM DE SEMANA ---
  var diaDaSemana = new Date().getDay();
  // 0 = Domingo | 6 = Sábado
  if (diaDaSemana === 0 || diaDaSemana === 6) {
    Logger.log("Fim de semana detetado (Mercado Fechado). Atualização cancelada e histórico protegido.");
    return; // Para aqui e não mexe em nenhuma linha nem histórico
  }
  // --- FIM DA BARREIRA DE FIM DE SEMANA ---

  var ss = SpreadsheetApp.getActiveSpreadsheet();
  
  // ==============================================================
  // 1. VALIDAÇÃO DA ABA DE CONFIGURAÇÕES E LISTA PERMITIDA
  // ==============================================================
  var sheetConfig = ss.getSheetByName("Configs");
  var configData = sheetConfig.getRange("A:B").getValues(); 
  var podeExecutar = false;
  var processarTudo = false; 
  var listaPermitida = []; 

  for (var c = 0; c < configData.length; c++) {
    if (configData[c][0] === "processarLoteItems_Short") {
      podeExecutar = (configData[c][1] === true); 
    }
    if (configData[c][0] === "processarTudo") { 
      processarTudo = (configData[c][1] === true); 
    }
    if (configData[c][0] === "listaAtivosPermitidos") {
      if (configData[c][1]) {
        listaPermitida = configData[c][1].toString().split(',').map(function(item) {
          return item.trim().toUpperCase();
        });
      }
    }
  }

  if (!podeExecutar) return;

  // ==============================================================
  // 2. INÍCIO DO PROCESSAMENTO
  // ==============================================================
  var sheet = ss.getSheetByName("Analise Compra");
  var ultimaLinha = sheet.getLastRow();
  
  if (ultimaLinha < 2) return; 

  var colunaCheck = 18;  // Coluna R 
  var colunaStatus = 19; // Coluna S 
  
  var tamanhoLote = 20; 
  var processadosNesteLote = 0;
  var tempoEsperaSegundos = 15; 
  
  var valoresTicker = sheet.getRange(2, 5, ultimaLinha - 1, 1).getValues(); 
  var valoresCheck = sheet.getRange(2, colunaCheck, ultimaLinha - 1, 1).getValues();
  var valoresStatus = sheet.getRange(2, colunaStatus, ultimaLinha - 1, 1).getValues();

  var resumo = []; 

  for (var i = 0; i < valoresCheck.length; i++) {
    var linhaAtual = i + 2; 
    var ticker = valoresTicker[i][0];
    var estadoCheck = valoresCheck[i][0];
    
    if (ticker === "") continue; 
    
    var tickerFormatado = ticker.toString().trim().toUpperCase();

    // Só ignora o ticker se 'processarTudo' for false E o ticker NÃO estiver na lista
    if (!processarTudo && !listaPermitida.includes(tickerFormatado)) {
      continue; 
    }

    // Processa se a checkbox NÃO estiver marcada
    if (estadoCheck !== true) {
      
      try {
        // ==============================================================
        // INTEGRAÇÃO DIRETA COM A LÓGICA DA API
        // ==============================================================
        
        // 1. Coloca o status temporário
        sheet.getRange(linhaAtual, colunaStatus).setValue("A calcular...");
        SpreadsheetApp.flush(); 
        
        // 2. Chama a função central diretamente
        var resultados = ANALISE_TACTICA_AUTO(tickerFormatado);
        
        // 3. Concatena os resultados (O "Comboio")
        var textoConcatenado = tickerFormatado + "," + resultados[0].join(",");
        
        // 4. Escreve os resultados na Coluna 19
        sheet.getRange(linhaAtual, 19).setValue(textoConcatenado);
        
        // ==============================================================
        // 5. LÓGICA DO CONTADOR
        // ==============================================================
        var colunaContador = 20;  // Coluna U
        var palavraGatilho = "Forca Consolidada"; 
        
        var arrayDados = textoConcatenado.split(',');
        var estadoHoje = "";
        
        if (arrayDados.length > 8) {
          estadoHoje = arrayDados[8].trim().toUpperCase(); 
          estadoHoje = estadoHoje.replace("ESTADO:", "").trim();
        }

        var celulaContador = sheet.getRange(linhaAtual, colunaContador);
        var contadorAnterior = celulaContador.getValue();
        
        contadorAnterior = Number(contadorAnterior);
        if (isNaN(contadorAnterior)) {
          contadorAnterior = 0;
        }
        
        var novoValor = 0;
        if (estadoHoje === palavraGatilho.toUpperCase()) {
          novoValor = contadorAnterior + 1;
          celulaContador.setValue(novoValor);
        } else {
          celulaContador.setValue(0);
        }

        // ==============================================================
        // 6. FECHA A CHECKBOX (Marca como concluído com sucesso)
        // ==============================================================
        sheet.getRange(linhaAtual, 18).setValue(true);

        // ==============================================================
        // DIÁRIO DE BORDO AUTOMÁTICO, RADAR E EMAIL
        // ==============================================================
        if (estadoHoje === palavraGatilho.toUpperCase()) {
          var ssDiario = SpreadsheetApp.getActiveSpreadsheet();
          var sheetDiario = ssDiario.getSheetByName("Diário de Bordo");
          
          if (sheetDiario) {
            var dadosLinha = sheet.getRange(linhaAtual, 5, 1, 16).getValues(); 
            
            var dataHoraRegistoTexto = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "dd/MM/yyyy HH:mm:ss");
            var linhaParaInserir = [dataHoraRegistoTexto].concat(dadosLinha[0]);
            
            // Insere na linha 3
            sheetDiario.insertRowAfter(2);
            
            var rngInserido = sheetDiario.getRange(3, 1, 1, linhaParaInserir.length);
            rngInserido.setValues([linhaParaInserir]);
            
            // --- FORÇAR O FORMATO ESTRITO ---
            var celulaData = sheetDiario.getRange(3, 1);
            celulaData.setNumberFormat("@"); 
            celulaData.setHorizontalAlignment("center"); 

            // --- VARIÁVEL COM O "COMBOIO" JÁ MONTADO ---
            var linhaComboio = textoConcatenado; 

            // --- EXTRAÇÃO DOS DADOS PARA OS CAMPOS DO E-MAIL ---
            var precoEntrada = resultados[0][8];  // Entrada
            var stopAtivo    = resultados[0][9];  // Stop-Loss
            var tpAtivo      = resultados[0][10]; // Take-Profit
            var breakEven    = resultados[0][11]; // Break-Even
            var quantidade   = resultados[0][12]; // Qtd
            var trailingAtivo = resultados[0][13]; // Trailing
            var rsiAtivo     = resultados[0][3];  // RSI
            var distMM20     = resultados[0][1];  // Dist MM20
            var momentum     = resultados[0][2];  // Momentum
            var adxAtivo     = resultados[0][4];  // ADX
            var atrAtivo     = resultados[0][5];  // ATR
            var rvolAtivo    = resultados[0][6];  // RVOL
            var estadoAtivo  = resultados[0][7];  // Estado

            // --- DISPARAR O ALERTA COM O COMBOIO ---
            enviarAlertaTrading(
              tickerFormatado, 
              precoEntrada, 
              stopAtivo, 
              tpAtivo, 
              quantidade, 
              dataHoraRegistoTexto, 
              rsiAtivo, 
              distMM20, 
              momentum, 
              adxAtivo, 
              atrAtivo, 
              rvolAtivo, 
              breakEven, 
              estadoAtivo, 
              trailingAtivo, 
              linhaComboio
            );
          }
        }
        // --- NOVA LÓGICA: INTERCETAR O ALERTA IMINENTE E ENVIAR PARA O RADAR ---
        else if (estadoHoje === "ALERTA IMINENTE") {
          var ssRadar = SpreadsheetApp.getActiveSpreadsheet();
          var sheetRadar = ssRadar.getSheetByName("Radar de alertas"); 
          
          if (sheetRadar) {
            var dataHoraRadar = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "dd/MM/yyyy HH:mm:ss");
            
            // Extração pontual das métricas para a Watchlist
            var rvolRadar     = resultados[0][6];  // RVOL
            var entradaRadar  = resultados[0][8];  // Entrada
            var stopRadar     = resultados[0][9];  // Stop
            var tpRadar       = resultados[0][10]; // Take-Profit
            var qtdRadar      = resultados[0][12]; // Quantidade
            var distMM20Radar = resultados[0][1];  // Distância à média
            
            // Array com a ordem exata das colunas (A a J):
            // Data | Ativo | Setup | RVOL | Entrada | Stop Loss | Take-Profit | Qtd | Dist MM20 % | Comboio
            var linhaParaRadar = [
              dataHoraRadar,
              tickerFormatado,
              "Alerta Iminente",
              rvolRadar,
              entradaRadar,
              stopRadar,
              tpRadar,
              qtdRadar,
              distMM20Radar,
              textoConcatenado // <--- O Comboio injetado no final da linha em lote
            ];
            
            // Insere uma nova linha logo abaixo do cabeçalho
            sheetRadar.insertRowAfter(1);
            var rngRadar = sheetRadar.getRange(2, 1, 1, linhaParaRadar.length);
            rngRadar.setValues([linhaParaRadar]);
            
            // Forçar formatação de texto para proteger a data
            var celulaDataRadar = sheetRadar.getRange(2, 1);
            celulaDataRadar.setNumberFormat("@");
            celulaDataRadar.setHorizontalAlignment("center");
          }
        }
        
      } catch (erro) {
        sheet.getRange(linhaAtual, 19).setValue("ERRO: " + erro.message);
      }
      
      SpreadsheetApp.flush(); 
      Utilities.sleep(tempoEsperaSegundos * 1000); 
      
      processadosNesteLote++;
      resumo.push("Linha " + linhaAtual + " -> " + tickerFormatado);

      if (processadosNesteLote >= tamanhoLote) {
        break; 
      }
    }
  }
}
function aoEditarCheckbox(e) {
  if (!e || !e.range) return;
  var sheet = e.range.getSheet();
  
  // 1. Valida o nome exato da aba
  if (sheet.getName() !== "Analise Compra") return;
  
  var linha = e.range.getRow();
  var coluna = e.range.getColumn();
  
  // 2. Se a edição foi na Coluna 18 (R) e foi marcado o Visto
  if (coluna === 18 && linha > 1 && (e.value === "TRUE" || e.value === true)) {
    
    var ticker = sheet.getRange(linha, 5).getValue(); // Lê o Ticker da Coluna 5 (E)
    
    if (ticker && ticker !== "") {
      var tickerFormatado = ticker.toString().trim().toUpperCase();
      
      // Mete status temporário na Coluna 19 (S)
      sheet.getRange(linha, 19).setValue("A calcular...");
      SpreadsheetApp.flush();
      
      try {
        // Chama a função central
        var resultados = ANALISE_TACTICA_AUTO(tickerFormatado);
        // ==============================================================
        // BARREIRA DE SEGURANÇA CONTRA FALHAS DE API
        // ==============================================================
        if (!resultados || !resultados[0]) {
          sheet.getRange(linha, 19).setValue("ERRO: API falhou ou Ticker sem dados.");
          return; // Aborta a execução aqui para não encravar o script
        }
        // ==============================================================
        
        // Concatena os resultados (O "Comboio")
        var textoConcatenado = tickerFormatado + "," + resultados[0].join(",");
        
        // Escreve a string toda junta na Coluna 19
        sheet.getRange(linha, 19).setValue(textoConcatenado);
        
        // ==============================================================
        // LÓGICA DO CONTADOR (COLUNA U / 20) E DIÁRIO DE BORDO
        // ==============================================================
        var colunaContador = 20;  // Coluna U
        var palavraGatilho = "FORCA CONSOLIDADA"; 
        
        var arrayDados = textoConcatenado.split(',');
        var estadoHoje = "";
        
        // O estado está no índice 8 (ex: "Estado: Forca Consolidada")
        if (arrayDados.length > 8) {
          estadoHoje = arrayDados[8].toString().trim().toUpperCase();
          // Remove o prefixo "ESTADO:" caso venha incluído na string
          estadoHoje = estadoHoje.replace("ESTADO:", "").trim();
        }

        var celulaContador = sheet.getRange(linha, colunaContador);
        var contadorAnterior = celulaContador.getValue();
        
        contadorAnterior = Number(contadorAnterior);
        if (isNaN(contadorAnterior)) {
          contadorAnterior = 0;
        }
        
        var novoValor = 0;
        if (estadoHoje === palavraGatilho) {
          novoValor = contadorAnterior + 1;
          celulaContador.setValue(novoValor);
        } else {
          celulaContador.setValue(0);
        }

        // ==============================================================
        // DIÁRIO DE BORDO AUTOMÁTICO, RADAR E EMAIL
        // ==============================================================
        if (estadoHoje === palavraGatilho) {
          var ss = SpreadsheetApp.getActiveSpreadsheet();
          var sheetDiario = ss.getSheetByName("Diário de Bordo");
          
          if (sheetDiario) {
            // Lê a linha de dados da análise para o Diário de Bordo
            var dadosLinha = sheet.getRange(linha, 5, 1, 16).getValues(); 
            var dataHoraRegisto = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "dd/MM/yyyy HH:mm:ss");
            
            var linhaParaInserir = [dataHoraRegisto].concat(dadosLinha[0]);
            
            // Insere na linha 3
            sheetDiario.insertRowAfter(2);
            sheetDiario.getRange(3, 1, 1, linhaParaInserir.length).setValues([linhaParaInserir]);

            // Forçar formatação
            var celulaData = sheetDiario.getRange(3, 1);
            celulaData.setNumberFormat("@");
            celulaData.setHorizontalAlignment("center");

            // --- VARIÁVEL COM O "COMBOIO" JÁ MONTADO ---
            var linhaComboio = textoConcatenado; 

            // --- EXTRAÇÃO DOS DADOS PARA OS CAMPOS DO E-MAIL ---
            var precoEntrada = resultados[0][8];  // Entrada
            var stopAtivo    = resultados[0][9];  // Stop-Loss
            var tpAtivo      = resultados[0][10]; // Take-Profit
            var breakEven    = resultados[0][11]; // Break-Even
            var quantidade   = resultados[0][12]; // Qtd
            var trailingAtivo = resultados[0][13]; // Trailing
            var rsiAtivo     = resultados[0][3];  // RSI
            var distMM20     = resultados[0][1];  // Dist MM20
            var momentum     = resultados[0][2];  // Momentum
            var adxAtivo     = resultados[0][4];  // ADX
            var atrAtivo     = resultados[0][5];  // ATR
            var rvolAtivo    = resultados[0][6];  // RVOL
            var estadoAtivo  = resultados[0][7];  // Estado

            // --- DISPARAR O ALERTA COM O COMBOIO ---
            enviarAlertaTrading(
              tickerFormatado, 
              precoEntrada, 
              stopAtivo, 
              tpAtivo, 
              quantidade, 
              dataHoraRegisto, 
              rsiAtivo, 
              distMM20, 
              momentum, 
              adxAtivo, 
              atrAtivo, 
              rvolAtivo, 
              breakEven, 
              estadoAtivo, 
              trailingAtivo, 
              linhaComboio
            );
          }
        }
        // --- NOVA LÓGICA: INTERCETAR O ALERTA IMINENTE E ENVIAR PARA O RADAR ---
        else if (estadoHoje === "ALERTA IMINENTE") {
          var ssRadar = SpreadsheetApp.getActiveSpreadsheet();
          var sheetRadar = ssRadar.getSheetByName("Radar de alertas"); 
          
          if (sheetRadar) {
            var dataHoraRadar = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "dd/MM/yyyy HH:mm:ss");
            
            // Extração pontual das métricas para a Watchlist
            var rvolRadar     = resultados[0][6];  // RVOL (O gatilho que falhou por pouco)
            var entradaRadar  = resultados[0][8];  // Entrada
            var stopRadar     = resultados[0][9];  // Stop
            var tpRadar       = resultados[0][10]; // Take-Profit
            var qtdRadar      = resultados[0][12]; // Quantidade
            var distMM20Radar = resultados[0][1];  // Distância à média
            
            // Array com a ordem exata das colunas (A a J):
            // Data | Ativo | Setup | RVOL | Entrada | Stop Loss | Take-Profit | Qtd | Dist MM20 % | Comboio
            var linhaParaRadar = [
              dataHoraRadar,
              tickerFormatado,
              "Alerta Iminente",
              rvolRadar,
              entradaRadar,
              stopRadar,
              tpRadar,
              qtdRadar,
              distMM20Radar,
              textoConcatenado // <--- [NOVO] O Comboio injetado no final da linha
            ];
            
            // Insere uma nova linha logo abaixo do cabeçalho
            sheetRadar.insertRowAfter(1);
            var rngRadar = sheetRadar.getRange(2, 1, 1, linhaParaRadar.length);
            rngRadar.setValues([linhaParaRadar]);
            
            // Forçar formatação de texto para proteger a data
            var celulaDataRadar = sheetRadar.getRange(2, 1);
            celulaDataRadar.setNumberFormat("@");
            celulaDataRadar.setHorizontalAlignment("center");
          }
        }
        
      } catch (erroGrave) {
        sheet.getRange(linha, 19).setValue("ERRO: " + erroGrave.message);
      }
    }
  }
}
function obterDadosTwelveData(celulaTicker) {
  var apiKey = "2f5ab27e4dec4858b4f7b9b17f11ea37"; // A tua chave da Twelve Data
  var symbol = celulaTicker;
  var exchange = "";

  // 1. Detetar o formato BOLSA:TICKER (ex: "FRA:BMW")
  if (celulaTicker.indexOf(":") !== -1) {
    var partes = celulaTicker.split(":");
    exchange = partes[0].trim(); // A bolsa fica antes dos : (ex: FRA)
    symbol = partes[1].trim();   // O ticker fica depois dos : (ex: BMW)
  }

  // 2. Construir o URL Base
  // (Substitui "quote" pelo endpoint que usas, ex: "time_series")
  var url = "https://api.twelvedata.com/quote?symbol=" + symbol + "&apikey=" + apiKey;

  // 3. Injetar o parâmetro "exchange" se for uma ação europeia
  if (exchange !== "") {
    url = url + "&exchange=" + exchange;
  }

  // 4. Fazer a chamada à API
  try {
    var resposta = UrlFetchApp.fetch(url);
    var dados = JSON.parse(resposta.getContentText());
    
    // Validar se a API devolveu erro (ex: limite de chamadas ou ticker inválido)
    if (dados.status === "error") {
      return "Erro: " + dados.message;
    }

    // 5. Retornar o valor pretendido (ajusta consoante o teu modelo)
    return dados.close; 
    
  } catch (erro) {
    return "Erro de ligação";
  }
}
function enviarAlertaTrading(ticker, preco, stop, takeProfit, quantidade, dataRegisto, rsi, distMM20, momentum, adx, atr, rvol, breakEven, estado, trailing, linhaCompleta) {
  var assunto = ticker + " - ALERTA TRADING: Força Consolidada";
  
  function limparValor(val, prefixoParaRemover) {
    if (!val) return "";
    var texto = val.toString().trim();
    if (prefixoParaRemover && texto.toUpperCase().indexOf(prefixoParaRemover.toUpperCase()) === 0) {
      texto = texto.substring(prefixoParaRemover.length).trim();
    }
    return texto.replace(/^[a-zA-ZÀ-ÿ\s\-]+:\s*/, "").trim();
  }

  var limpoPreco = Number(limparValor(preco, "Entrada:"));
  var limpoStop = Number(limparValor(stop, "Stop:"));
  var limpoTP = Number(limparValor(takeProfit, "Take-Profit:"));

  var risco = limpoPreco - limpoStop;
  var retorno = limpoTP - limpoPreco;
  var rrRatio = (risco > 0 && !isNaN(risco) && !isNaN(retorno)) ? (retorno / risco).toFixed(2) : "N/A";

  var mensagem = "O sistema detetou um novo setup de alta qualidade!\n\n" +
                 "• Ticker: " + ticker + "\n" +
                 "• Data/Hora: " + dataRegisto + "\n\n" +
                 "--- PARÂMETROS DA POSIÇÃO ---\n" +
                 "• Preço de Entrada: " + limparValor(preco, "Entrada:") + "\n" +
                 "• Quantidade (Qtd): " + limparValor(quantidade, "Qtd:") + "\n" +
                 "• Stop-Loss: " + limparValor(stop, "Stop:") + "\n" +
                 "• Trailing Stop: " + limparValor(trailing, "Trailing:") + "\n" +
                 "• Take-Profit: " + limparValor(takeProfit, "Take-Profit:") + "\n" +
                 "• Break-Even: " + limparValor(breakEven, "Break-Even:") + "\n" +
                 "• Rácio Risco/Retorno: 1 : " + rrRatio + "\n\n" +
                 "--- CONTEXTO TÉCNICO ---\n" +
                 "• RSI: " + limparValor(rsi, "RSI:") + "\n" +
                 "• Dist. MM20: " + limparValor(distMM20, "Dist MM20:") + "\n" +
                 "• Momentum: " + limparValor(momentum, "Momentum:") + "\n" +
                 "• ADX: " + limparValor(adx, "ADX:") + "\n" +
                 "• ATR: " + limparValor(atr, "ATR:") + "\n" +
                 "• RVOL: " + limparValor(rvol, "RVOL:") + "\n\n" +
                 "--- REGISTO COMPLETO ---\n" +
                 linhaCompleta + "\n\n" + // <--- O erro estava nesta linha! Já está corrigido.
                 "Consulta o teu Google Sheets e o Diário de Bordo para validar a posição.";
  
  var meuEmail = Session.getActiveUser().getEmail();
  
  GmailApp.sendEmail(meuEmail, assunto, mensagem);
}

// ==============================================================
// SCRIPT INTRADAY (15h30) - GESTOR DE POSIÇÕES (TREND FOLLOWER)
// ==============================================================
function atualizarDiarioIntraday() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheetDiario = ss.getSheetByName("Diário de Bordo");
  
  if (!sheetDiario) return;

  var COL_MAX_DIA = 17; // Começa a escrever na Coluna Q
  
  if (sheetDiario.getRange("Q2").getValue() === "") {
    sheetDiario.getRange("Q2:V2").setValues([["Máximo 15h30", "Nova Entrada", "Novo Stop Loss", "Novo Take Profit", "Status Intraday", "Resumo Intraday"]]);
    sheetDiario.getRange("Q2:V2").setFontWeight("bold").setBackground("#e0f7fa");
  }

  var hoje = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "dd/MM/yyyy");
  var ultimaLinha = sheetDiario.getLastRow();
  
  if (ultimaLinha < 3) return;

  // Extrai da Coluna 16 (P) até à Coluna 23 (W)
  var dados = sheetDiario.getRange(3, 16, ultimaLinha - 2, 8).getValues();

  // Variável para acumular todos os resumos num único e-mail consolidado
  var corpoEmailGlobal = "Resumo Intraday - " + hoje + "\n\n========================\n\n";
  var contadorAtivosAtualizados = 0;

  for (var i = 0; i < dados.length; i++) {
    var linhaAtual = i + 3;
    var textoComboio = dados[i][0].toString(); // Coluna P
    var statusFechado = dados[i][7].toString().toUpperCase(); // Coluna W
    
    if (textoComboio === "") continue;
    
    // BLINDAGEM RIGOROSA: Ignora se a linha estiver vazia/sem valor OU se já estiver fechada
    if (statusFechado === "" || statusFechado === "WIN" || statusFechado === "LOSS" || statusFechado === "BREAKEVEN" || statusFechado === "FUGIU") {
      continue;
    }
    
    var partesComboio = textoComboio.split(",");
    var tickerT212 = partesComboio[0].trim(); 
    var tickerLimpo = tickerT212.split("_")[0].trim(); 
    
    const extrair = (chave) => {
      for (var j = 0; j < partesComboio.length; j++) {
        if (partesComboio[j].indexOf(chave) > -1) {
          var partesChave = partesComboio[j].split(":");
          if (partesChave.length > 1) {
            return partesChave[1].trim();
          }
        }
      }
      return "N/A";
    };
    
    var riscoStr = extrair("ATR:");
    var risco = riscoStr !== "N/A" ? parseFloat(riscoStr) : 0;
    var rsi = extrair("RSI:");
    var distMM20 = extrair("Dist MM20:");
    var momentum = extrair("Momentum:");
    var adx = extrair("ADX:");
    var atr = riscoStr; 
    var rvol = extrair("RVOL:");
    var qtd = extrair("Qtd:");
    
    if (tickerLimpo && risco > 0) {
      var maximoDia = 0;
      var fechoAnterior = 0;
      
      try {
        var url = "https://query1.finance.yahoo.com/v8/finance/chart/" + tickerLimpo;
        var resposta = UrlFetchApp.fetch(url, {muteHttpExceptions: true});
        
        if (resposta.getResponseCode() === 200) {
          var json = JSON.parse(resposta.getContentText());
          var meta = json.chart.result[0].meta;
          
          maximoDia = parseFloat(meta.regularMarketDayHigh || meta.regularMarketPrice);
          fechoAnterior = parseFloat(meta.chartPreviousClose);
        }
      } catch(e) { }
      
      var dataHoraIntraday = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "dd/MM/yyyy HH:mm:ss");

      if (!isNaN(maximoDia) && maximoDia > 0 && !isNaN(fechoAnterior) && fechoAnterior > 0) {
        
        if (maximoDia > fechoAnterior) {
          var precoEntrada = maximoDia - risco;
          var stopLoss = precoEntrada - risco;
          var takeProfit = precoEntrada + (risco * 1.5);
          var statusStr = "Forca Consolidada";
          
          var resumoIntraday = tickerT212 + " (INTRADAY),Máximo 15h30: " + maximoDia.toFixed(2) + ",Estado: " + statusStr + ",Entrada: " + precoEntrada.toFixed(2) + ",Stop: " + stopLoss.toFixed(2) + ",Take-Profit: " + takeProfit.toFixed(2) + ",Data: " + dataHoraIntraday;
          
          sheetDiario.getRange(linhaAtual, COL_MAX_DIA, 1, 6).setValues([[
            maximoDia.toFixed(2), precoEntrada.toFixed(2), stopLoss.toFixed(2), takeProfit.toFixed(2), statusStr, resumoIntraday
          ]]);
          
          // Adiciona ao texto global do e-mail
          corpoEmailGlobal += "🔹 " + tickerT212 + "\n" +
                              "• Máximo 15h30: " + maximoDia.toFixed(2) + "\n" +
                              "• Nova Entrada: " + precoEntrada.toFixed(2) + "\n" +
                              "• Novo Stop Loss: " + stopLoss.toFixed(2) + "\n" +
                              "• Novo Take Profit: " + takeProfit.toFixed(2) + "\n\n";
          contadorAtivosAtualizados++;
          
        } else {
           var statusStr = "Ignorado - S/ Quebra de Fecho";
           var resumoIntraday = tickerT212 + ",Máximo 15h30: " + maximoDia.toFixed(2) + ",Estado: " + statusStr + ",Data: " + dataHoraIntraday;
           
           sheetDiario.getRange(linhaAtual, COL_MAX_DIA, 1, 6).setValues([[
            maximoDia.toFixed(2), "-", "-", "-", statusStr, resumoIntraday
           ]]);
        }
        
      } else {
        var statusStr = "Erro Mercado - Ticker não encontrado";
        var resumoIntraday = tickerT212 + ",Estado: " + statusStr + ",Data: " + dataHoraIntraday;
        
        sheetDiario.getRange(linhaAtual, COL_MAX_DIA, 1, 6).setValues([[
          "Erro API", "-", "-", "-", statusStr, resumoIntraday
        ]]);
      } 
    }
  }

  // ENVIA APENAS UM ÚNICO E-MAIL NO FIM COM TODAS AS ATUALIZAÇÕES CONSOLIDADAS
  if (contadorAtivosAtualizados > 0) {
    MailApp.sendEmail(Session.getActiveUser().getEmail(), "Relatório Intraday Consolidado - " + hoje, corpoEmailGlobal);
  }
}
// ==============================================================
// GATILHOS CIRÚRGICOS - EXECUÇÃO EXATA ÀS 15H30 (HORA DE LISBOA)
// ==============================================================

// PASSO 1: Corre esta função APENAS UMA VEZ manualmente
function instalarGatilhoCirurgico() {
  var nomeFuncaoPreparador = "prepararExecucaoExata";
  
  // Limpa instaladores antigos para não duplicar
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === nomeFuncaoPreparador) {
      //ScriptApp.deleteTrigger(triggers[i]);
    }
  }
  
  // Cria a rotina matinal que vai agendar o horário exato todos os dias
  ScriptApp.newTrigger(nomeFuncaoPreparador)
    .timeBased()
    .everyDays(1)
    .atHour(8) // Todos os dias entre as 8h e as 9h da manhã
    .inTimezone("Europe/Lisbon")
    .create();
    
  Logger.log("Sucesso! O sistema matinal está ativado e vai preparar o disparo exato para as 15h30.");
}


// PASSO 2: O sistema que corre sozinho às 8h da manhã para apontar a mira às 15h30
function prepararExecucaoExata() {
  var nomeFuncaoIntraday = "atualizarDiarioIntraday";
  
  // Limpa o disparo do dia anterior
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === nomeFuncaoIntraday) {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }
  
  // Define a data de hoje e as horas exatas para o disparo
  var dataExata = new Date();
  dataExata.setHours(15);
  dataExata.setMinutes(30);
  dataExata.setSeconds(0);
  
  // Verifica se é dia de semana (Segunda = 1 a Sexta = 5). Ignora Sábados (6) e Domingos (0).
  var diaSemana = dataExata.getDay();
  if (diaSemana > 0 && diaSemana < 6) { 
    
    // Cria o gatilho cirúrgico para as 15:30 de hoje
    ScriptApp.newTrigger(nomeFuncaoIntraday)
      .timeBased()
      .at(dataExata)
      .inTimezone("Europe/Lisbon")
      .create();
  }
}
function enviarResumoMatinal() {
  var emailDestino = Session.getActiveUser().getEmail(); 
  var assunto = "Relatorio Matinal - Forca Consolidada";
  
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Diário de Bordo");
  var ultimaLinha = sheet.getLastRow();
  
  if (ultimaLinha < 3) return; 
  
  // getDisplayValues() lê exatamente o que os teus olhos veem na folha, como texto
  var dados = sheet.getRange(3, 1, ultimaLinha - 2, 16).getDisplayValues(); 
  
  var hojeFormatado = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "dd/MM/yyyy");
  
  var comboio = "";
  var ativosHoje = 0;
  
  for (var i = 0; i < dados.length; i++) {
    var dataCelula = dados[i][0];  // Coluna A (Data, exatamente como aparece no ecrã)
    var textoCelula = dados[i][15]; // Coluna P (Texto consolidado)
    
    // Se o texto da data incluir "04/08/2026" (mesmo que tenha horas à frente)
    if (dataCelula.includes(hojeFormatado) && textoCelula !== "") {
      comboio += textoCelula + "\n";
      ativosHoje++;
    }
  }
  
  if (ativosHoje === 0) {
    MailApp.sendEmail(emailDestino, assunto, "Bom dia!\n\nO teu sistema verificou o Diário de Bordo, mas não há ativos novos registados com a data de hoje (" + hojeFormatado + ").\n\nBoas análises!");
    return;
  }
  
  var corpoEmail = "Bom dia!\n\nCopia o bloco abaixo e cola diretamente no chat:\n\n";
  corpoEmail += "--------------------------------------------------\n";
  
  corpoEmail += "Modo Diário Ativo: Avalia os seguintes ativos da minha watchlist 'Força Consolidada'. Destaca os 3 melhores (com base no ADX > 25, RVOL > 1 e RSI > 50) e alerta para os que devo evitar (Momentum muito negativo ou RSI fraco). Na tua recomendação tática para os 3 melhores, é estritamente proibido arredondar ou usar linguagem aproximada. Extrai e lista os valores EXATOS fornecidos na string de dados para: Entrada, Stop, Take-Profit, Break-Even, Trailing e Qtd. Mantém a análise focada na minha estratégia de Math.max e trailing stop.\n\n";
  corpoEmail += comboio;
  MailApp.sendEmail(emailDestino, assunto, corpoEmail);
}

/**
 * ATENÇÃO (LIMITAÇÃO DA API TRADING 212):
 * A API da Trading 212 não suporta contas multi-moeda nem conversões automáticas 
 * flexíveis via payload externo. As ordens são sempre liquidadas na moeda principal 
 * da conta (primary currency). O envio falha com erro 400 (Insufficient funds) 
 * caso não exista saldo livre suficiente nessa moeda base específica no momento da execução.
 * 
 * Motivo para o projeto estar em pausa: Evitar a necessidade de gerir conversões 
 * manuais de moeda constantes na folha de cálculo.
 */
function enviarOrdensParaTrading212() {
  var apiKey = "36580760ZxLlBqoHUoZCxVMiUTVWlRmyCnjNn"; 
  var apiSecret = "Sl9yYO5zCmNjl9fDpXpRscXwIJY3DJFK6WN6xwrHXIw"; 
  
  var urlApi = "https://live.trading212.com/api/v0/equity/orders/limit"; 
  
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Execute Trading");
  if (!sheet) {
    SpreadsheetApp.getUi().alert("Erro", "Não foi possível encontrar a aba 'Execute Trading'.", SpreadsheetApp.getUi().ButtonSet.OK);
    return;
  }
  
  var ultimaLinha = sheet.getLastRow();
  if (ultimaLinha < 3) return;
  
  // Lemos até à Coluna P (índice 15)
  var dados = sheet.getRange(3, 1, ultimaLinha - 2, 16).getDisplayValues(); 
  var hojeFormatado = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "dd/MM/yyyy");
  
  var rawCredentials = apiKey + ":" + apiSecret;
  var encodedCredentials = Utilities.base64Encode(rawCredentials);
  
  var ordensEnviadas = 0;
  var erros = [];
  
  for (var i = 0; i < dados.length; i++) {
    var dataCelula = dados[i][0]; // Coluna A
    
    if (dataCelula.includes(hojeFormatado)) {
      var ticker = dados[i][1]; // Coluna B (ex: ORCL_US_EQ)
      var comboio = dados[i][15]; // Coluna P (o "comboio" de texto)
      
      if (ticker !== "" && comboio !== "") {
        
        // Funções auxiliares para extrair os valores de dentro da string do comboio
        var entradaMatch = comboio.match(/Entrada:\s*([\d.]+)/);
        var qtdMatch = comboio.match(/Qtd:\s*([\d.]+)/);
        
        if (entradaMatch && qtdMatch) {
          var precoEntrada = parseFloat(entradaMatch[1]);
          var quantidade = parseFloat(qtdMatch[1]);
          
          var payload = {
            "ticker": ticker,
            "quantity": quantidade,
            "limitPrice": precoEntrada,
            "timeValidity": "DAY" 
          };
          
          var options = {
            "method": "post",
            "headers": {
              "Authorization": "Basic " + encodedCredentials,
              "Content-Type": "application/json"
            },
            "payload": JSON.stringify(payload),
            "muteHttpExceptions": true 
          };
          
          try {
            var resposta = UrlFetchApp.fetch(urlApi, options);
            var statusCode = resposta.getResponseCode();
            var respostaTexto = resposta.getContentText();
            
            SpreadsheetApp.getUi().alert("Debug API - Status " + statusCode, respostaTexto, SpreadsheetApp.getUi().ButtonSet.OK);
            
            if (statusCode === 200) {
              ordensEnviadas++;
            } else {
              erros.push(ticker);
            }
          } catch (e) {
            SpreadsheetApp.getUi().alert("Exceção detetada", e.toString(), SpreadsheetApp.getUi().ButtonSet.OK);
            erros.push(ticker);
          }
        } else {
          SpreadsheetApp.getUi().alert("Erro de Formato", "Não foi possível extrair 'Entrada' ou 'Qtd' do comboio na linha " + (i + 3), SpreadsheetApp.getUi().ButtonSet.OK);
        }
      }
    }
  }
  
  var ui = SpreadsheetApp.getUi();
  if (erros.length === 0 && ordensEnviadas > 0) {
    ui.alert("API Trading 212 (Live)", "Foram submetidas com sucesso " + ordensEnviadas + " ordens limite.", ui.ButtonSet.OK);
  } else if (erros.length > 0) {
    ui.alert("Aviso API", "Ocorreram erros em " + erros.length + " ativos.", ui.ButtonSet.OK);
  } else {
    ui.alert("Sem Ação", "Não foram encontradas ordens para hoje (" + hojeFormatado + ").", ui.ButtonSet.OK);
  }
}
function verificarEEnviarParaAgente() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  
  // 1. LER A ABA "Configs" E PROCURAR A FLAG
  var abaConfig = ss.getSheetByName("Configs"); 
  if (!abaConfig) {
    console.log("Erro: Aba 'Configs' não encontrada.");
    return;
  }
  
  var dadosConfig = abaConfig.getRange("A:B").getValues();
  var linhaControlo = -1;
  var controloActivo = false;
  
  for (var i = 0; i < dadosConfig.length; i++) {
    if (dadosConfig[i][0] === "enviarRelatorioIA") {
      controloActivo = dadosConfig[i][1];
      linhaControlo = i + 1; 
      break;
    }
  }
  
  console.log("A variável enviarRelatorioIA foi encontrada na linha: " + linhaControlo);
  console.log("O valor atual da variável é: " + controloActivo);
  
  if (controloActivo !== true && controloActivo !== "true" && controloActivo !== "TRUE") {
    console.log("A flag não é TRUE. O script abortou aqui.");
    return;
  }
  
  // 2. EXTRAIR O COMBOIO DA COLUNA S
  var abaAnalise = ss.getSheetByName("Analise Compra");
  if (!abaAnalise) {
    console.log("Erro: Aba 'Analise de compra' não encontrada.");
    return;
  }
  
  var ultimaLinha = abaAnalise.getLastRow();
  console.log("A aba Analise de compra tem " + ultimaLinha + " linhas.");
  
  if (ultimaLinha < 3) {
    console.log("Erro: Aba Analise de compra tem menos de 3 linhas. Não há dados.");
    return; 
  }
  
  var rangeColunaS = abaAnalise.getRange(3, 19, ultimaLinha - 2, 1);
  var dadosS = rangeColunaS.getValues();
  
  // --- PROMPT ATUALIZADO: MODO PREDADOR E GESTOR DE RISCO IMPLACÁVEL ---
  var promptManual = "MODO DIÁRIO ATIVO - PREDADOR DE BREAKOUTS: Avalia os seguintes ativos da minha watchlist.\n" +
    "Contexto: O mercado recente está armadilhado com falsos breakouts. A tua missão é PROTEGER O CAPITAL, desconfiar do motor matemático e expor ativamente o risco de cada trade, priorizando apenas os arranques com força institucional real.\n\n" +
    "Regras Operacionais Estritas de Triagem e Ataque:\n\n" +
    "1. FILTRO CÉTICO INICIAL: Analisa apenas ativos com 'Forca Consolidada' ou 'Alerta Iminente'. Se o panorama geral for fraco (maioria com ADX < 25 e RVOL baixo), REJEITA TUDO e inicia a resposta com: [MERCADO CHOPPY - FICA DE FORA HOJE].\n" +
    "2. OS 3 MELHORES ALVOS: Se existirem oportunidades reais, foca-te num máximo de 3. TÍTULO: [Ticker] - [Nome da Empresa].\n" +
    "3. ANÁLISE DE VULNERABILIDADE E POTENCIAL (CRÍTICO):\n" +
    "   Para cada alvo, cruza os dados e aplica as seguintes bandeiras táticas:\n" +
    "   - REGRA DA MOLA (MM20): Se 'Dist MM20' > 2.5%, alerta [AVISO: PREÇO ESTICADO - Risco de Pullback].\n" +
    "   - COMPRESSÃO (ATR vs RVOL): Se o RVOL for > 1.5 e o Momentum for sólido, marca como [POTENCIAL DE COMPRESSÃO] (alta prioridade).\n" +
    "   - EXAUSTÃO: Se o RSI for > 70 mas o Momentum for baixo (< 1.0) ou RVOL < 1.3, alerta [AVISO DE EXAUSTÃO - Sem Combustível].\n" +
    "   - BARREIRAS INSTITUCIONAIS: Se o Preço de Entrada ou Take-Profit estiver a menos de 1% de um número redondo maior (ex: 50.00, 100.00, 200.00), alerta [PAREDE INSTITUCIONAL - Risco de rejeição].\n" +
    "   - ATIVOS ERRÁTICOS: Se o ATR for superior a 5% do Preço atual, alerta [ATIVO ERRÁTICO - Alta Volatilidade] e recomenda evitar o risco de slippage.\n" +
    "   - RECOMENDAÇÃO DE LOTE: Com base no exposto, dita se a entrada deve ser de 'Lote Completo' ou 'Lote Reduzido a 50%'.\n" +
    "4. TÁTICA DE EXECUÇÃO:\n" +
    "   - GAPS DE ABERTURA: Lembra sempre o trader com a frase 'Se a ação abrir em Gap > 1% acima da entrada prevista, ABORTA A MISSÃO, não persigas o preço.'\n" +
    "   - GESTÃO DE LUCRO: Se o ADX for > 35, instrui: '[TENDÊNCIA EXTREMA] Ignora o TP, gere pelo Trailing Stop'. Se ADX < 30, instrui: '[TENDÊNCIA MODERADA] Respeita o Take-Profit fixo.'\n" +
    "5. RISCOS DE CALENDÁRIO E CORRELAÇÃO:\n" +
    "   - EARNINGS: Adiciona o aviso '⚠️ ALERTA MANUAL: Verifica se há apresentação de resultados nos próximos 3 dias. Se sim, ABORTA.'\n" +
    "   - SEXTA-FEIRA: Se a data da análise for uma Sexta-Feira, adiciona '[ALERTA DE SEXTA-FEIRA] - Probabilidade de recolha de lucros à tarde. Reduz o lote ou aperta os critérios de entrada.'\n" +
    "   - CORRELAÇÃO: Se os 3 ativos forem do mesmo setor, emite '[AVISO DE CORRELAÇÃO] - Risco concentrado. Escolhe apenas o ativo com o melhor Momentum.'\n" +
    "6. EXTRACÇÃO EXATA (INTOCÁVEL): Lista os valores EXATOS fornecidos (Entrada, Stop, Take-Profit, Break-Even, Trailing, Qtd). NUNCA recalcules ou modifiques estes números.\n" +
    "7. REFERÊNCIA: Cola a linha original do 'comboio' de dados correspondente abaixo de cada ativo.\n" +
    "8. SAÚDE DO MERCADO E LEI DA MEIA-HORA:\n" +
    "   Termina o relatório com o estado clínico do mercado ('Ex: 80% das ações a Observar, dinheiro institucional a lateralizar') E inclui SEMPRE este mandato final a negrito:\n" +
    "   **'TÁTICA DE EXECUÇÃO OBRIGATÓRIA: Não executar ordens antes das 15h00. Deixar a volatilidade inicial queimar os amadores e confirmar a verdadeira direção institucional.'**\n\n" +
    "--------------------------------------------------\n" +
    "DADOS DOS ATIVOS (COMBOIO):\n\n";
  
  var textoFinal = promptManual;
  var linhasAdicionadas = 0;
  
  for (var j = 0; j < dadosS.length; j++) {
    var linhaComboio = dadosS[j][0];
    if (linhaComboio && linhaComboio.toString().trim() !== "") {
      textoFinal += linhaComboio + "\n";
      linhasAdicionadas++;
    }
  }
  
  console.log("Foram adicionadas " + linhasAdicionadas + " linhas válidas ao email.");
  
  // 3. ENVIAR O EMAIL E RESETAR A FLAG
  if (linhasAdicionadas > 0) {
    var EMAIL_DESTINO = "pintovilanova.online@gmail.com"; 
    var ASSUNTO_EXATO = "tradingRelatorioIA"; 
    
    MailApp.sendEmail(EMAIL_DESTINO, ASSUNTO_EXATO, textoFinal);
    abaConfig.getRange(linhaControlo, 2).setValue(false); 
    console.log("Sucesso! Email enviado com o prompt e a regra do comboio incluída, e flag desativada.");
  } else {
    console.log("Erro: Não há linhas preenchidas na coluna S para enviar.");
  }
  dispararAgenteGitHubViaAPI();
}
function ligarProcessarTudo() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Configs"); // Nome da aba visível na imagem
  
  // A célula B3 corresponde à linha 3, coluna 2 (onde está o "processarTudo")
  var range = sheet.getRange("B3"); 
  
  range.setValue(true);
  
  Logger.log("Flag 'processarTudo' (B3) colocada a TRUE às " + new Date());
}
function ativarEnviarRelatorioIA() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Configs");
  if (!sheet) return;
  
  var dados = sheet.getRange("A:B").getValues();
  for (var i = 0; i < dados.length; i++) {
    if (dados[i][0] === "enviarRelatorioIA") {
      sheet.getRange(i + 1, 2).setValue(true);
      Logger.log("Flag 'enviarRelatorioIA' ativada para o novo ciclo.");
      break;
    }
  }
}

function instalarPipelineCompleto() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  
  // 1. Limpa APENAS os gatilhos associados às funções para evitar duplicados
  var funcoesAlvo = [
    "limparCheckboxes", 
    "ativarConfigProcessarLote", 
    "ligarProcessarTudo", 
    "ativarEnviarRelatorioIA",
    "processarLoteItemsShort", 
    "verificarEEnviarParaAgente", 
    "resetConfigProcessarLote",
    "prepararExecucaoExata"
  ];
  
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) {
    if (funcoesAlvo.includes(triggers[i].getHandlerFunction())) {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }
  
  // 2. Agenda a Sequência Completa (Fuso Horário de Lisboa)
  var tz = "Europe/Lisbon";
  
  // --- FASE 1 & 2: MADRUGADA E MANHÃ ---
  // 01:00 - Limpar todas as checkboxes
  ScriptApp.newTrigger("limparCheckboxes")
    .timeBased().everyDays(1).atHour(1).nearMinute(0).inTimezone(tz).create();
    
  // 01:05 a 01:08 - Ativar todas as flags de configuração necessárias
  ScriptApp.newTrigger("ativarConfigProcessarLote")
    .timeBased().everyDays(1).atHour(1).nearMinute(5).inTimezone(tz).create();
    
  ScriptApp.newTrigger("ligarProcessarTudo")
    .timeBased().everyDays(1).atHour(1).nearMinute(7).inTimezone(tz).create();
    
  ScriptApp.newTrigger("ativarEnviarRelatorioIA")
    .timeBased().everyDays(1).atHour(1).nearMinute(8).inTimezone(tz).create();
    
  // =========================================================================
  // PROCESSADOR CONTÍNUO: Corre a cada 15 minutos até bater nas 06:00
  // =========================================================================
  ScriptApp.newTrigger("processarLoteItemsShort")
    .timeBased().everyMinutes(15).create();
    
  // =========================================================================
  // GATILHO DA INTELIGÊNCIA ARTIFICIAL E GITHUB ACTIONS
  // TÁTICA ANTI-TRÁFEGO: Alterado das 05h30 para as 05h45 (minuto quebrado)
  // =========================================================================
  ScriptApp.newTrigger("verificarEEnviarParaAgente")
    .timeBased().everyDays(1).atHour(5).nearMinute(45).inTimezone(tz).create();
    
  // 06:00 - Fazer o reset final das flags de configuração para fechar o ciclo da manhã
  // ISTO ATUA COMO "KILL SWITCH" PARA O TRIGGER DE 15 EM 15 MINUTOS
  ScriptApp.newTrigger("resetConfigProcessarLote")
    .timeBased().everyDays(1).atHour(6).nearMinute(0).inTimezone(tz).create();
    
  // --- FASE 3: INTRADAY ---
  // 08:00 - O sistema acorda, verifica se é dia útil, e espeta o gatilho cirúrgico exato para as 15:30
  ScriptApp.newTrigger("prepararExecucaoExata")
    .timeBased().everyDays(1).atHour(8).nearMinute(0).inTimezone(tz).create();
    
  Logger.log("Pipeline completo atualizado e instalado com sucesso! A fugir à hora de ponta.");
}
function guardarTokenGitHub() {
  PropertiesService.getScriptProperties().setProperty("GITHUB_PAT", "AQUI O GIT TOKEN");
}
function dispararAgenteGitHubViaAPI() {
  var owner = "pintovilanova";       // Substitui pelo teu nome de utilizador no GitHub
  var repo = "agente-trading";              // O nome exato do teu repositório
  
  // Lê o token guardado no passo anterior
  var token = PropertiesService.getScriptProperties().getProperty("GITHUB_PAT");
  
  if (!token) {
    Logger.log("Erro: Token do GitHub não encontrado nas propriedades.");
    return;
  }
  
  var url = "https://api.github.com/repos/" + owner + "/" + repo + "/actions/workflows/agente.yml/dispatches";
  
  var payload = {
    "ref": "main" // Confirma se a tua branch principal se chama "main" ou "master"
  };
  
  var options = {
    "method": "post",
    "headers": {
      "Authorization": "Bearer " + token,
      "Accept": "vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28"
    },
    "payload": JSON.stringify(payload),
    "muteHttpExceptions": true
  };
  
  var response = UrlFetchApp.fetch(url, options);
  var respostaCodigo = response.getResponseCode();
  
  if (respostaCodigo === 204) {
    Logger.log("Sucesso! O GitHub Actions foi acionado com sucesso via API.");
  } else {
    Logger.log("Erro ao acionar o GitHub (" + respostaCodigo + "): " + response.getContentText());
  }
}



// ==========================================
// MOTOR HÍBRIDO (WEBHOOK PARA O GITHUB: US + EUROPA)
// ==========================================

// 1. O Python chama o GET para ler a Watchlist
function doGet(e) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  
  // Se o Python enviar o nome da aba (ex: ?aba=Europa), usa essa. 
  // Se não enviar nada (que é o caso do teu script US atual), usa "Analise Compra" por defeito.
  var nomeAba = (e.parameter && e.parameter.aba) ? e.parameter.aba : "Analise Compra";
  var sheet = ss.getSheetByName(nomeAba);
  
  if (!sheet) {
    return ContentService.createTextOutput(JSON.stringify({"erro": "Aba '" + nomeAba + "' nao encontrada"}))
                         .setMimeType(ContentService.MimeType.JSON);
  }
  
  var ultimaLinha = sheet.getLastRow();
  var ativos = [];
  
  if (ultimaLinha >= 3) {
    // Lê as colunas E (Ticker) e F (Nome) a partir da linha 3
    var valores = sheet.getRange(3, 5, ultimaLinha - 2, 2).getValues();
    
    for (var i = 0; i < valores.length; i++) {
      var t = valores[i][0]; // Ticker
      var n = valores[i][1]; // Nome
      if (t && t.toString().trim() !== "") {
        ativos.push({
          "ticker": t.toString().trim(),
          "nome": n ? n.toString().trim() : "N/A"
        });
      }
    }
  }
  
  return ContentService.createTextOutput(JSON.stringify(ativos))
                       .setMimeType(ContentService.MimeType.JSON);
}

// 2. O Python envia os resultados via POST
function doPost(e) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var payload = JSON.parse(e.postData.contents);
  
  // ==========================================================
  // LÓGICA UNIFICADA: ATUALIZAÇÃO POR COLUNAS NA ABA INDICADA
  // ==========================================================
  if (payload.acao === "atualizar_colunas_todas") {
    // Recebe o nome da aba enviada pelo Python (ex: "Analise Compra" para os EUA ou "Analise Compra EU" para a Europa)
    var nomeAba = payload.aba || "Analise Compra"; 
    var sheet = ss.getSheetByName(nomeAba);
    
    if (!sheet) {
      return ContentService.createTextOutput(JSON.stringify({"status": "erro", "mensagem": "Aba '" + nomeAba + "' nao encontrada"}))
                           .setMimeType(ContentService.MimeType.JSON);
    }
    
    var dados = payload.dados;
    var dataRange = sheet.getDataRange();
    var values = dataRange.getValues();
    
    for (var i = 0; i < dados.length; i++) {
      var d = dados[i];
      // Procura o Ticker na Coluna E (índice 4)
      for (var row = 1; row < values.length; row++) {
        if (values[row][4] === d.ticker) {
          // Grava valores nas respetivas colunas (G=7, K=11, L=12, M=13, N=14, Q=17, S=19)
          sheet.getRange(row + 1, 7).setValue(d.preco);
          sheet.getRange(row + 1, 11).setValue(d.momentum);
          sheet.getRange(row + 1, 12).setValue(d.rsi);
          sheet.getRange(row + 1, 13).setValue(d.adx);
          sheet.getRange(row + 1, 14).setValue(d.atr);
          sheet.getRange(row + 1, 17).setValue(d.time);
          sheet.getRange(row + 1, 19).setValue(d.comboio);
          break;
        }
      }
    }
    return ContentService.createTextOutput(JSON.stringify({"status": "sucesso"}))
                         .setMimeType(ContentService.MimeType.JSON);
  }
  
  // Caso venha num formato antigo descontinuado
  return ContentService.createTextOutput(JSON.stringify({"status": "erro", "mensagem": "Ação desconhecida"}))
                       .setMimeType(ContentService.MimeType.JSON);
}
