# Stop only a listener explicitly launched for this workspace.
param(
    [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
    [Parameter(Mandatory = $true)][string]$AppDir
)
$ErrorActionPreference = 'Stop'
try {
    $owners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop |
        Where-Object { $_.LocalPort -eq $Port } |
        Select-Object -ExpandProperty OwningProcess -Unique)
    if ($owners.Count -eq 0) {
        Write-Output 'Service is already stopped.'
        exit 0
    }
    $root = (Resolve-Path -LiteralPath $AppDir).Path.TrimEnd('\', '/')
    $rootArg = '(?:"' + [regex]::Escape($root) + '"|' + [regex]::Escape($root) + ')(?=\s|$)'
    $verified = @()
    foreach ($ownerId in $owners) {
        $info = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerId"
        if ($null -eq $info) { continue }
        $line = $info.CommandLine
        if ($info.Name -notmatch '^python(?:w|3(?:\.\d+)?)?\.exe$' -or
            $line -notmatch '(?i)(?:^|\s)-m\s+uvicorn\s' -or
            $line -notmatch '(?:^|\s)app\.main:create_app(?=\s|$)' -or
            $line -notmatch ('(?:^|\s)--port\s+' + $Port + '(?=\s|$)') -or
            $line -notmatch ('(?i)(?:^|\s)--app-dir\s+' + $rootArg)) {
            throw "Refusing to stop PID $ownerId on port ${Port}: workspace ownership cannot be verified. Stop this legacy or unrelated process manually once."
        }
        $verified += $info
    }
    # Verify every listener before stopping any of them; recheck PID identity.
    foreach ($info in $verified) {
        $current = Get-CimInstance Win32_Process -Filter "ProcessId = $($info.ProcessId)"
        if ($null -eq $current) { continue }
        if ($current.CreationDate -ne $info.CreationDate -or $current.CommandLine -ne $info.CommandLine) {
            throw 'Process identity changed; refusing to stop it.'
        }
        Stop-Process -Id $info.ProcessId -ErrorAction Stop
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    do {
        $remaining = @(Get-NetTCPConnection -State Listen -ErrorAction Stop |
            Where-Object { $_.LocalPort -eq $Port })
        if ($remaining.Count -eq 0) {
            Write-Output 'Service stopped.'
            exit 0
        }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Port $Port was not released within 15 seconds."
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}
