# Mini Mesa de Som

Mesa de som virtual para Windows, simples de operar pelo teclado e construída
com acessibilidade como requisito central. A Mini Mesa recebe qualquer microfone
reconhecido pelo sistema, aplica efeitos em tempo real e envia o resultado para
um cabo de áudio virtual usado pelo Discord, TeamTalk, WhatsApp ou outro programa.

> Projeto experimental em desenvolvimento ativo. A interface, as preferências e
> o instalador Windows já são utilizáveis, mas a versão ainda precisa de testes
> em diferentes computadores e interfaces de áudio.

## Instalação rápida

Baixe `MiniMesaDeSom-Setup-0.2.0.exe` na página da
[versão mais recente](https://github.com/viniciusSiqueira195/mini-mesa-de-som/releases/latest)
e execute o instalador. Ele pode instalar opcionalmente o VB-CABLE oficial,
necessário para enviar o áudio processado ao TeamTalk, Discord ou outro programa.

Na primeira abertura, uma mensagem acessível explica o fluxo básico, como
configurar as duas pontas do cabo virtual e que `F1` abre a ajuda completa.

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
- Modificador de voz com presets de pitch, harmonização, auto-tune e vocoder.
- Efeitos criativos, modulações, ambientes e controles de intensidade com
  bypass real em 0%.
- Compressor, equalizador, noise gate, de-esser, expander, ganho automático e
  filtro de plosivas.
- Soundboard com cinco efeitos pessoais, arquivo personalizado, volume e
  ducking durante a fala.
- Redução neural de ruído RNNoise, opcional e executada localmente.
- Áudio espacial binaural 3D por coordenadas X, Y e Z, com movimento automático.
- Soundboard acessível com tiro, palmas, fala e buzina misturados na rota virtual.
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
    -> modificador e efeitos de voz opcionais
    -> soundboard / efeitos sonoros
    -> reverb opcional
    -> HRTF binaural opcional
    -> limitador
    -> cabo de áudio virtual
    -> Discord, TeamTalk, WhatsApp ou outro aplicativo
```

Os efeitos do soundboard entram na mesma rota antes do limitador. Eles chegam ao
aplicativo de conversa e ao retorno sem abrir outro dispositivo de áudio.

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
`installer-output\MiniMesaDeSom-Setup-0.2.0.exe`. O aplicativo é empacotado em
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

O RNNoise reduz ruídos de fundo antes dos efeitos e não envia áudio para a
internet. A opção fica desmarcada por padrão, requer processamento em 48 kHz e
adiciona um quadro fixo de 10 milissegundos. Quando essa opção é alterada com a
mesa ativa, a rota é reiniciada de forma controlada para renegociar a taxa.

### Áudio espacial binaural

O efeito espacial usa respostas de impulso medidas no manequim acústico KEMAR
do MIT. Três coordenadas posicionam a voz: X controla esquerda e direita, Y
controla baixo e cima e Z controla trás e frente. Cada eixo vai de `-100` a
`100`. As respostas HRTF reais cuidam do plano horizontal e pistas espectrais
suaves diferenciam cima e baixo.

O movimento automático percorre continuamente os três eixos. Sua velocidade
pode ser ajustada de `1` a `100`, e o movimento usa o próprio relógio do fluxo
de áudio para permanecer estável. Posições intermediárias e mudanças manuais
são suavizadas para evitar cliques, inclusive enquanto a mesa está ativa.

O resultado foi feito para audição em fones e precisa permanecer estéreo até o
ouvinte. Aplicativos de conversa que transformem o microfone em mono eliminarão
boa parte ou todo o efeito. Faça uma gravação estéreo no aplicativo de destino
para avaliá-lo ou use o retorno experimental.

### Soundboard acessível

O menu **Efeitos** abre uma janela separada para não ocupar a interface principal.
Use as setas para escolher um som, `Enter` para reproduzir, `Espaço` para parar
todos e `Escape` para fechar. Os atalhos diretos funcionam com a janela fechada,
desde que a Mini Mesa esteja em foco e ativa.

Os efeitos podem tocar simultaneamente e entram na mesma cadeia da voz. Portanto,
reverb e áudio espacial 3D ativos também processam todos os sons do soundboard.

O pacote pessoal instalado neste computador oferece um tiro de pistola, uma
rajada de metralhadora, palmas, uma air horn de DJ com quatro segundos e a frase
"Sensacional!" de Mano Brown. Esses arquivos ficam em
`%APPDATA%\Mini Mesa de Som\sounds`, fora do Git e disponíveis sem internet.
As palmas vêm do Mixkit, o tiro e a air horn vêm do Orange Free Sounds e a voz
foi obtida no Myinstants. O pacote é usado apenas para diversão pessoal e não é
distribuído junto com o programa. A procedência completa fica registrada em
`tools/PERSONAL_SOUND_PACK_NOTICE.txt`.

## Atalhos

- `Alt+M`: escolher o microfone.
- `Alt+S`: escolher a saída virtual.
- `Alt+O`: ativar ou desativar o retorno experimental.
- `Alt+T`: escolher o dispositivo de retorno.
- `Alt+E`: ativar ou desativar o reverb.
- `Alt+R`: ajustar o nível de reverb.
- `Alt+D`: ativar ou desativar a redução de ruído.
- `Alt+P`: ativar ou desativar o áudio espacial.
- `Alt+X`, `Alt+Y` e `Alt+Z`: ajustar as coordenadas espaciais.
- `Alt+U`: ativar ou desativar o movimento automático.
- `Alt+V`: ajustar a velocidade do movimento espacial.
- `Ctrl+Shift+E`: abrir o soundboard acessível.
- `Ctrl+1`: reproduzir pistola.
- `Ctrl+2`: reproduzir metralhadora.
- `Ctrl+3`: reproduzir palmas.
- `Ctrl+4`: reproduzir buzina de DJ por até quatro segundos.
- `Ctrl+5`: reproduzir "Sensacional!" de Mano Brown.
- `Ctrl+0`: interromper todos os efeitos.
- `Alt+A`: ativar ou desativar a mesa.
- `Alt+C`: encerrar o programa.
- `F5`: atualizar os dispositivos.
- `F1`: abrir a ajuda acessível com apresentação, atalhos e créditos.
- `F2`: reproduzir metralhadora; `F3`: palmas; `F4`: buzina de DJ.
- `F6`: escolher uma vinheta de áudio personalizada.
- `Alt+J`, depois `A`: abrir Ajuda e verificar atualizações.

Na ajuda aberta por `F1`, leitores de tela podem usar `H` e `Shift+H` para
navegar entre os cabeçalhos, ou as teclas `1` a `6` para navegar por nível. O
botão **Usar modo de texto contínuo** preserva a leitura tradicional com as
setas, Page Up e Page Down.

## Preferências

As preferências são gravadas automaticamente em:

```text
%APPDATA%\Mini Mesa de Som\preferences.json
```

O arquivo inclui os dispositivos, o retorno e os estados dos efeitos. A gravação usa um
arquivo temporário antes da substituição, reduzindo o risco de corrupção. Se o
JSON estiver inválido ou um dispositivo desaparecer, a mesa usa valores seguros
e seleciona uma alternativa disponível.

Ao atualizar uma instalação antiga, as preferências e os efeitos pessoais da
pasta `%APPDATA%\Mini Mesa de Som Teste` continuam sendo reconhecidos e as
preferências são migradas automaticamente para o novo nome.

## Compatibilidade de áudio no Windows

O Windows pode anunciar o mesmo dispositivo por várias APIs. A Mini Mesa agrupa
nomes duplicados e prioriza WASAPI compartilhado na rota entre o microfone e o
cabo virtual. WDM-KS, DirectSound e MME permanecem como alternativas
automáticas. O retorno físico é tratado separadamente e também prefere WASAPI.

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
- `mini_mesa/soundboard.py`: carregamento, reamostragem e mixagem dos efeitos.
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

Desenvolvido originalmente por [Vinicius Siqueira](https://github.com/viniciusSiqueira195).
Colaboração de [Paulo Santesso](https://github.com/paulosantesso1), responsável
por melhorias no motor de áudio em tempo real, efeitos de voz, controles
profissionais e atualizador.

- [Pedalboard](https://github.com/spotify/pedalboard), usado para reverb e
  limitação.
- [RNNoise](https://github.com/xiph/rnnoise), usado para redução neural de ruído.
- [MIT KEMAR HRTF](https://sound.media.mit.edu/resources/KEMAR.html), medições
  binaurais de Bill Gardner e Keith Martin usadas pelo áudio espacial.
- [PortAudio](https://www.portaudio.com/) por meio do sounddevice.
- [wxPython](https://wxpython.org/) na interface nativa.
- [VB-CABLE](https://vb-cable.com/), cabo virtual donationware opcional incluído
  no instalador.
