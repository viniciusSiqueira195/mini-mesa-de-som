# Mini Mesa de Som

Mesa de som virtual para Windows, simples de operar pelo teclado e construída
com acessibilidade como requisito central. A Mini Mesa recebe qualquer microfone
reconhecido pelo sistema, aplica efeitos em tempo real e envia o resultado para
um cabo de áudio virtual usado pelo Discord, TeamTalk, WhatsApp ou outro programa.

> Projeto experimental em desenvolvimento ativo. A interface e as preferências
> já são utilizáveis, mas ainda não há uma versão empacotada para distribuição.

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
- Retorno da própria voz sem depender da opção “Escutar este dispositivo” do
  Windows.
- Troca do retorno enquanto a mesa está ativa sem interromper a saída virtual.
- Minimização para a bandeja do sistema sem interromper o áudio.
- Preferências persistentes em JSON com recuperação de configuração inválida.
- Buffer limitado, margem de volume e suavização de descontinuidades para evitar
  atraso crescente, saturação e estalos.

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

Quando **Ouvir retorno** está marcado, o mesmo áudio processado também segue para
o fone escolhido. Use fones de ouvido para evitar microfonia.

## Requisitos

- Windows 10 ou 11.
- Python 3.11 ou mais recente para desenvolvimento.
- Um cabo de áudio virtual, como o VB-CABLE.
- Fones de ouvido recomendados para usar o retorno.

## Instalação para desenvolvimento

No PowerShell, dentro da pasta do projeto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m mini_mesa
```

Depois da instalação, também é possível iniciar com:

```powershell
mini-mesa
```

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
boa parte ou todo o efeito; use **Ouvir retorno** para avaliá-lo diretamente.

## Atalhos

- `Alt+M`: escolher o microfone.
- `Alt+S`: escolher a saída virtual.
- `Alt+O`: ativar ou desativar o retorno.
- `Alt+T`: escolher o dispositivo de retorno.
- `Alt+E`: ativar ou desativar o reverb.
- `Alt+R`: ajustar o nível de reverb.
- `Alt+D`: ativar ou desativar a redução de ruído.
- `Alt+P`: ativar ou desativar o áudio espacial.
- `Alt+I`: ajustar a posição espacial da voz.
- `Alt+A`: ativar ou desativar a mesa.
- `Alt+C`: encerrar o programa.
- `F5`: atualizar os dispositivos.

## Preferências

As preferências são gravadas automaticamente em:

```text
%APPDATA%\Mini Mesa de Som Teste\preferences.json
```

O arquivo inclui dispositivos, retorno e estados dos efeitos. A gravação usa um
arquivo temporário antes da substituição, reduzindo o risco de corrupção. Se o
JSON estiver inválido ou um dispositivo desaparecer, a mesa usa valores seguros
e seleciona uma alternativa disponível.

## Compatibilidade de áudio no Windows

O Windows pode anunciar o mesmo dispositivo por várias APIs. A Mini Mesa agrupa
nomes duplicados e tenta WDM-KS, WASAPI, DirectSound e MME conforme a finalidade
da rota. O retorno prefere WASAPI compartilhado porque diversas saídas WDM-KS
não aceitam captura, cabo virtual e monitoramento simultâneos.

Com retorno, a mesa começa com blocos de 256 amostras; sem retorno, usa 512. Dois
blocos são preparados antes das saídas começarem. O buffer permanece limitado e
suaviza faltas ou descartes de áudio para evitar estalos e atraso crescente.

## Testes

```powershell
python -m unittest discover -s tests -v
```

A suíte valida configurações, preferências, ciclo do motor, continuidade dos
buffers, roteamento dinâmico e integração do redutor de ruído sem acessar os
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
- Presets de efeitos.
- Empacotamento para usuários sem ambiente Python.

## Créditos técnicos

- [Pedalboard](https://github.com/spotify/pedalboard), usado para reverb e
  limitação.
- [RNNoise](https://github.com/xiph/rnnoise), usado para redução neural de ruído.
- [MIT KEMAR HRTF](https://sound.media.mit.edu/resources/KEMAR.html), medições
  binaurais de Bill Gardner e Keith Martin usadas pelo áudio espacial.
- [PortAudio](https://www.portaudio.com/) por meio do sounddevice.
- [wxPython](https://wxpython.org/) na interface nativa.
