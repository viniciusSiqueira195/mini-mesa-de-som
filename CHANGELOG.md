# Histórico de versões

## 1.2.0 — 2026-09-09

Esta versão adiciona a transmissão do áudio de outros programas junto com o
microfone e facilita a organização do Painel de efeitos.

### Transmissão do áudio de programas

- Agora é possível escolher um ou mais programas em execução e transmitir o
  áudio deles junto com o microfone para a saída virtual.
- A lista de programas fica na guia Dispositivos e pode ser atualizada sem
  reiniciar a Mini Mesa.
- A captura identifica cada programa pelo nome e pelo PID, permitindo escolher
  exatamente quais aplicativos serão transmitidos.
- Alterações na seleção feitas enquanto a mesa está ativa passam a valer na
  próxima ativação.
- Foram adicionados controles independentes para o volume do microfone e dos
  programas, ajustáveis de 0% a 200%.
- Os volumes podem ser alterados durante a transmissão.
- O novo motor nativo utiliza o WASAPI do Windows para capturar e misturar o
  microfone e os programas selecionados.
- O componente necessário para essa transmissão já acompanha o instalador.

### Adição de vários efeitos

- Agora é possível selecionar e adicionar vários arquivos ao Painel de efeitos
  de uma só vez.
- Cada áudio selecionado pode ser conferido individualmente antes da importação.
- Se uma prévia for cancelada, nenhum item daquele lote será adicionado
  parcialmente.
- A Mini Mesa verifica antecipadamente se há espaço suficiente na página para
  todos os arquivos escolhidos.
- Continuam sendo aceitos arquivos WAV, MP3, FLAC e OGG.

### Outros aprimoramentos

- Nomes e descrições de botões, listas, seletores, campos de busca e controles
  de ajuste ficaram mais claros.
- Os botões de efeitos anunciam seus estados de forma mais curta, evitando
  informações repetidas.
- A navegação durante a importação de vários arquivos ficou mais direta.

### Limitação desta versão

Nesta primeira etapa da migração para o motor nativo, o microfone e os programas
selecionados são enviados para a saída virtual sem os efeitos de voz, reverb,
redução de ruído, áudio 3D ou sons do Painel de efeitos. Esses recursos continuam
visíveis na interface, mas ainda não fazem parte da nova rota nativa.

## 1.1.0 — 2026-09-07

Esta é uma grande atualização da Mini Mesa de Som, com um painel de efeitos
totalmente pessoal, melhorias de acessibilidade, nova organização da interface
e ferramentas para facilitar configuração, suporte e troca de computador.

### Painel de efeitos pessoais

- O antigo conjunto de sons predefinidos foi substituído por um painel inicialmente
  vazio. Cada pessoa escolhe os próprios arquivos no computador.
- São dez páginas, com até dez efeitos em cada uma, totalizando cem posições.
- São aceitos arquivos WAV, MP3, FLAC e OGG, com até dez minutos e 256 MB por arquivo.
- `Ctrl+Shift+E` abre o Painel de efeitos e `F6` adiciona um som à página atual,
  mesmo quando a mesa está desligada.
- Antes de adicionar, é possível ouvir uma prévia no dispositivo de retorno. A
  prévia não abre o microfone nem envia o arquivo ao cabo virtual.
- `Alt+1` a `Alt+9` selecionam as páginas 1 a 9; `Alt+0` seleciona a página 10.
- `Ctrl+1` a `Ctrl+9` tocam as posições 1 a 9 da página atual; `Ctrl+0` toca a
  décima posição. `Ctrl+Shift+0` para todos os efeitos.
- `F2`, `F3` e `F4` continuam disponíveis para as três primeiras posições.
- Cada página pode receber um nome personalizado, como Memes, Aberturas ou Programa.
- A busca filtra a página pelo nome sem alterar a posição nem o atalho dos efeitos.
- Os efeitos podem ser movidos para cima, para baixo ou para outra página. A nova
  posição passa a definir automaticamente o atalho correspondente.
- A lista apresenta nomes e atalhos curtos para reduzir a leitura pelo NVDA.
- `Enter` toca o efeito selecionado e `Espaço` para todos os efeitos.
- O menu de contexto oferece Tocar, Renomear, Substituir arquivo, Mover, Excluir
  do painel e Parar todos. Ele abre pelo botão direito, tecla Aplicações,
  `Shift+F10` ou pelo botão Ações do efeito.
