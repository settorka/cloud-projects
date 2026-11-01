# Run using Azure Run Command (SYSTEM); adds real SSIS and SSAS services if absent.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
New-Item -ItemType Directory -Path 'C:\fx\logs' -Force | Out-Null
Start-Transcript -Path 'C:\fx\logs\setup-windows.log' -Append
try {
    $raw = @(Get-Disk | Where-Object { $_.PartitionStyle -eq 'RAW' -and $_.Size -eq 64GB })
    if ($raw.Count -gt 1) { throw 'Ambiguous data disks; refusing to initialise.' }
    if ($raw.Count -eq 1) {
        if (Get-Volume -DriveLetter F -ErrorAction SilentlyContinue) {
            throw 'F: is already occupied; refusing to initialise data disk.'
        }
        $raw[0] | Initialize-Disk -PartitionStyle GPT -PassThru |
            New-Partition -UseMaximumSize -DriveLetter F |
            Format-Volume -FileSystem NTFS -NewFileSystemLabel 'FxData' -Confirm:$false | Out-Null
    }
    if (-not (Test-Path 'F:\')) { throw 'Expected persistent data disk F: is unavailable.' }
    New-Item -ItemType Directory -Path 'F:\fx\data', 'F:\fx\sql', 'F:\fx\ssas' -Force | Out-Null

    $features = @()
    if (-not (Get-Service -Name 'MsDtsServer160' -ErrorAction SilentlyContinue)) {
        $features += 'IS'
    }
    if (-not (Get-Service -Name 'MSOLAP$FXTABULAR' -ErrorAction SilentlyContinue)) {
        $features += 'AS'
    }
    if ($features.Count -gt 0) {
        $setup = 'C:\SQLServerFull\setup.exe'
        if (-not (Test-Path $setup)) { throw 'SQL Server installation media not found.' }
        $arguments = @('/Q', '/ACTION=Install', '/IACCEPTSQLSERVERLICENSETERMS',
            ('/FEATURES=' + ($features -join ',')), '/INSTANCENAME=FXTABULAR')
        if ($features -contains 'AS') {
            $arguments += @('/ASSERVERMODE=TABULAR',
                '/ASSVCACCOUNT="NT Service\MSOLAP$FXTABULAR"',
                '/ASSVCSTARTUPTYPE=Automatic',
                ('/ASSYSADMINACCOUNTS="NT AUTHORITY\SYSTEM" "{0}\fxadmin"' -f $env:COMPUTERNAME),
                '/ASDATADIR="F:\fx\ssas"')
        }
        if ($features -contains 'IS') {
            $arguments += '/ISSVCSTARTUPTYPE=Automatic'
        }
        $process = Start-Process $setup -ArgumentList $arguments -Wait -PassThru
        if ($process.ExitCode -notin @(0, 3010)) {
            throw "SQL component setup failed: $($process.ExitCode). Inspect SQL Setup Bootstrap logs."
        }
        if ($process.ExitCode -eq 3010) { Write-Warning 'SQL setup requests a restart.' }
    }
    foreach ($name in @('MSSQLSERVER', 'MsDtsServer160', 'MSOLAP$FXTABULAR')) {
        Start-Service -Name $name
        Get-Service -Name $name | Select-Object Name, Status
    }
} finally {
    Stop-Transcript
}
