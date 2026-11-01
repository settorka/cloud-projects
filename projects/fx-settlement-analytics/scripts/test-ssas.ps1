$ErrorActionPreference = 'Stop'
$assembly = Get-ChildItem 'C:\Windows\Microsoft.NET\assembly\GAC_MSIL\Microsoft.AnalysisServices.AdomdClient' -Filter Microsoft.AnalysisServices.AdomdClient.dll -Recurse | Select-Object -First 1
Add-Type -Path $assembly.FullName
function Read-Sql([string]$Query) {
    $connection = New-Object Data.SqlClient.SqlConnection('Server=localhost;Database=FxWarehouse;Integrated Security=True;')
    try {
        $connection.Open()
        $command = $connection.CreateCommand()
        $command.CommandText = $Query
        $table = New-Object Data.DataTable
        $reader = $command.ExecuteReader()
        try { $table.Load($reader) } finally { $reader.Dispose() }
        return ,$table
    } finally { $connection.Dispose() }
}
$as = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection('Data Source=localhost:2384;Initial Catalog=FxSettlement;')
function Read-Dax([string]$Query) {
    $command = $as.CreateCommand()
    $command.CommandText = $Query
    $table = New-Object Data.DataTable
    $reader = $command.ExecuteReader()
    try { $table.Load($reader) } finally { $reader.Dispose(); $command.Dispose() }
    return ,$table
}
function Assert-Blank($Value,[string]$Message) {
    if ($Value -ne [DBNull]::Value -and $null -ne $Value) { throw $Message }
}
try {
    $as.Open()
    $guard = Read-Dax 'EVALUATE ROW("Legs",[Expected Legs],"Outstanding",[Gross Outstanding])'
    Assert-Blank $guard.Rows[0][0] 'Measures must require one batch.'
    Assert-Blank $guard.Rows[0][1] 'Money must not sum across batches/currencies.'
    $batches = Read-Sql 'SELECT BatchId FROM analytics.Batch ORDER BY TradeCount;'
    $checks = 0
    foreach ($batch in $batches.Rows) {
        $id = $batch.BatchId.ToString()
        if ($id -notmatch '^[a-fA-F0-9]{64}$') { throw 'Unexpected batch identifier.' }
        $batchFilter = "TREATAS({`"$id`"},'Batch'[BatchId])"
        $guard = Read-Dax ("EVALUATE CALCULATETABLE(ROW(`"Outstanding`",[Gross Outstanding]),$batchFilter)")
        Assert-Blank $guard.Rows[0][0] 'Money must require one explicit currency.'
        foreach ($currency in @('GBP','EUR','USD')) {
            foreach ($pair in @('','EUR/USD','EUR/GBP','GBP/USD')) {
                foreach ($counterparty in @('','CP01')) {
                    foreach ($direction in @('','pay','receive')) {
                        $filters = @($batchFilter,"TREATAS({`"$currency`"},'Currency'[Currency])")
                        $where = "BatchId='$id' AND Currency='$currency'"
                        if ($pair) {
                            $filters += "TREATAS({`"$pair`"},'CurrencyPair'[Pair])"
                            $where += " AND Pair='$pair'"
                        }
                        if ($counterparty) {
                            $filters += "TREATAS({`"$counterparty`"},'Counterparty'[Counterparty])"
                            $where += " AND Counterparty='$counterparty'"
                        }
                        if ($direction) {
                            $filters += "TREATAS({`"$direction`"},'Direction'[Direction])"
                            $where += " AND Direction='$direction'"
                        }
                        $sql = Read-Sql @"
SELECT COUNT(*) AS Legs,COALESCE(SUM(CASE WHEN SettlementStatus='settled' THEN 1 ELSE 0 END),0) AS Settled,
 COALESCE(SUM(CASE WHEN OutstandingAmount>0 THEN 1 ELSE 0 END),0) AS OutstandingLegs,
 COALESCE(SUM(IsLate),0) AS Late,COALESCE(SUM(IsOverdue),0) AS Overdue,
 COALESCE(SUM(OutstandingAmount),0) AS Outstanding,COALESCE(SUM(ExpectedAmount),0) AS Expected,
 COALESCE(SUM(AllocatedAmount),0) AS Allocated
