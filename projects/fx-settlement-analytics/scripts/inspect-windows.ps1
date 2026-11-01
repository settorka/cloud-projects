$ErrorActionPreference = 'Stop'
$services = Get-Service | Where-Object {
    $_.Name -match 'MSSQL|SQLSERVER|MsDts|MSOLAP'
} | Select-Object Name, Status, DisplayName
$media = Test-Path 'C:\SQLServerFull\setup.exe'
$disks = Get-Disk | Select-Object Number, PartitionStyle, OperationalStatus, Size
[pscustomobject]@{
    Computer = $env:COMPUTERNAME
    SqlServices = @($services)
    InstallationMediaPresent = $media
    Disks = @($disks)
    Python = [bool](Get-Command python.exe -ErrorAction SilentlyContinue)
    SqlCmd = [bool](Get-Command sqlcmd.exe -ErrorAction SilentlyContinue)
} | ConvertTo-Json -Depth 4
