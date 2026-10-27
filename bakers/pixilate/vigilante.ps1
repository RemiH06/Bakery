# Vigilante de los Bakers: cada 5 s mira la VRAM y la RAM y elige la marcha más alta que cabe (perfil de llama-swap).
# Baja al momento, sube solo tras un minuto estable y nunca descarga un modelo a media respuesta.
# Lo lanza setup.ps1 como trabajo `bakers-vigilante` al arrancar Windows.
#   -Extra 3000 -Duracion 60      simula 3 GB de VRAM ocupados por otro programa durante un minuto (prueba sin abrir un juego)
#   -ExtraRam 30000 -Duracion 60  lo mismo con 30 GB de RAM
param([int]$Extra = 0, [int]$ExtraRam = 0, [int]$Duracion = 0)
$ErrorActionPreference = 'Stop'
$api = 'http://127.0.0.1:8090'
$auth = @{ Authorization = "Bearer $((Get-Content "$env:USERPROFILE\bakers\api-key.txt" -Raw).Trim())" }
# VRAM y RAM propias de cada modelo con -c 32768, en MiB, sin lo del escritorio (medidas el 2026-10-27).
# Bonsai también copia el modelo a RAM (~9.5 GB residentes); Qwen deja ~4.6 GB privados más los expertos
# mapeados del GGUF, que llegan a ~20 GB conforme se usan (si faltan, no truena: se vuelve lento leyendo disco).
$marchas = @(
    @{ perfil = 'alta'; modelo = 'bonsai'; vram = 9100; ram = 10000 },
    @{ perfil = 'media'; modelo = 'qwen'; vram = 3350; ram = 20000 },
    @{ perfil = 'ninguna'; modelo = $null; vram = 0; ram = 0 }
)
# Modelos fuera de las marchas (se piden por nombre): su VRAM también es nuestra, no de un juego
$fuera = @{ abliterado = 3350; whisper = 1500; vision = 4700 }
$margen = 1024     # MiB de VRAM libres para que lo demás (el juego) no se quede corto
$margenRam = 2048  # lo mismo en RAM
$subirTras = 60    # segundos cabiendo sin interrupción antes de subir a esa marcha
$cabeDesde = @{}
$fin = if ($Duracion) { (Get-Date).AddSeconds($Duracion) } else { [datetime]::MaxValue }

function Log($msg) { "[vigilante] $(Get-Date -f s) $msg" }

while ((Get-Date) -lt $fin) {
    try {
        $usado, $total = (nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits) -split ',\s*' | ForEach-Object { [int]$_ }
        $corriendo = @((Invoke-RestMethod "$api/running" -Headers $auth).running)
        $cargado = $marchas | Where-Object { $_.modelo -and $_.modelo -in $corriendo.model } | Select-Object -First 1
        # Lo que usa todo lo demás: el total menos lo que ocupan nuestros modelos cargados
        $nuestraVram = ($corriendo | ForEach-Object { $m = $_.model; if ($fuera.ContainsKey($m)) { $fuera[$m] } else { ($marchas | Where-Object { $_.modelo -eq $m }).vram } } | Measure-Object -Sum).Sum
        $otros = $usado + $Extra - [int]$nuestraVram
        # RAM: la disponible más lo que ya ocupan nuestros servidores, que se libera al cambiar de modelo
        $nuestra = (Get-Process llama-server, whisper-server -EA SilentlyContinue | Measure-Object WorkingSet64 -Sum).Sum / 1MB
        $ramLibre = (Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory).AvailableMBytes + $nuestra - $ExtraRam
        $activo = (Invoke-RestMethod "$api/api/profiles" -Headers $auth).active
        $iActual = @(0..2 | Where-Object { $marchas[$_].perfil -eq $activo })[0]

        $ahora = Get-Date
        $nuevo = $null
        for ($i = 0; $i -lt $marchas.Count; $i++) {
            $m = $marchas[$i]
            $cabe = ($m.vram -eq 0) -or (($m.vram + $otros + $margen -le $total) -and ($m.ram + $margenRam -le $ramLibre))
            if (-not $cabe) { $cabeDesde.Remove($m.perfil); continue }
            if (-not $cabeDesde.ContainsKey($m.perfil)) { $cabeDesde[$m.perfil] = $ahora }
            # Bajar o quedarse: inmediato. Subir: solo si lleva un minuto cabiendo.
            $estable = ($ahora - $cabeDesde[$m.perfil]).TotalSeconds -ge $subirTras
            if ($null -eq $iActual -or $i -ge $iActual -or $estable) { $nuevo = $i; break }
        }

        if ($nuevo -ne $iActual) {
            $body = @{ name = $marchas[$nuevo].perfil } | ConvertTo-Json
            Invoke-RestMethod -Method Put "$api/api/profiles/active" -Headers $auth -Body $body -ContentType 'application/json' | Out-Null
            Log "marcha $activo -> $($marchas[$nuevo].perfil) (otros usan $otros de $total MiB de VRAM; RAM libre $([int]$ramLibre) MiB)"
        }

        # Un modelo por encima de la marcha permitida se descarga, pero nunca a media respuesta
        if ($cargado -and [array]::IndexOf($marchas, $cargado) -lt $nuevo) {
            $proxy = ($corriendo | Where-Object { $_.model -eq $cargado.modelo }).proxy
            if (-not (@(Invoke-RestMethod "$proxy/slots") | Where-Object { $_.is_processing })) {
                Invoke-RestMethod -Method Post "$api/api/models/unload/$($cargado.modelo)" -Headers $auth | Out-Null
                Log "descargado $($cargado.modelo)"
            }
        }
    }
    catch { Log "sin llama-swap o error: $($_.Exception.Message)" }
    Start-Sleep 5
}
