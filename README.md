# Mini Mesa de Som

Mesa de som virtual para Windows, simples de operar pelo teclado e construída
com acessibilidade como requisito central. A Mini Mesa recebe qualquer microfone
reconhecido pelo sistema, aplica efeitos em tempo real e envia o resultado para
um cabo de áudio virtual usado pelo Discord, TeamTalk, WhatsApp ou outro programa.

> Projeto experimental em desenvolvimento ativo. A interface, as preferências e
> o instalador Windows já são utilizáveis, mas a versão ainda precisa de testes
> em diferentes computadores e interfaces de áudio.

## Instalação rápida

Baixe `MiniMesaDeSom-Setup-0.1.0.exe` na página da
[versão mais recente](https://github.com/viniciusSiqueira195/mini-mesa-de-som/releases/latest)
e execute o instalador. Ele pode instalar opcionalmente o VB-CABLE oficial,
necessário para enviar o áudio processado ao TeamTalk, Discord ou outro programa.

Na primeira abertura, uma mensagem acessível explica o fluxo básico e como
configurar as duas pontas do cabo virtual.

## Por que este projeto existe

Mesas virtuais populares costumam usar interfaces visuais difíceis ou
impossíveis de operar com leitores de tela. Este projeto usa controles nativos do
wxPython, nomes acessíveis, atalhos de teclado e mensagens de estado pensadas
para funcionar bem com NVDA.

O aplicativo não depende da marca do microfone. FIFINE AM8, Zeus X e outras
entradas reconhecidas pelo Windows podem ser selecionadas diretamente.

## Recursos atuais

- Interface nativa acessível com NVDA e operação completa pelo teclado.
- Seleção independente do microfone, cabo virtual e dispositivo de retorno.
- Reverb ajustado por um único controle simples de 0 a 100.
- Redução neural de ruído RNNoise, opcional e executada localmente.
- Áudio espacial binaural com HRTF real e posição horizontal de −180° a +180°.
- Reverb e redução de ruído utilizáveis separadamente ou em conjunto.
- Retorno local experimental, mantido aberto para testes e contribuições.
- Minimização para a bandeja do sistema sem interromper o áudio.
- Preferências persistentes em JSON com recuperação de configuração inválida.
- Verificação automática de novas versões pelo GitHub, com download acessível e
  validação SHA-256 antes da instalação.
- Buffer limitado, margem de volume e suavização de descontinuidades para evitar
  atraso crescente, saturação e estalos.
- Preferência por WASAPI compartilhado para coexistir com aplicativos de chamada,
  mantendo WDM-KS, DirectSound e MME como alternativas automáticas.
- Filas independentes: congestionamentos no retorno descartam somente a cópia
  local e não bloqueiam o áudio enviado ao cabo virtual.

## Fluxo do áudio

```text
Microfone físico
    -> redução de ruído opcional
    -> reverb opcional
    -> HRTF binaural opcional
    -> limitador
    -> cabo de áudio virtual
    -> Discord, TeamTalk, WhatsApp ou outro aplicativo
```

Quando **Ouvir retorno** está marcado, uma cópia do áudio processado também
segue para o fone escolhido. Use fones de ouvido para evitar microfonia. Esse
retorno ainda é experimental e pode apresentar estalos em algumas combinações
de dispositivos; a rota do cabo virtual permanece isolada para que isso não
interrompa gravações e chamadas.

## Requisitos

- Windows 10 ou 11.
- Python 3.11 ou mais recente para desenvolvimento.
- Um cabo de áudio virtual, como o VB-CABLE.
- Fones de ouvido recomendados para usar o retorno experimental.

## Instalação para desenvolvimento

No PowerShell, dentro da pasta do projeto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m mini_mesa
```

Depois da instalação, também é possível iniciar com:

```powershell
mini-mesa
```

## Instalador para Windows

O instalador coloca o aplicativo em `%LOCALAPPDATA%\Programs`, portanto não
precisa de privilégios administrativos para instalar a Mini Mesa. A etapa
opcional do VB-CABLE é marcada por padrão e solicita elevação somente se o
driver realmente precisar ser instalado.

Antes de instalar o driver, o processo guarda separadamente os dispositivos
padrão de reprodução, comunicação, gravação e gravação para comunicação. Depois
ele restaura os quatro. Se o VB-CABLE oficial já estiver presente — inclusive
com endpoints desativados — a instalação do driver é ignorada automaticamente.
VoiceMeeter e outros produtos da VB-Audio não são confundidos com o cabo exigido
pela mesa.

O VB-CABLE é um produto donationware da VB-Audio, obtido de
[vb-cable.com](https://vb-cable.com/). O instalador da Mini Mesa não altera os
dispositivos padrão de propósito e não remove o cabo na desinstalação, pois ele
pode estar sendo usado por outros programas. A instalação inicial do driver
pode exigir reinicialização do Windows.

### Gerando o instalador

Instale o Inno Setup 6 e prepare o ambiente uma vez:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[build]"
winget install --id JRSoftware.InnoSetup --exact
```

Depois execute:

```powershell
.\tools\build_installer.ps1
```

O script roda os testes, empacota o programa com PyInstaller, baixa os pacotes
oficiais do VB-CABLE e AudioDeviceCmdlets com verificação SHA-256 e gera
`installer-output\MiniMesaDeSom-Setup-0.1.0.exe`. O aplicativo é empacotado em
uma pasta interna para dar mais estabilidade às bibliotecas nativas de áudio;
para o usuário, a entrega continua sendo um único instalador.

## Atualizações

A versão instalada verifica em segundo plano a release estável mais recente no
GitHub. Quando houver uma versão nova, um diálogo acessível permite baixar e
instalar a atualização. O arquivo só é executado depois de sua assinatura
SHA-256 ser comparada com a assinatura publicada junto da release.

Também é possível iniciar a verificação manualmente em **Ajuda > Verificar
atualizações**. O atualizador preserva as preferências e não reinstala o driver
VB-CABLE durante atualizações comuns.

## Configuração do cabo virtual

Com o VB-CABLE como exemplo:

1. Em **Microfone de entrada**, escolha o microfone físico.
2. Em **Saída virtual**, escolha `CABLE Input`.
3. No aplicativo de conversa, escolha `CABLE Output` como microfone.
4. Marque os efeitos desejados e pressione **Ativar mesa**.

**Desativar mesa** interrompe somente a transmissão e mantém a janela aberta.
**Encerrar programa** para o áudio e fecha o aplicativo.

## Bandeja do sistema

Ao minimizar a janela normalmente ou pressionar `Windows+M`, a Mini Mesa some da
barra de tarefas e continua funcionando na bandeja do sistema. Para restaurar
pelo teclado, pressione `Windows+B`, localize **Mini Mesa de Som** com as setas e
pressione `Enter`. O menu do ícone também oferece **Abrir Mini Mesa de Som** e
**Encerrar programa**.

Se o Windows não conseguir criar o ícone, a janela permanece apenas minimizada
na barra de tarefas para nunca deixar o programa inacessível. Uma falha de áudio
restaura a janela automaticamente antes de mostrar a mensagem de erro.

## Efeitos

### Reverb

O controle **Nível de reverb** combina internamente a quantidade do efeito, o
tamanho do ambiente simulado e a duração da cauda. A voz limpa e o efeito são
misturados com margem automática de volume. O reverb pode ser alterado enquanto
a mesa está funcionando.

### Redução de ruído

O RNNoise reduz ruídos de fundo antes do reverb e não envia áudio para a
internet. A opção fica desmarcada por padrão, requer processamento em 48 kHz e
adiciona um quadro fixo de 10 milissegundos. Para preservar a continuidade do
áudio, altere essa opção com a mesa desativada.

### Áudio espacial binaural

O efeito espacial usa respostas de impulso medidas no manequim acústico KEMAR
do MIT. Um único controle posiciona a voz ao redor da cabeça: valores negativos
movem para a esquerda, `0` fica à frente e valores positivos movem para a
direita. As posições intermediárias são interpoladas e qualquer mudança é
suavizada para evitar cliques. O efeito pode ser ligado, desligado e movido
enquanto a mesa está ativa.

O resultado foi feito para audição em fones e precisa permanecer estéreo até o
ouvinte. Aplicativos de conversa que transformem o microfone em mono eliminarão
boa parte ou todo o efeito. Faça uma gravação estéreo no aplicativo de destino
para avaliá-lo ou use o retorno experimental.

## Atalhos

- `Alt+M`: escolher o microfone.
- `Alt+S`: escolher a saída virtual.
- `Alt+O`: ativar ou desativar o retorno experimental.
- `Alt+T`: escolher o dispositivo de retorno.
- `Alt+E`: ativar ou desativar o reverb.
- `Alt+R`: ajustar o nível de reverb.
- `Alt+D`: ativar ou desativar a redução de ruído.
- `Alt+P`: ativar ou desativar o áudio espacial.
- `Alt+I`: ajustar a posição espacial da voz.
- `Alt+A`: ativar ou desativar a mesa.
- `Alt+C`: encerrar o programa.
- `F5`: atualizar os dispositivos.
- `Alt+J`, depois `A`: abrir Ajuda e verificar atualizações.

## Preferências

As preferências são gravadas automaticamente em:

```text
%APPDATA%\Mini Mesa de Som Teste\preferences.json
```

O arquivo inclui os dispositivos, o retorno e os estados dos efeitos. A gravação usa um
arquivo temporário antes da substituição, reduzindo o risco de corrupção. Se o
JSON estiver inválido ou um dispositivo desaparecer, a mesa usa valores seguros
e seleciona uma alternativa disponível.

## Compatibilidade de áudio no Windows

O Windows pode anunciar o mesmo dispositivo por várias APIs. A Mini Mesa agrupa
nomes duplicados e prioriza WDM-KS na rota entre o microfone e o cabo virtual,
preservando o caminho que se mostrou estável no instalador anterior. WASAPI,
DirectSound e MME permanecem como alternativas. O retorno físico é tratado
separadamente e prefere WASAPI compartilhado.

O retorno local é experimental. Nos testes, abrir simultaneamente o cabo virtual
e uma saída física ainda produziu estalos em algumas combinações de dispositivos
com relógios independentes. Seu buffer é separado e não bloqueante: o cabo
virtual recebe cada bloco primeiro e, se o retorno estiver congestionado, apenas
a cópia local é descartada. Assim, o defeito conhecido permanece disponível para
estudo sem atrasar a rota usada por gravações e aplicativos de conversa.

## Testes

```powershell
python -m pip install -e ".[test]"
python -m pytest
```

A suíte valida configurações, preferências, ciclo do motor, continuidade dos
buffers, isolamento entre retorno e gravação e integração do redutor de ruído sem acessar os
microfones físicos.

## Arquitetura

- `mini_mesa/ui.py`: janela wxPython e comportamento acessível.
- `mini_mesa/audio_engine.py`: dispositivos, ciclo da transmissão e cadeia DSP.
- `mini_mesa/noise_reduction.py`: adaptação de streaming e RNNoise nativo.
- `mini_mesa/spatial_audio.py`: convolução binaural, interpolação e transições.
- `mini_mesa/preferences.py`: persistência JSON atômica.
- `mini_mesa/settings.py`: mapeamento seguro dos controles de efeito.
- `tests/`: testes automatizados do motor e das configurações.

## Próximos passos

- Testes auditivos do HRTF em diferentes cabos virtuais e aplicativos.
- Medidor de nível acessível.
- Assinatura digital do executável e do instalador.
- Testes do instalador em máquinas limpas.

## Licença

O código da Mini Mesa de Som é distribuído sob a licença MIT. Dependências,
dados HRTF e o VB-CABLE permanecem sujeitos às licenças de seus respectivos
autores. Consulte [LICENSE](LICENSE) e os avisos incluídos no projeto.

## Créditos técnicos

- [Pedalboard](https://github.com/spotify/pedalboard), usado para reverb e
  limitação.
- [RNNoise](https://github.com/xiph/rnnoise), usado para redução neural de ruído.
- [MIT KEMAR HRTF](https://sound.media.mit.edu/resources/KEMAR.html), medições
  binaurais de Bill Gardner e Keith Martin usadas pelo áudio espacial.
- [PortAudio](https://www.portaudio.com/) por meio do sounddevice.
- [wxPython](https://wxpython.org/) na interface nativa.
- [VB-CABLE](https://vb-cable.com/), cabo virtual donationware opcional incluído
  no instalador.