FROM analytics.SettlementLeg WHERE $where;
"@
                        $dax = Read-Dax ("EVALUATE CALCULATETABLE(ROW(`"Legs`",[Expected Legs],`"Settled`",[Settled Legs],`"OutstandingLegs`",[Outstanding Legs],`"Late`",[Late Legs],`"Overdue`",[Overdue Legs],`"Outstanding`",[Gross Outstanding],`"Expected`",[Gross Expected],`"Allocated`",[Gross Allocated])," + ($filters -join ',') + ')')
                        for ($column=0; $column -lt $sql.Columns.Count; $column++) {
                            if ([decimal]$sql.Rows[0][$column] -ne [decimal]$dax.Rows[0][$column]) {
                                throw "SQL/DAX mismatch: batch=$id currency=$currency pair=$pair counterparty=$counterparty direction=$direction column=$column"
                            }
                        }
                        $sql = Read-Sql @"
SELECT COUNT(*) AS Payments,COALESCE(SUM(CASE WHEN PaymentStatus<>'matched' THEN 1 ELSE 0 END),0) AS Exceptions,
 COALESCE(SUM(CASE WHEN PaymentStatus='duplicate_candidate' THEN 1 ELSE 0 END),0) AS Duplicates,
 COALESCE(SUM(CASE WHEN PaymentStatus='overpayment' THEN 1 ELSE 0 END),0) AS Overpaid,
 COALESCE(SUM(UnappliedAmount),0) AS Unapplied FROM analytics.Payment WHERE $where;
"@
                        $dax = Read-Dax ("EVALUATE CALCULATETABLE(ROW(`"Payments`",[Payments],`"Exceptions`",[Payment Exceptions],`"Duplicates`",[Duplicate Candidates],`"Overpaid`",[Overpaid Payments],`"Unapplied`",[Unapplied Payment Amount])," + ($filters -join ',') + ')')
                        for ($column=0; $column -lt $sql.Columns.Count; $column++) {
                            if ([decimal]$sql.Rows[0][$column] -ne [decimal]$dax.Rows[0][$column]) { throw "Payment SQL/DAX mismatch: column=$column SQL=$($sql.Rows[0][$column]) DAX=$($dax.Rows[0][$column]) $where" }
                        }
                        $checks++
                    }
                }
            }
        }
        $minimum = Read-Sql "SELECT MIN(DueDate) AS DueDate FROM analytics.SettlementLeg WHERE BatchId='$id';"
        $day = [datetime]$minimum.Rows[0].DueDate
        $dateFilter = "TREATAS({DATE($($day.Year),$($day.Month),$($day.Day))},'SettlementDate'[Date])"
        $sql = Read-Sql ("SELECT COUNT(*) AS Legs FROM analytics.SettlementLeg WHERE BatchId='$id' AND DueDate='" + $day.ToString('yyyy-MM-dd') + "';")
        $dax = Read-Dax ("EVALUATE CALCULATETABLE(ROW(`"Legs`",[Expected Legs]),$batchFilter,$dateFilter)")
        if ([int]$sql.Rows[0][0] -ne [int]$dax.Rows[0][0]) { throw 'Due-date relationship does not filter legs correctly.' }
        $ratio = Read-Dax ("EVALUATE CALCULATETABLE(ROW(`"Rate`",[Leg Settlement Rate],`"Numerator`",[Settled Legs],`"Denominator`",[Expected Legs]),$batchFilter)")
        $expectedRate = [double]$ratio.Rows[0][1]/[double]$ratio.Rows[0][2]
        if ([Math]::Abs([double]$ratio.Rows[0][0]-$expectedRate) -gt 0.000000000001) { throw 'Settlement rate denominator is incorrect.' }
    }
    Write-Output "PASS: $checks filtered contexts agree exactly between deployed DAX and SQL; batch/currency guards, due-date relationship and ratio checks passed."
} finally { $as.Dispose() }
