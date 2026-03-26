$dst = "$env:USERPROFILE\.claude\bin"

$links = @(
    @{ src = "$env:USERPROFILE\.local\bin\c-guard";     dst = "$dst\c-guard" },
    @{ src = "$env:USERPROFILE\.local\bin\c-guard.cmd"; dst = "$dst\c-guard.cmd" },
    @{ src = "C:\Bin\usePwsh7";                         dst = "$dst\usePwsh7" },
    @{ src = "C:\Bin\usePwsh7.cmd";                     dst = "$dst\usePwsh7.cmd" },
    @{ src = "C:\Bin\kiro-cli";                         dst = "$dst\kiro-cli" },
    @{ src = "C:\Bin\kiro-cli.cmd";                     dst = "$dst\kiro-cli.cmd" }
)

foreach ($link in $links) {
    if (Test-Path $link.dst) { Remove-Item $link.dst -Force }
    New-Item -ItemType HardLink -Path $link.dst -Target $link.src | Out-Null
    Write-Host "linked $($link.src) -> $($link.dst)"
}