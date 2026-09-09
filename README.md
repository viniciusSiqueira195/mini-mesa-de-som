# Mini Mesa de Som

Mesa de som virtual para Windows, simples de operar pelo teclado e construída
com acessibilidade como requisito central. A Mini Mesa recebe qualquer microfone
reconhecido pelo sistema, aplica efeitos em tempo real e envia o resultado para
um cabo de áudio virtual usado pelo Discord, TeamTalk, WhatsApp ou outro programa.

> Projeto experimental em desenvolvimento ativo. A interface, as preferências e
> o instalador Windows já são utilizáveis, mas a versão ainda precisa de testes
> em diferentes computadores e interfaces de áudio.

## Versão atual

A versão **1.2.0** adiciona a transmissão do áudio de programas em execução
junto com o microfone, controles independentes de volume e importação de vários
arquivos no Painel de efeitos.

## Instalação rápida

Baixe `MiniMesaDeSom-Setup-1.2.0.exe` na página da
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
- Seleção de um ou mais programas para transmitir junto com o microfone.
- Volumes independentes, de 0% a 200%, para o microfone e os programas.
- Reverb ajustado por um único controle simples de 0 a 100.
- Modificador de voz com presets de pitch e harmonização.
- Efeitos criativos, modulações, ambientes e controles de intensidade com
  bypass real em 0%.
- Compressor, equalizador, noise gate, de-esser, expander, ganho automático e
  filtro de plosivas.
- Painel de efeitos pessoais com lista livre, nomes editáveis, volume e
  ducking durante a fala.
- Redução neural de ruído RNNoise, opcional e executada localmente.
- Áudio espacial binaural 3D por coordenadas X, Y e Z, com movimento automático.
- Reverb e redução de ruído utilizáveis separadamente ou em conjunto.
- Retorno local experimental, mantido aberto para testes e contribuições.
- Minimização para a bandeja, com notificação explicativa, sem interromper o áudio.
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
Microfone físico --------\
                            -> mistura nativa pelo WASAPI
Programas selecionados ----/       -> volumes independentes
    -> cabo de áudio virtual
    -> Discord, TeamTalk, WhatsApp ou outro aplicativo
