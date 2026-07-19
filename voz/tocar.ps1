# Tocador de áudio persistente.
#
# Lê caminhos de arquivo da entrada padrão, um por linha, e toca cada um até o
# fim antes de ler o próximo — assim as frases saem na ordem, sem sobrepor.
#
# MediaPlayer toca mp3 sem depender de codec externo, mas é assíncrono: por isso
# esperamos a duração do arquivo antes de seguir.

Add-Type -AssemblyName presentationCore

$tocador = New-Object System.Windows.Media.MediaPlayer

while ($true) {
    $caminho = [Console]::In.ReadLine()
    if ($null -eq $caminho) { break }
    if ($caminho -eq '__SAIR__') { break }
    if (-not (Test-Path $caminho)) { continue }

    try {
        $tocador.Open([uri]$caminho)

        # A duração só fica conhecida depois que o arquivo é aberto.
        $limite = 0
        while (-not $tocador.NaturalDuration.HasTimeSpan -and $limite -lt 100) {
            Start-Sleep -Milliseconds 20
            $limite++
        }

        $tocador.Play()

        if ($tocador.NaturalDuration.HasTimeSpan) {
            $ms = $tocador.NaturalDuration.TimeSpan.TotalMilliseconds
            Start-Sleep -Milliseconds ([int]$ms + 120)
        } else {
            Start-Sleep -Milliseconds 1500  # não trava se a duração falhar
        }

        $tocador.Close()
        Remove-Item $caminho -ErrorAction SilentlyContinue
    } catch {
        continue
    }
}

$tocador.Close()
