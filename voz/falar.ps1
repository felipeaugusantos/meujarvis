# Processo de fala persistente.
#
# Sobe o sintetizador uma vez só e fica lendo frases da entrada padrão. Abrir um
# PowerShell novo a cada frase custaria ~300 ms de silêncio entre elas.
#
# Cada linha recebida é UTF-8 em base64: assim acentos e aspas atravessam o pipe
# sem depender de code page, e nada do texto é interpretado como comando.

param(
    [string]$Voz = "Microsoft Maria Desktop",
    [int]$Velocidade = 1
)

Add-Type -AssemblyName System.Speech

$sintetizador = New-Object System.Speech.Synthesis.SpeechSynthesizer
try { $sintetizador.SelectVoice($Voz) } catch { }  # cai na voz padrão do sistema
$sintetizador.Rate = $Velocidade
$sintetizador.Volume = 100

while ($true) {
    $linha = [Console]::In.ReadLine()
    if ($null -eq $linha) { break }
    if ($linha -eq '__SAIR__') { break }
    if ($linha.Trim().Length -eq 0) { continue }

    try {
        $texto = [System.Text.Encoding]::UTF8.GetString(
            [System.Convert]::FromBase64String($linha))
        $sintetizador.Speak($texto)
    } catch {
        continue  # linha corrompida não derruba a voz
    }
}

$sintetizador.Dispose()