```

Na versão 1.2.0, a nova rota nativa mistura o microfone e os programas
selecionados diretamente na saída virtual. Nesta primeira etapa da migração,
os efeitos de voz, reverb, redução de ruído, áudio 3D e o Painel de efeitos ainda
não são aplicados por essa rota.

Os efeitos do soundboard entram na mesma rota antes do limitador. Eles chegam ao
aplicativo de conversa pela saída virtual. Os efeitos também são ouvidos no
dispositivo de retorno escolhido, mesmo com **Ouvir retorno** desligado.

A escuta local dos efeitos funciona automaticamente com a mesa ativa. Deixe
**Ouvir retorno** desligado para gravar voz e efeitos ouvindo somente os efeitos
no fone. O seletor **Dispositivo de retorno** permanece disponível para escolher
onde ouvi-los. Nessa escuta separada, os sons respeitam volume e ducking do painel,
sem os efeitos de processamento da voz, como reverb e áudio 3D.

Quando **Ouvir retorno** está ligado, uma única cópia do áudio processado completo
segue para o fone escolhido, sem duplicar os sons. Use fones de ouvido para evitar microfonia. Esse
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

O script roda os testes, empacota o programa com PyInstaller, executa um autoteste
do executável sem o Python de desenvolvimento no PATH e baixa os pacotes
oficiais do VB-CABLE e AudioDeviceCmdlets com verificação SHA-256 e gera
`installer-output\MiniMesaDeSom-Setup-1.2.0.exe`. O aplicativo é empacotado em
uma pasta interna para dar mais estabilidade às bibliotecas nativas de áudio;
para o usuário, a entrega continua sendo um único instalador.

### Verificação do pacote

A geração do instalador é interrompida se o executável não conseguir carregar a
interface, a ajuda, o Pedalboard, o RNNoise, os dados HRTF ou os codecs WAV, MP3,
FLAC e OGG. Esse autoteste é obrigatório mesmo com `-SkipTests` e grava seu
resultado em `build/frozen-self-test.json`, incluindo os dispositivos e APIs de
áudio encontrados, sem abrir microfones para captura.

O relatório ajuda a comparar a versão instalada com a de desenvolvimento; ele
não substitui uma instalação em máquina limpa nem testes com o hardware do usuário.

## Novidades da versão

Na primeira abertura após atualizar, uma janela nativa acessível apresenta as
novidades da versão. Use as setas para ler, Ctrl+Home para voltar ao início e
Escape ou o botão Fechar novidades para fechar. A leitura é registrada nas
preferências para que a janela não apareça em todas as aberturas.

O menu **Ajuda > Novidades desta versão** permite reler o texto. A janela usa a
seção correspondente à versão instalada no `CHANGELOG.md`. Assim, o programa,
o GitHub e os textos de divulgação compartilham uma única fonte completa. Esse
arquivo é incluído no pacote e verificado pelo autoteste do executável.

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
4. Ative os efeitos desejados nas guias e pressione **Ativar mesa**.

**Desativar mesa** interrompe somente a transmissão e mantém a janela aberta.
**Encerrar programa** para o áudio e fecha o aplicativo.

## Organização por guias

A janela reúne os controles em cinco guias:

- **Dispositivos**: microfone, saída virtual e retorno.
- **Voz e efeitos**: modificador de voz, reverb, estilos, modulações, ambientes e eco.
- **Limpeza da voz**: compressor, equalizador, filtros e redução de ruído.
- **Áudio 3D**: posição e movimento espacial.
- **Painel de efeitos**: adicionar, renomear, substituir, remover e reproduzir arquivos pessoais, com volume e ducking.

Use `Ctrl+Tab` para avançar e `Ctrl+Shift+Tab` para voltar entre as guias.
O foco fica no seletor de guias; `Tab` entra nos controles da guia selecionada.
`Tab` e `Shift+Tab` percorrem seus controles e as ações gerais da janela.
Os controles das outras guias ficam ocultos. Trocar de guia mantém o áudio e
todos os efeitos ativos, inclusive os configurados em outra guia.

Os botões de efeitos mostram a ação **Ativar** ou **Desativar**. O estado
marcado ou desmarcado continua sendo exposto pelo próprio controle ao leitor de
tela. Pressione `Espaço` para alternar o botão em foco.
**Ativar/Desativar mesa**, **Encerrar programa** e o estado do processamento
permanecem disponíveis fora das guias. Os atalhos globais de efeitos e ajustes
revelam automaticamente a guia correspondente.

## Bandeja do sistema

Ao minimizar a janela ou pressionar `Windows+M`, a Mini Mesa fica oculta, sai da
barra de tarefas e de `Alt+Tab`, mantendo o áudio ativo. A cada minimização para a
bandeja, solicita ao Windows a notificação **Mini Mesa minimizada**: “A Mini Mesa
está minimizada. Você pode restaurá-la pela bandeja do sistema.” A exibição e o anúncio da
notificação dependem das configurações de notificações do Windows e do leitor de tela.

Para voltar, pressione `Windows+B`, localize **Mini Mesa de Som**, abra o menu
com a tecla Aplicações ou `Shift+F10` e escolha **Abrir Mini Mesa de Som**.
Depois de restaurada pela bandeja, a janela volta à barra de tarefas e a
`Alt+Tab`. O menu também oferece **Encerrar programa**.

Se o ícone da bandeja não estiver disponível, a janela permanece minimizada na
barra de tarefas para continuar acessível. Uma falha de áudio restaura a janela
antes de mostrar a mensagem de erro.

## Efeitos

Os presets experimentais de auto-tune e vocoder foram removidos porque não
entregavam a afinação vocal pretendida. Preferências antigas desses presets
são carregadas com o modificador de voz desativado e tom neutro; as demais
preferências são preservadas.

### Reverb

O controle **Nível de reverb** combina internamente a quantidade do efeito, o
tamanho do ambiente simulado e a duração da cauda. A voz limpa e o efeito são
misturados com margem automática de volume. O reverb pode ser alterado enquanto
a mesa está funcionando.

### Redução de ruído

O RNNoise reduz ruídos de fundo antes dos efeitos e não envia áudio para a
internet. A opção fica desligada por padrão, requer processamento em 48 kHz e
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

### Painel de efeitos pessoais

O painel começa vazio: nenhum efeito sonoro é predefinido ou distribuído no
instalador. O menu **Efeitos > Abrir painel de efeitos** ou `Ctrl+Shift+E`
seleciona a guia **Painel de efeitos** e leva o foco ao seletor de páginas.

1. Abra o painel com `Ctrl+Shift+E`. No seletor, use as setas para escolher
   **Página 1**, **Página 2** e assim por diante. O foco permanece no seletor
   enquanto você escolhe.
2. Pressione `Tab` para chegar ao botão **Adicionar efeitos, página 1** (o número
   acompanha a página escolhida). Ative o botão e selecione um ou mais arquivos WAV,
   MP3, FLAC ou OGG. Cada arquivo é conferido individualmente antes de ser adicionado;
   cancelar qualquer prévia cancela todo o lote. **Ouvir prévia** toca o arquivo somente
   no dispositivo de retorno. A prévia funciona com a mesa desativada, sem abrir o
   microfone. `F6` também adiciona diretamente à página atual.
3. Após confirmar, o foco vai para os novos efeitos. A lista anuncia somente o nome
   e o atalho do som, sem ler o caminho inteiro do arquivo.
4. Na lista, use as setas para escolher o efeito e abra seu menu com a tecla
   **Aplicações** ou `Shift+F10`. O botão direito sobre um efeito e o botão
   **Ações do efeito** oferecem o mesmo menu: **Tocar**, **Renomear**,
   **Substituir arquivo**, **Mover para cima**, **Mover para baixo**,
   **Mover para outra página**, **Excluir do painel** e **Parar todos os efeitos**.
   Excluir do painel preserva o arquivo original no computador.
5. Com a mesa ativa, `Enter` reproduz o efeito selecionado. `Espaço` na lista
   ou `Ctrl+Shift+0` interrompe todos os sons.

O painel tem dez páginas, com até dez efeitos em cada uma: até cem sons.
Use o seletor **Página de efeitos** ou `Alt+1` a `Alt+9`; `Alt+0` escolhe a página
10. A página escolhida é salva e anunciada no nome acessível da lista.

`Ctrl+1` a `Ctrl+9` reproduzem as posições 1 a 9 da página atual; `Ctrl+0` reproduz
o décimo efeito. Esses atalhos funcionam também em outras guias, com a janela em
foco. `F2`, `F3` e `F4` reproduzem as posições 1, 2 e 3 da página atual.
Trocar de página não interrompe sons em reprodução. **Parar todos**, `Ctrl+Shift+0`
ou `Espaço` na lista interrompem os sons de todas as páginas.

`F6` adiciona à página selecionada. Quando ela estiver cheia, escolha outra página
ou remova um efeito. Ao remover, os atalhos acompanham a nova ordem dessa página.
Uma lista salva pela versão anterior do painel é distribuída em grupos de dez.
Se uma lista antiga ultrapassar cem itens, os excedentes são preservados no final
da página 10, acessíveis pela lista, sem atalhos numéricos adicionais.

Nomes, caminhos e ordem são salvos nas preferências. Os áudios permanecem no
local escolhido, sem cópia para o aplicativo. Se um arquivo for movido ou apagado,
use **Substituir arquivo** para localizar o áudio novamente. Os arquivos podem ter
até 256 MB e dez minutos de duração. Arquivos vazios ou não reconhecidos são
recusados ao cadastrar.

Use **Renomear página** para trocar nomes genéricos por categorias como Memes,
Aberturas ou Programa. O campo **Buscar efeito nesta página** filtra pelo nome
sem mudar a posição real nem o atalho do som.

Os efeitos podem tocar simultaneamente e entram na mesma cadeia da voz. Portanto,
reverb e áudio espacial 3D ativos também processam os sons do painel. O volume e
a redução dos efeitos durante a fala continuam disponíveis.

Ao atualizar uma versão antiga, a lista também começa vazia e as demais
preferências são preservadas. Os arquivos pessoais antigos continuam em
`%APPDATA%\Mini Mesa de Som\sounds` ou
`%APPDATA%\Mini Mesa de Som Teste\sounds`; use **Adicionar efeito de áudio** para
escolher quais deles deseja incluir no painel.

## Atalhos globais

Os atalhos numéricos funcionam dentro da Mini Mesa por padrão. Em **Ferramentas >
Configurar atalhos globais**, eles podem funcionar também quando Discord,
TeamTalk, um gravador ou outro programa estiver em foco. A ativação é opcional
para não capturar teclas usadas por outros aplicativos sem escolha do usuário.

O diálogo permite escolher os modificadores de efeitos e páginas. Se qualquer
combinação já estiver registrada por outro programa, a Mini Mesa informa qual
falhou, desativa o conjunto e libera os atalhos que conseguiu registrar.

## Perfis, backup e diagnóstico

Em **Ferramentas**, **Salvar perfil atual** guarda dispositivos, processamento,
volumes, nomes de páginas e efeitos. **Carregar perfil** aplica o conjunto e
mantém a mesa parada para que a nova rota seja conferida antes da ativação.

**Exportar backup** oferece duas modalidades:

- Backup de configurações, pequeno, que mantém os caminhos atuais dos áudios.
- Backup portátil, que inclui cópias dos arquivos e pode ser levado para outro
  computador.

**Importar backup** valida o manifesto, os caminhos e os limites dos arquivos
antes de extrair os áudios. A extração usa uma nova pasta em `%APPDATA%`, sem
sobrescrever uma importação anterior.

**Abrir diagnóstico** mostra e permite copiar a versão, o Windows, o estado da
mesa, os dispositivos escolhidos, as entradas, saídas, retornos e APIs de áudio.
O relatório é indicado para casos em que algum dispositivo não aparece.

## Indicador textual e avisos locais

O campo **Nível do microfone** informa: sem sinal, microfone baixo, nível adequado
ou saturando. Uma mudança só é anunciada ao leitor de tela depois de permanecer
estável por três medições, evitando repetição perto dos limites.

**Ferramentas > Avisos sonoros locais** habilita sinais do Windows ao ligar ou
desligar a mesa e trocar de página. Eles não entram diretamente na saída virtual.
Essa preferência fica desligada inicialmente.

## Atalhos

- `Ctrl+Tab`: próxima guia.
- `Ctrl+Shift+Tab`: guia anterior.
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
- `Ctrl+Shift+E`: acessar o Painel de efeitos e escolher a página.
- `Aplicações` ou `Shift+F10` na lista: abrir as ações do efeito selecionado.
- `Alt+1` a `Alt+9` e `Alt+0`: selecionar as páginas 1 a 10.
- `Ctrl+1` a `Ctrl+9` e `Ctrl+0`: reproduzir os efeitos 1 a 10 da página atual.
- `Ctrl+Shift+0`: interromper todos os efeitos de todas as páginas.
- `Alt+A`: ativar ou desativar a mesa.
- `Alt+C`: encerrar o programa.
- `F5`: atualizar os dispositivos.
- `F1`: abrir a ajuda acessível com apresentação, atalhos e créditos.
- `F2`, `F3` e `F4`: reproduzir os efeitos nas posições 1, 2 e 3.
- `F6`: adicionar um arquivo ao Painel de efeitos.
- `Alt+J`, depois `A`: abrir Ajuda e verificar atualizações.

Quando os atalhos globais estiverem ligados, os atalhos numéricos configurados
continuam ativos enquanto outro aplicativo estiver em foco.

Na ajuda aberta por `F1`, leitores de tela podem usar `H` e `Shift+H` para
navegar entre os cabeçalhos, ou as teclas `1` a `6` para navegar por nível. O
botão **Usar modo de texto contínuo** preserva a leitura tradicional com as
setas, Page Up e Page Down.

## Preferências

As preferências são gravadas automaticamente em:

```text
%APPDATA%\Mini Mesa de Som\preferences.json
```

O arquivo inclui os dispositivos, o retorno, os estados dos efeitos e a lista de áudios pessoais. A gravação usa um
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
buffers, isolamento entre retorno e gravação, integração do redutor de ruído e
operação do painel de efeitos em controles wxPython reais. Os testes usam arquivos
de áudio temporários, sem acessar microfones físicos nem alterar preferências pessoais.

## Arquitetura

- `mini_mesa/ui.py`: janela wxPython e comportamento acessível.
- `mini_mesa/audio_engine.py`: dispositivos, ciclo da transmissão e cadeia DSP.
- `mini_mesa/native_engine.py`: controle da rota nativa de transmissão.
- `mini_mesa/process_audio.py`: descoberta e captura do áudio de programas.
- `placasom.cpp`: motor nativo WASAPI para microfone, programas e saídas.
- `mini_mesa/noise_reduction.py`: adaptação de streaming e RNNoise nativo.
- `mini_mesa/spatial_audio.py`: convolução binaural, interpolação e transições.
- `mini_mesa/soundboard.py`: carregamento, reamostragem e mixagem dos efeitos.
- `mini_mesa/preferences.py`: persistência JSON atômica.
- `mini_mesa/global_hotkeys.py`: registro e liberação dos atalhos do Windows.
- `mini_mesa/user_features.py`: perfis, backup portátil e diagnóstico.
- `mini_mesa/settings.py`: mapeamento seguro dos controles de efeito.
- `tests/`: testes automatizados do motor e das configurações.

## Próximos passos

- Testes auditivos do HRTF em diferentes cabos virtuais e aplicativos.
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
