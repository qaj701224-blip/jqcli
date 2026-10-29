# Temporary opt-in wrapper; all jqcli arguments are forwarded unchanged.
$retryPython = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
$retryScript = Join-Path $PSScriptRoot 'jqcli_read_retry.py'
if (-not (Test-Path -LiteralPath $retryPython)) {
    Write-Error "jqcli virtual environment not found: $retryPython"
    exit 1
}
& $retryPython -X utf8 $retryScript @args
exit $LASTEXITCODE
