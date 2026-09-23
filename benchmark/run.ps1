<#
.SYNOPSIS
  Side-by-side Laya vs Kev benchmark runner.

.DESCRIPTION
  Loads benchmark/cases.json, POSTs each case's state+questions to both
  /v1/systemone endpoints, and prints a per-question agreement table.

  Structure parity : envelope keys must match (Laya's "routing" ignored)
  choice agreement : SAME / DIFF
  noul agreement   : CLOSE if |gap| < 0.30 else GAP
  score agreement  : CLOSE if |gap| < 0.50 else DIFF

.EXAMPLE
  .\benchmark\run.ps1
  .\benchmark\run.ps1 -Lang zh,ta
  .\benchmark\run.ps1 -LayaUrl http://127.0.0.1:8000 -KevUrl http://127.0.0.1:8009
#>
param(
  [string]$LayaUrl = "http://127.0.0.1:8000",
  [string]$KevUrl  = "http://127.0.0.1:8009",
  [string]$ApiKey  = "sk-laya-super-9f4a7c2e-ops-primary",
  [string[]]$Lang,          # filter: en, zh, ms, ta
  [string[]]$Id,            # filter by case id
  [string]$CasesPath = "$PSScriptRoot\cases.json",
  [switch]$FailOnDiff       # exit 1 if any choice/score disagrees
)

$ErrorActionPreference = "Stop"

function Invoke-SystemOne {
  param([string]$Url, [string]$Json, [string]$Key)
  $t = [IO.Path]::GetTempFileName()
  try {
    [IO.File]::WriteAllText($t, $Json, [Text.UTF8Encoding]::new($false))
    $h = @()
    if ($Key) { $h = @("-H", "Authorization: Bearer $Key") }
    $raw = & curl.exe -s -m 180 -w "\n%{http_code}" -X POST "$Url/v1/systemone" `
             -H "content-type: application/json" @h --data-binary "@$t"
    $code = ($raw | Select-Object -Last 1).Trim()
    $body = ($raw | Select-Object -SkipLast 1) -join "`n"
    if ($code -ne "200") { return @{ ok = $false; code = $code; error = $body } }
    return @{ ok = $true; code = $code; data = ($body | ConvertFrom-Json) }
  } finally { Remove-Item $t -ErrorAction SilentlyContinue }
}

$cases = Get-Content $CasesPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($Lang) { $cases = $cases | Where-Object { $_.lang -in $Lang } }
if ($Id)   { $cases = $cases | Where-Object { $_.id -in $Id } }
if (-not $cases) { Write-Host "No cases matched filter."; exit 1 }

$stats = @{ structure_ok = 0; choice_same = 0; choice_total = 0; score_close = 0; score_total = 0; noul_close = 0; noul_total = 0; errors = 0 }
$diffs = @()

foreach ($c in $cases) {
  "`n" + ("=" * 74)
  "[$($c.lang)] $($c.id)  -  $($c.title)"
  ("=" * 74)

  $payload = @{ model = "auto"; state = $c.state; questions = $c.questions } | ConvertTo-Json -Depth 20 -Compress
  $kevJson = $payload -replace '"auto"', '"kev-latest"'
  $layaJson = $payload -replace '"auto"', '"laya-latest"'

  $l = Invoke-SystemOne $LayaUrl $layaJson $ApiKey
  $k = Invoke-SystemOne $KevUrl $kevJson $null

  if (-not $l.ok) { "Laya HTTP $($l.code): $($l.error)"; $stats.errors++ ; continue }
  if (-not $k.ok) { "Kev  HTTP $($k.code): $($k.error)"; $stats.errors++ ; continue }

  $ld = $l.data; $kd = $k.data

  $lKeys = ($ld.PSObject.Properties.Name | Where-Object { $_ -ne "routing" }) | Sort-Object
  $kKeys = $kd.PSObject.Properties.Name | Sort-Object
  $structOk = ($lKeys -join ",") -eq ($kKeys -join ",")
  if ($structOk) { $stats.structure_ok++ }
  "structure : $(if ($structOk) { 'OK' } else { "MISMATCH  kev=[$($kKeys -join ',')]  laya=[$($lKeys -join ',')]" })"
  if ($ld.routing) {
    $r = $ld.routing
    "routing   : $($r.model)  ($($r.reason))"
  }

  foreach ($id in $ld.answers.PSObject.Properties.Name) {
    $la = $ld.answers.$id
    $ka = $kd.answers.$id
    if (-not $ka) { "  $id : MISSING IN KEV"; $stats.errors++; continue }
    if ($la.type -ne $ka.type) { "  $id : TYPE MISMATCH laya=$($la.type) kev=$($ka.type)"; $stats.errors++; continue }

    switch ($la.type) {
      "choice" {
        $stats.choice_total++
        $same = $la.choice -eq $ka.choice
        if ($same) { $stats.choice_same++ } else { $diffs += "$($c.id)/$($id): laya=$($la.choice) kev=$($ka.choice)" }
        $lp = ($la.probabilities.PSObject.Properties | Sort-Object Value -Descending | ForEach-Object { "$($_.Name)=$([math]::Round($_.Value,2))" }) -join " "
        $kp = ($ka.probabilities.PSObject.Properties | Sort-Object Value -Descending | ForEach-Object { "$($_.Name)=$([math]::Round($_.Value,2))" }) -join " "
        "  [choice] $id  $(if ($same) { 'SAME' } else { 'DIFF' })"
        "     Laya: $($la.choice)  [$lp]"
        "     Kev : $($ka.choice)  [$kp]"
      }
      "noul" {
        $stats.noul_total++
        $gap = [math]::Abs($la.noul - $ka.noul)
        $close = $gap -lt 0.30
        if ($close) { $stats.noul_close++ } else { $diffs += "$($c.id)/$($id): noul gap $($la.noul) vs $($ka.noul)" }
        "  [noul ] $id  $(if ($close) { 'CLOSE' } else { 'GAP  ' })  Laya=$([math]::Round($la.noul,2))  Kev=$([math]::Round($ka.noul,2))"
      }
      "score" {
        $stats.score_total++
        $gap = [math]::Abs($la.score - $ka.score)
        $close = $gap -lt 0.50
        if ($close) { $stats.score_close++ } else { $diffs += "$($c.id)/$($id): score gap $($la.score) vs $($ka.score)" }
        "  [score] $id  $(if ($close) { 'CLOSE' } else { 'DIFF' })  Laya=$([math]::Round($la.score,2))  Kev=$([math]::Round($ka.score,2))"
      }
    }
  }
  "latency   : Laya $($ld.latency_ms) ms | Kev $($kd.latency_ms) ms"
  "usage     : Laya $($ld.usage.input_tokens)/$($ld.usage.output_tokens) tok | Kev $($kd.usage.input_tokens)/$($kd.usage.output_tokens) tok (output=0 on Laya is expected)"
}

"`n" + ("#" * 74)
"BENCHMARK SUMMARY  ($($cases.Count) cases)"
("#" * 74)
"structure parity : $($stats.structure_ok)/$($cases.Count)"
"choice SAME      : $($stats.choice_same)/$($stats.choice_total)"
"score  CLOSE     : $($stats.score_close)/$($stats.score_total)"
"noul   CLOSE     : $($stats.noul_close)/$($stats.noul_total)"
"errors           : $($stats.errors)"
if ($diffs) {
  "`nDiffs / gaps:"
  $diffs | ForEach-Object { "  - $_" }
}
if ($FailOnDiff -and (($stats.choice_same -ne $stats.choice_total) -or ($stats.errors -gt 0))) { exit 1 }
