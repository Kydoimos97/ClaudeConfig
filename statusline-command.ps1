$ESC = [char]27
$R = "$ESC[0m"
$GR = "$ESC[90m"
$MG = "$ESC[95m"
$CY = "$ESC[96m"
$GN = "$ESC[92m"
$YL = "$ESC[93m"
$RD = "$ESC[91m"

function val-color([double]$v, [double]$warn, [double]$bad) {
    if ($v -ge $bad) { return $RD }
    if ($v -ge $warn) { return $YL }
    return $GN
}

function fmt-duration([long]$totalSecs) {
    $h = [math]::Floor($totalSecs / 3600)
    $m = [math]::Floor(($totalSecs % 3600) / 60)
    if ($h -gt 0 -and $m -gt 0) { return "${h}h${m}m" }
    if ($h -gt 0)               { return "${h}h" }
    if ($m -gt 0)               { return "${m}m" }
    return "${totalSecs}s"
}

function fmt-osc8([string]$text, [string]$url) {
    $bell = [char]7
    return "${ESC}]8;;${url}${bell}${text}${ESC}]8;;${bell}"
}

$PIPE = " ${GR}|${R} "

$raw = [Console]::In.ReadToEnd()
$data = $raw | ConvertFrom-Json

try {

    $segs = [System.Collections.Generic.List[string]]::new()

    # ── Model tag ────────────────────────────────────────────────────────────────
    $modelId = $null
    if ($null -ne $data.model -and $null -ne $data.model.id) {
        $modelId = $data.model.id
    }
    elseif ($null -ne $data.model) {
        $modelId = "$($data.model)"
    }
    $modelTag = $null
    if ($modelId) {
        $modelTag = switch -Wildcard ($modelId.ToLower()) {
            '*opus*'   { 'Opus'   }
            '*sonnet*' { 'Sonnet' }
            '*haiku*'  { 'Haiku'  }
            default    { $modelId.Substring(0, 1).ToUpper() + $modelId.Substring(1, [math]::Min(7, $modelId.Length - 1)) }
        }
    }

    # ── 1  Lim:52%/3h2m (always first) ──────────────────────────────────────────
    $fiveHour = $data.rate_limits.five_hour
    if ($null -ne $fiveHour) {
        $pct  = $fiveHour.used_percentage

        $pctColor = val-color $pct 75 90
        $limStr   = "${R}${pctColor}$("{0:0}" -f $pct)%${R}"

        if ($null -ne $fiveHour.resets_at -and $fiveHour.resets_at -gt 0) {
            $secsLeft = [long]$fiveHour.resets_at - ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())
            if ($secsLeft -gt 0) {
                $durColor = if ($pct -ge 75) {
                    if     ($secsLeft -ge 3600) { $RD }
                    elseif ($secsLeft -ge 600)  { $YL }
                    else                        { $GN }
                } else { $GR }
                $limStr += "${GR}/${R}${durColor}$(fmt-duration $secsLeft)${R}"
            }
        }
        $segs.Add($limStr)
    }

    # ── 2  Agent(Model) @ Repo(branch) ──────────────────────────────────────────
    $s2parts = [System.Collections.Generic.List[string]]::new()

    $agentStr = ''
    $agentName = $null
    if ($null -ne $data.agent -and $null -ne $data.agent.name) {
        $agentName = $data.agent.name
    }
    if ($agentName) {
        $agentStr = "${CY}$($agentName.Substring(0,1).ToUpper() + $agentName.Substring(1))${R}"
    }
    if ($modelTag) {
        $tag = "${GR}(${MG}${modelTag}${GR})${R}"
        $agentStr = if ($agentStr) { "${agentStr}${tag}" } else { $tag }
    }
    if ($agentStr) { $s2parts.Add($agentStr) }

    $projectDir = $data.workspace.project_dir
    $branch = $null
    $wt = $data.worktree
    if ($null -ne $wt -and $null -ne $wt.branch -and $wt.branch -ne '') {
        $branch = $wt.branch
    }
    elseif ($projectDir) {
        $branch = (git -C $projectDir branch --show-current 2>$null)
    }

    # Mirror Prompt.psm1: derive the display name from the actual worktree toplevel,
    # not the workspace project_dir (which points to the main repo for linked worktrees).
    # Priority: $wt.path (Claude Code worktree path) → git show-toplevel → $projectDir.
    $repoStr = ''
    $repoNameSource = $null
    if ($null -ne $wt -and $null -ne $wt.path -and $wt.path -ne '') {
        $repoNameSource = $wt.path
    }
    elseif ($projectDir) {
        $toplevel = git -C $projectDir rev-parse --show-toplevel 2>$null
        $repoNameSource = if ($toplevel) { $toplevel } else { $projectDir }
    }
    # Resolve GitHub remote URL (SSH → HTTPS), mirroring Prompt.psm1's Get-GitRemoteUrl.
    $remoteUrl = $null
    $gitRoot = if ($repoNameSource) { $repoNameSource } else { $projectDir }
    if ($gitRoot) {
        $rawRemote = git -C $gitRoot remote get-url origin 2>$null
        if ($rawRemote) {
            if ($rawRemote -match '^git@([^:]+):(.+?)(?:\.git)?$') {
                $remoteUrl = "https://$($Matches[1])/$($Matches[2])"
            } else {
                $remoteUrl = $rawRemote -replace '\.git$', ''
            }
        }
    }

    if ($repoNameSource) {
        $repoLeaf = Split-Path $repoNameSource -Leaf
        $repoText = if ($remoteUrl) { fmt-osc8 $repoLeaf $remoteUrl } else { $repoLeaf }
        $repoStr = "${CY}${repoText}${R}"
    }
    if ($branch) {
        $branchUrl  = if ($remoteUrl) { "$remoteUrl/tree/$branch" } else { $null }
        $branchText = if ($branchUrl) { fmt-osc8 $branch $branchUrl } else { $branch }
        $repoStr += "${GR}(${R}${MG}${branchText}${R}${GR})${R}"
    }
    if ($repoStr) { $s2parts.Add($repoStr) }

    if ($s2parts.Count -gt 0) { $segs.Add($s2parts -join " ${GR}@${R} ") }

    # ── 3  Diff:+45/-12  Dur:23m  Ctx:58% ───────────────────────────────────────
    $s3parts = [System.Collections.Generic.List[string]]::new()

    $linesAdded   = if ($null -ne $data.cost) { $data.cost.total_lines_added }   else { $null }
    $linesRemoved = if ($null -ne $data.cost) { $data.cost.total_lines_removed } else { $null }
    if ($null -ne $linesAdded -and $null -ne $linesRemoved) {
        $s3parts.Add("${GR}Diff:${R}${GN}+${linesAdded}${R}${GR}/${R}${RD}-${linesRemoved}${R}")
    }

    $durationMs = if ($null -ne $data.cost) { $data.cost.total_duration_ms } else { $null }
    if ($null -ne $durationMs -and $durationMs -gt 0) {
        $durSecs = [math]::Floor($durationMs / 1000)
        $durStr  = fmt-duration $durSecs
        $s3parts.Add("${GR}Dur:${R}${CY}${durStr}${R}")
    }

    $usedPct = $data.context_window.used_percentage
    if ($null -ne $usedPct) {
        $ctxColor = val-color $usedPct 70 85
        $s3parts.Add("${GR}Ctx:${R}${ctxColor}${usedPct}%${R}")
    }

    if ($s3parts.Count -gt 0) { $segs.Add($s3parts -join ' ') }

    # ── 4  Weekly rate limit (only when hot ≥ 75%) ───────────────────────────────
    $tailParts = [System.Collections.Generic.List[string]]::new()

    $sevenDay = $data.rate_limits.seven_day
    if ($null -ne $sevenDay -and $sevenDay.used_percentage -ge 75) {
        $pct     = $sevenDay.used_percentage
        $wkColor = val-color $pct 75 90
        $wkStr   = "${GR}7d:${R}${wkColor}$("{0:0}" -f $pct)%${R}"
        if ($null -ne $sevenDay.resets_at -and $sevenDay.resets_at -gt 0) {
            $secsLeft = [long]$sevenDay.resets_at - ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())
            if ($secsLeft -gt 0) {
                $wkStr += "${GR}/${R}${YL}$(fmt-duration $secsLeft)${R}"
            }
        }
        $tailParts.Add($wkStr)
    }

    if ($tailParts.Count -gt 0) { $segs.Add($tailParts -join ' ') }

    Write-Output ($segs -join $PIPE)

}
catch {
    $debugFile = Join-Path $env:TEMP 'status-debug.log'
    "=== STATUS ERROR ===" | Out-File -FilePath $debugFile -Append -Encoding utf8
    $_.Exception.Message   | Out-File -FilePath $debugFile -Append -Encoding utf8
    $_.ScriptStackTrace    | Out-File -FilePath $debugFile -Append -Encoding utf8
    "=== END ERROR ==="    | Out-File -FilePath $debugFile -Append -Encoding utf8
}