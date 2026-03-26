$src = "$env:USERPROFILE\.local\bin"
$dst = "$env:USERPROFILE\.claude\bin"

$files = @("c-guard", "c-guard.cmd")

foreach ($f in $files) {
    $target = Join-Path $dst $f
    $source = Join-Path $src $f
    if (Test-Path $target) { Remove-Item $target -Force }
    New-Item -ItemType HardLink -Path $target -Target $source | Out-Null
    Write-Host "linked $f"
}