- Excluir remove apenas o cadastro da mesa e preserva o arquivo original. Uma
  confirmação acessível evita exclusões acidentais.
- Arquivos ausentes, muito grandes, longos ou inválidos produzem mensagens de erro
  acessíveis. Se o arquivo for movido, a opção Substituir permite localizá-lo.
- O instalador não distribui gravações ou efeitos sonoros predefinidos.

### Escuta dos efeitos e atalhos globais

- Os efeitos são ouvidos automaticamente no dispositivo de retorno escolhido,
  mesmo quando Ouvir retorno está desligado. Assim é possível gravar sem ouvir a
  própria voz e ainda conferir cada efeito em tempo real.
- Quando o retorno completo da voz é ligado, o efeito não é reproduzido em dobro.
- Em Ferramentas, Configurar atalhos globais, os comandos podem funcionar enquanto
  Discord, TeamTalk, gravadores e outros programas estão em foco.
- Os atalhos globais ficam desligados por padrão. É possível escolher `Ctrl` ou
  `Ctrl+Alt` para os efeitos e `Alt` ou `Alt+Shift` para as páginas.
- A mesa detecta combinações ocupadas por outros programas. Em caso de conflito,
  desativa o conjunto e libera os registros já feitos para não deixar atalhos presos.

### Interface e acessibilidade

- Os controles foram organizados nas guias Dispositivos, Voz e efeitos, Limpeza
  da voz, Áudio 3D e Painel de efeitos.
- `Ctrl+Tab` e `Ctrl+Shift+Tab` alternam as guias. Trocar de guia mantém o áudio e
  todos os efeitos ativos.
- Os botões informam ao leitor de telas a ação disponível e se o recurso está
  ligado ou desligado.
- O Painel de efeitos segue um fluxo direto: escolher a página, adicionar e
  navegar pela lista. O botão de adição anuncia a página que receberá o arquivo.
- Um indicador textual informa sem sinal, microfone baixo, nível adequado ou
  saturando. O NVDA só recebe um novo anúncio depois que o estado se estabiliza,
  evitando repetição excessiva.
- Avisos sonoros locais opcionais podem sinalizar quando a mesa liga, desliga ou
  muda de página. Esses avisos não são enviados à saída virtual.
- Uma janela acessível mostra as novidades uma vez após cada atualização. O texto
  permanece disponível em Ajuda, Novidades desta versão.
- Os presets experimentais de auto-tune e vocoder foram removidos porque não
  entregavam a afinação esperada. Configurações antigas são migradas com segurança.

### Perfis, backup e diagnóstico

- Perfis completos permitem salvar e recuperar dispositivos, processamento de
  voz, volumes, páginas e efeitos. A exclusão de perfil exige confirmação.
- Exportar backup cria um arquivo `.mmb` somente com configurações e caminhos ou
  um backup portátil contendo cópias dos áudios.
- Importar backup restaura as configurações e extrai os sons portáteis para a
  pasta de dados da Mini Mesa. Caminhos e tamanhos são validados antes da extração.
- Abrir diagnóstico mostra entradas, saídas, retornos, dispositivos selecionados
  e APIs de áudio. O relatório pode ser copiado e enviado ao suporte.

### Bandeja, dispositivos e estabilidade

- `Windows+M` oculta a mesa na bandeja sem interromper o áudio. Uma notificação
  curta explica que a janela pode ser restaurada pela bandeja do sistema.
- Ao restaurar pela bandeja, a janela volta a aparecer no `Alt+Tab`.
- Foi corrigida a condição que podia ocultar a janela novamente logo após sua
  restauração.
- Saídas disponíveis somente por MME ou DirectSound agora aparecem na lista de
  retorno mesmo quando o computador também possui dispositivos WASAPI.
- A continuidade do áudio foi reforçada ao alternar guias e controles, com filas
  separadas para impedir que problemas no retorno bloqueiem a gravação ou chamada.
- A atualização preserva preferências e efeitos pessoais já cadastrados.

### Instalador e verificação

