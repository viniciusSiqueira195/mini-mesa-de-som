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
4. Ative o reverb na Mini Mesa.

Evite selecionar caixas de som como saída enquanto elas estiverem próximas do
microfone: isso pode produzir microfonia.

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
- `Alt+R`: ajustar a quantidade de reverb.
- `Alt+T`: ajustar o tamanho da sala.
- `Alt+A`: ativar ou desativar o processamento.
- `F5`: atualizar a lista de dispositivos.

## Testes

Os testes do controlador não acessam microfones reais:

```powershell
python -m unittest discover -s tests -v
```

## Estado atual

Este é um MVP. Ele usa PortAudio para selecionar os dispositivos por
identificadores estáveis e Pedalboard para processar o reverb em código nativo.
Ele já separa a interface do motor de áudio, permite trocar o
microfone sem alterar o código e protege contra duas transmissões simultâneas.
Configuração persistente, medidor de nível, presets e empacotamento serão as
próximas etapas.
