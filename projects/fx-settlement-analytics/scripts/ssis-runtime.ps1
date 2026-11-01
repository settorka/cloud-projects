# Shared VM-only authentication, artifact publication and SSIS execution.
function Get-FxBlobContext {
    $token = Invoke-RestMethod -Headers @{Metadata = 'true'} -Uri 'http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fstorage.azure.com%2F'
    return @{
        Base = 'https://stfx36c63c6a50e8.blob.core.windows.net/fx-data'
        Headers = @{Authorization = "Bearer $($token.access_token)"; 'x-ms-version' = '2023-11-03'}
    }
}
function Send-FxArtifact($Context, [string]$BlobPath, [string]$LocalPath) {
    $headers = $Context.Headers.Clone()
    $headers['x-ms-blob-type'] = 'BlockBlob'
    Invoke-RestMethod -Method Put -Uri ($Context.Base + '/' + $BlobPath) -Headers $headers -InFile $LocalPath -ContentType 'application/octet-stream' | Out-Null
}
function Invoke-FxPackage($Context, [string]$Kind, $Batch) {
    & 'F:\fx\app\ssis\build-package.ps1' -Kind $Kind
    $path = 'F:\fx\app\ssis\Load' + $Kind + '.dtsx'
    $application = New-Object Microsoft.SqlServer.Dts.Runtime.Application
    $package = $application.LoadPackage($path, $null)
    $started = [DateTimeOffset]::UtcNow
    $result = $package.Execute()
    $errors = @($package.Errors | ForEach-Object { $_.Description })
    $hash = (Get-FileHash $path -Algorithm SHA256).Hash.ToLower()
    $report = [pscustomobject]@{
        RunId = $Batch.run_id
        InputBatchId = $Batch.batch_id
        PreparedBlobPath = $Batch.prepared_blob_path
        PreparedSha256 = $Batch.prepared_sha256
        CodeVersion = $Batch.code_version
        ExecutionId = $package.Variables['System::ExecutionInstanceGUID'].Value.ToString()
        PackageSha256 = $hash
        PackageBlobPath = "deploy/ssis/$hash.dtsx"
        StartedAt = $started.ToString('o')
        FinishedAt = [DateTimeOffset]::UtcNow.ToString('o')
        Result = $result.ToString()
        Errors = $errors
    }
    $reportPath = "F:\fx\data\ssis-$($Batch.run_id).json"
    $report | ConvertTo-Json -Depth 4 | Set-Content $reportPath
    Send-FxArtifact $Context $report.PackageBlobPath $path
    Send-FxArtifact $Context "runs/$($Batch.run_id)/ssis.json" $reportPath
    & sqlcmd -S localhost -E -b -d FxWarehouse -Q "UPDATE audit.PipelineRun SET ssis_execution_id='$($report.ExecutionId)',package_sha256='$hash' WHERE run_id='$($Batch.run_id)';"
    if ($LASTEXITCODE -ne 0) { throw 'SSIS audit update failed.' }
    $report | ConvertTo-Json -Depth 4 | Write-Host
    if ($result.ToString() -ne 'Success') { throw ('SSIS execution failed: ' + ($errors -join '; ')) }
    return $report
}