- O instalador mantém o mesmo identificador das versões anteriores e atualiza a
  instalação existente sem apagar as preferências do usuário.
- A instalação opcional do VB-CABLE reconhece instalações existentes, inclusive
  dispositivos desativados, e preserva os dispositivos padrão de reprodução,
  comunicação e gravação.
- O pacote inclui explicitamente a ajuda, as novidades, extensões Markdown,
  bibliotecas nativas do RNNoise e dados do áudio espacial HRTF.
- A geração do instalador agora exige um autoteste do executável isolado do ambiente
  de desenvolvimento. Ele verifica interface, ajuda, novidades, dispositivos,
  Pedalboard, RNNoise, HRTF, perfis, backup, diagnóstico e os formatos WAV, MP3,
  FLAC e OGG.
- O instalador é acompanhado por um arquivo SHA-256, usado pelo atualizador para
  confirmar a integridade antes de executar a instalação.

### Como começar

1. Abra o Painel de efeitos com `Ctrl+Shift+E`.
2. Escolha uma página com as setas ou com `Alt+1` a `Alt+0`.
3. Pressione `F6`, escolha um arquivo e use Ouvir prévia se desejar conferi-lo.
4. Confirme a adição. A posição na lista define o atalho `Ctrl` correspondente.
5. Ative a mesa e use `Ctrl+1` a `Ctrl+0` para tocar os efeitos da página atual.

Para restaurar a janela depois de `Windows+M`, pressione `Windows+B`, localize
Mini Mesa de Som, abra o menu com a tecla Aplicações ou `Shift+F10` e escolha
Abrir Mini Mesa de Som.

## 1.0.0 — 2026-09-01

- Posicionamento binaural 3D por coordenadas X, Y e Z.
- Movimento espacial automático por frente, direita, trás, esquerda, cima e baixo.
- Controle acessível de velocidade e migração das preferências horizontais antigas.
- Soundboard acessível com cinco efeitos simultâneos, atalhos de teclado e mistura na rota virtual.
- Suporte a pacote pessoal com pistola, metralhadora, palmas, air horn de DJ e locução personalizada.
- Soundboard inserido antes do reverb e do áudio espacial para acompanhar o estado da mesa.
- Descoberta renovada de dispositivos e preferência por WASAPI compartilhado.
- Efeitos de voz, modulações, ambientes e controles profissionais de áudio.
- Volume e ducking do soundboard, além de reprodução de arquivo personalizado.
- Ajuda acessível em F1 herdada do README, com navegação web por cabeçalhos e modo de texto contínuo.
- Rótulos MSAA estáveis para sliders e correções de inicialização da interface.
- Endurecimento concorrente do RNNoise e limpeza segura de atualizações incompletas.
- Nome definitivo “Mini Mesa de Som”, com migração das preferências e compatibilidade com os sons pessoais antigos.

### Instalação

Baixe `MiniMesaDeSom-Setup-1.0.0.exe` nos arquivos da release. O instalador usa o
mesmo identificador da versão anterior e atualiza a instalação existente sem
apagar as preferências do usuário.

## 0.1.0 — 2026-08-27

Primeira versão pública da Mini Mesa de Som.

- Interface acessível para teclado e leitores de tela.
- Reverb em tempo real com controle simplificado.
- Redução de ruído RNNoise opcional e local.
- Áudio espacial binaural com HRTF MIT KEMAR.
- Rota principal WDM-KS restaurada após comparação com o instalador anterior.
- Retorno local experimental, com fila não bloqueante isolada da gravação.
- Preferências persistentes e funcionamento na bandeja do sistema.
- Atualizador integrado com consulta ao GitHub e validação SHA-256.
- Instalador acessível para Windows com instalação opcional do VB-CABLE.
- Diálogo de boas-vindas na primeira inicialização.

### Instalação

Baixe `MiniMesaDeSom-Setup-0.1.0.exe` nos arquivos da release e execute-o. A
instalação do aplicativo não exige privilégios administrativos. A opção do
VB-CABLE pode solicitar permissão de administrador porque instala um driver de
áudio no Windows.

O instalador desta primeira versão ainda não possui assinatura digital. Por
isso, o Microsoft Defender SmartScreen pode exibir um aviso antes da execução.
