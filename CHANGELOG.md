# Histórico de versões

## 1.1.0 — Em testes

- Janela acessível de novidades exibida uma vez por versão, com acesso permanente
  pelo menu Ajuda e arquivo de texto incluído no instalador.

- Saídas de retorno disponíveis apenas por MME ou DirectSound deixam de ser
  ocultadas quando também existe um dispositivo WASAPI.
- Build passa a exigir autoteste do executável, com interface, ajuda, codecs,
  RNNoise e HRTF; corrigido o parâmetro espacial desatualizado desse autoteste.
- Inclusão explícita das extensões Markdown e coleta da DLL do RNNoise como
  binário, permitindo ao PyInstaller verificar suas dependências nativas.

- Painel simplificado: escolher página, adicionar efeitos à página indicada e
  navegar por uma lista com nomes e atalhos curtos.
- Menu de contexto dos efeitos com tocar, renomear, substituir, excluir e parar,
  acessível pelo botão direito, tecla Aplicações, Shift+F10 ou botão Ações do efeito.

- Os efeitos são ouvidos automaticamente no dispositivo de retorno, mesmo com
  o retorno da voz desligado, sem nova opção. Ativar o retorno completo não duplica os sons.

- Painel de efeitos inicialmente vazio, com cadastro de arquivos locais, renomeação,
  substituição e remoção sem apagar o áudio original.
- Dez páginas pessoais com dez efeitos por página: Alt+1 a Alt+0 escolhem a
  página e Ctrl+1 a Ctrl+0 reproduzem seus efeitos. Ctrl+Shift+0 para todos.
- F6 adiciona à página atual, mesmo com a mesa desativada.
- Windows+M oculta a mesa na bandeja, mantendo o áudio, e solicita uma notificação
  com instruções de restauração. Ao abrir pela bandeja, a janela volta ao Alt+Tab.
- Restauração cancela ocultamentos pendentes, impedindo que a janela suma novamente.
- Validação de arquivos e mensagens acessíveis para falhas de reprodução ou gravação.
- Empacotamento sem gravações predefinidas do soundboard.

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
