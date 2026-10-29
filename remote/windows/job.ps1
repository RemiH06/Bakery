# Trabajos largos en Pixilate que sobreviven al cerrar SSH (OpenSSH en Windows mata los procesos de la sesión).
# Corren como tarea programada S4U: sin sesión abierta, sin contraseña guardada, con acceso a la GPU.
#   job.ps1 start <nombre> <carpeta> "<comando>" [-AtStartup]
#   job.ps1 list
#   job.ps1 log <nombre> [-Tail 100]
#   job.ps1 stop <nombre>
param(
    [Parameter(Mandatory)][ValidateSet('start', 'list', 'log', 'stop')][string]$Verb,
    [string]$Name,
    [string]$Dir,
    [string]$Command,
    [int]$Tail = 40,
    # Además de lanzarlo ahora, lo vuelve a lanzar en cada arranque de Windows, sin sesión abierta
    [switch]$AtStartup
)
$ErrorActionPreference = 'Stop'
$root = "$HOME\bakery-jobs"
$task = "bakery-$Name"
if ($Verb -ne 'list' -and -not $Name) { throw 'Falta el nombre del trabajo' }

switch ($Verb) {
    'start' {
        if (-not $Dir -or -not $Command) { throw 'Uso: job.ps1 start <nombre> <carpeta> "<comando>"' }
        $Dir = (Resolve-Path $Dir).Path
        New-Item -ItemType Directory -Force $root | Out-Null
        $log = "$root\$Name.log"
        # El comando va a su propio .ps1 para no pelear con comillas anidadas
        Set-Content "$root\$Name.ps1" -Encoding utf8 -Value @"
`$env:PYTHONUNBUFFERED = '1'
Set-Location '$Dir'
"[bakery] inicio `$(Get-Date -f s)" | Out-File -Encoding utf8 '$log'
& { $Command } *>&1 | Out-File -Append -Encoding utf8 '$log'
"[bakery] fin `$(Get-Date -f s) codigo `$LASTEXITCODE" | Out-File -Append -Encoding utf8 '$log'
"@
        $action = New-ScheduledTaskAction -Execute powershell.exe -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$root\$Name.ps1`""
        # En sesiones SSH USERDOMAIN vale WORKGROUP: la cuenta local se nombra con COMPUTERNAME
        $principal = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\$env:USERNAME" -LogonType S4U
        # Sin límite de tiempo (el default corta a las 72 h) y prioridad normal (el default es baja).
        # En una laptop (Aerilate) el default tampoco arranca con batería y mata la tarea al desconectar el cargador
        $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -Priority 4 `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        $trigger = if ($AtStartup) { @{ Trigger = New-ScheduledTaskTrigger -AtStartup } } else { @{} }
        Register-ScheduledTask -TaskName $task -Action $action -Principal $principal -Settings $settings @trigger -Force | Out-Null
        Start-ScheduledTask $task
        "Lanzado $task. Log: $log"
    }
    'list' {
        Get-ScheduledTask -TaskName 'bakery-*' -EA SilentlyContinue | ForEach-Object {
            $i = $_ | Get-ScheduledTaskInfo
            [pscustomobject]@{ Nombre = $_.TaskName -replace '^bakery-'; Estado = $_.State; Inicio = $i.LastRunTime; Resultado = $i.LastTaskResult }
        } | Format-Table -AutoSize
    }
    'log' { Get-Content "$root\$Name.log" -Tail $Tail }
    'stop' {
        Stop-ScheduledTask $task
        Unregister-ScheduledTask $task -Confirm:$false
        "Detenido $task"
    }
}
