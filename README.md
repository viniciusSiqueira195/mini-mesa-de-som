# Mini Mesa de Som Teste

Protótipo de uma mesa de som virtual simples e acessível para aplicar reverb
em tempo real a qualquer microfone. A interface usa controles nativos do
Windows para funcionar bem com NVDA e somente pelo teclado.

## Como o áudio passa pelo aplicativo

```text
Microfone físico -> Mini Mesa de Som -> cabo de áudio virtual -> Discord/TeamTalk
```

O aplicativo não depende da marca do microfone. Um FIFINE AM8, um Zeus X ou
qualquer outra entrada reconhecida pelo Windows pode ser selecionada na lista.

Nesta primeira versão, ainda é necessário ter um cabo de áudio virtual
instalado. Com o VB-CABLE, por exemplo:

1. Em **Microfone de entrada**, selecione o microfone físico.
2. Em **Saída virtual**, selecione `CABLE Input`.
3. No Discord ou TeamTalk, selecione `CABLE Output` como microfone.
4. Clique em **Ativar mesa** e marque **Ativar efeito de reverb**.

O único ajuste do efeito é **Nível de reverb**, de 0 a 100. Internamente, esse
controle equilibra a quantidade do efeito, o tamanho do ambiente simulado e a
duração da cauda. Não é necessário configurar parâmetros técnicos separados.
A voz limpa e o efeito são misturados proporcionalmente com margem automática
de volume, evitando que a soma dos dois sinais sature ou acione o limitador o
tempo inteiro.

O reverb pode ser ligado ou desligado enquanto a mesa está funcionando. Ao
desligá-lo, a voz limpa continua sendo enviada normalmente para a saída virtual.
Isso permite acrescentar outros efeitos independentes no futuro sem interromper
todo o fluxo de áudio.

## Redução de ruído

**Ativar redução de ruído profissional** usa o RNNoise para reduzir ruídos de
fundo na voz antes dos outros efeitos. A opção fica desmarcada por padrão. Ela
pode ser combinada livremente com o reverb:

```text
Microfone -> redução de ruído opcional -> reverb opcional -> limitador -> saídas
```

O RNNoise funciona localmente, sem enviar áudio para a internet, e acrescenta um
quadro fixo de 10 milissegundos ao processamento. Como ele exige áudio em 48 kHz,
a configuração só pode ser alterada enquanto a mesa estiver desativada. Isso não
impede usar redução e reverb juntos; basta marcar os efeitos desejados antes de
ativar a mesa.

O botão **Desativar mesa** interrompe somente a transmissão de áudio e mantém a
janela aberta. Use **Encerrar programa** para parar o áudio e fechar a Mini Mesa.

## Preferências

A Mini Mesa guarda automaticamente em JSON o microfone, a saída virtual, o
retorno, o estado do reverb, seu nível e a redução de ruído. No Windows, o
arquivo fica em
`%APPDATA%\Mini Mesa de Som Teste\preferences.json`. A gravação é feita primeiro
em um arquivo temporário para reduzir o risco de corrupção. Se o JSON estiver
inválido ou um dispositivo salvo não estiver mais conectado, a mesa inicia com
valores seguros e escolhe um dispositivo disponível.

## Retorno da própria voz

Marque **Ouvir retorno** e escolha o fone ou dispositivo em que deseja escutar
a voz processada. A saída virtual continua alimentando o Discord, TeamTalk ou
WhatsApp ao mesmo tempo. Use preferencialmente fones; retornar o microfone para
caixas de som pode provocar microfonia.

Os controles de retorno permanecem disponíveis enquanto a mesa está ativa.
Marcar, desmarcar ou escolher outro dispositivo altera somente a saída de
retorno. O microfone, a saída virtual e os efeitos continuam funcionando.

O retorno usa preferencialmente WASAPI compartilhado. Saídas exclusivas WDM-KS
não são oferecidas para monitoramento, pois muitos drivers não permitem que elas
sejam sincronizadas com a captura e o cabo virtual ao mesmo tempo. Ao ativar, a
mesa testa silenciosamente a combinação antes de começar a transmitir.

A mesa usa blocos de 256 amostras com retorno e 512 sem retorno, recorrendo ao
outro tamanho se o driver não aceitar a primeira opção. Antes de iniciar as saídas,
dois blocos são preparados para absorver pequenas oscilações do Windows. O buffer
continua curto e suaviza faltas ou descartes de áudio para evitar estalos. Ainda
existe uma pequena latência de captura, processamento e reprodução; o retorno não
pode ser literalmente instantâneo.

Evite selecionar caixas de som como saída enquanto elas estiverem próximas do
microfone: isso pode produzir microfonia.

### Quando um microfone aparece, mas não abre

O Windows pode anunciar o mesmo microfone por várias APIs, mesmo quando algumas
delas não funcionam com o driver instalado. A Mini Mesa agrupa nomes duplicados
e tenta automaticamente WDM-KS, WASAPI, DirectSound e MME. Se todas forem
recusadas, feche outros programas que possam estar usando o microfone em modo
exclusivo, reconecte o dispositivo e pressione `F5`. O FIFINE AM8 e o Virtual
Audio Cable usados no desenvolvimento foram validados em transmissão real.

## Instalação para desenvolvimento

No PowerShell, dentro desta pasta:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m mini_mesa
```

Também é possível iniciar pelo comando instalado:

```powershell
mini-mesa
```

## Atalhos

- `Alt+M`: escolher o microfone.
- `Alt+S`: escolher a saída virtual.
- `Alt+O`: ativar ou desativar o retorno.
- `Alt+T`: escolher o dispositivo de retorno.
- `Alt+E`: ativar ou desativar somente o efeito de reverb.
- `Alt+R`: ajustar o nível de reverb.
- `Alt+D`: ativar ou desativar a redução de ruído, com a mesa parada.
- `Alt+A`: ativar ou desativar a mesa.
- `Alt+C`: encerrar o programa.
- `F5`: atualizar a lista de dispositivos.

## Testes

Os testes do controlador não acessam microfones reais:

```powershell
python -m unittest discover -s tests -v
```

## Estado atual

Este é um MVP. Ele usa PortAudio para selecionar os dispositivos por
identificadores estáveis, Pedalboard para o reverb e RNNoise para redução neural
de ruído local. Ele já separa a interface do motor de áudio, permite trocar o
microfone sem alterar o código, protege contra duas transmissões simultâneas e
mantém as preferências em JSON. Medidor de nível, presets, novos efeitos e
empacotamento são possíveis próximas etapas.
