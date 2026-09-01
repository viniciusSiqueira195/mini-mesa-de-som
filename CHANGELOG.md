# Histórico de versões

## Em desenvolvimento

- Posicionamento binaural 3D por coordenadas X, Y e Z.
- Movimento espacial automático por frente, direita, trás, esquerda, cima e baixo.
- Controle acessível de velocidade e migração das preferências horizontais antigas.
- Descoberta renovada de dispositivos e preferência por WASAPI compartilhado.

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
