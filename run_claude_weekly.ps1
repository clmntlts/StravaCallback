<#
.SYNOPSIS
  Routine hebdo LOCALE avec Claude comme coach — version Windows (PowerShell).

.DESCRIPTION
  Lance le CLI Claude Code en mode headless sur la commande /weekly, DEPUIS TON PC
  (IP residentielle) : Claude genere la semaine, la juge, envoie l'email et
  planifie sur Garmin Connect. A planifier via le Planificateur de taches Windows.

  Garde "une fois par semaine" : si le PC se reveille plusieurs fois (ou si la
  tache rattrape un creneau manque), le run n'a lieu qu'une fois par semaine ISO.

  Ce n'est PAS la "Routine" cloud du produit (celle-ci tourne dans le cloud, IP
  datacenter -> Garmin bloque). Ici tout tourne en local.

.PARAMETER Force
  Ignore la garde hebdo et relance meme si la semaine a deja ete traitee.

.EXAMPLE
  .\run_claude_weekly.ps1
  .\run_claude_weekly.ps1 -Force        # test manuel, rejoue la semaine

.NOTES
  Prerequis (une fois) :
    - Claude Code installe + authentifie :  claude login   (ou $env:ANTHROPIC_API_KEY)
    - Secrets dans training\.env  (copie training\.env.example)
    - Login Garmin fait une fois :  python training\generate.py garmin-connect-login
#>
[CmdletBinding()]
param([switch]$Force)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
Set-Location $Root

# 1) Charger les secrets locaux depuis training\.env (jamais committe).
$envFile = Join-Path $Root 'training\.env'
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq '' -or $line.StartsWith('#')) { return }
    $idx = $line.IndexOf('=')
    if ($idx -lt 1) { return }
    $key = $line.Substring(0, $idx).Trim()
    $val = $line.Substring($idx + 1).Trim()
    if ($val.Length -ge 2 -and
        (($val[0] -eq '"' -and $val[-1] -eq '"') -or ($val[0] -eq "'" -and $val[-1] -eq "'"))) {
      $val = $val.Substring(1, $val.Length - 2)
    }
    Set-Item -Path "Env:$key" -Value $val
  }
} else {
  Write-Warning "training\.env introuvable — copie training\.env.example puis renseigne-le."
}

# 2) Journalisation + garde hebdo (fichier d'horodatage dans training\logs\, gitignore).
$logDir = Join-Path $Root 'training\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log   = Join-Path $logDir ("claude-weekly-{0}.log" -f (Get-Date -Format 'yyyy-MM-dd'))
$stamp = Join-Path $logDir '.last-week-run'

# [System.Globalization.ISOWeek] n'existe pas sous .NET Framework (Windows
# PowerShell 5.1) : calcul ISO 8601 manuel via le jeudi de la semaine courante.
$now      = Get-Date
$dow      = [int]$now.DayOfWeek; if ($dow -eq 0) { $dow = 7 }   # dimanche -> 7
$thursday = $now.AddDays(4 - $dow)
$isoYear  = $thursday.Year
$jan1     = Get-Date -Year $isoYear -Month 1 -Day 1
$iso      = [int][Math]::Ceiling((($thursday - $jan1).Days + 1) / 7.0)
$thisWeek = "{0}-W{1:D2}" -f $isoYear, $iso

"===== run $(Get-Date -Format o) (semaine $thisWeek) =====" | Tee-Object -FilePath $log -Append

if (-not $Force -and (Test-Path $stamp) -and ((Get-Content $stamp -Raw).Trim() -eq $thisWeek)) {
  "Deja execute pour $thisWeek — rien a faire (utilise -Force pour rejouer)." |
    Tee-Object -FilePath $log -Append
  exit 0
}

# 3) Binaire Claude + posture de permissions (surchargeables par l'environnement).
#    En run non-surveille, --dangerously-skip-permissions evite tout prompt. C'est
#    puissant : a n'utiliser que sur TON PC de confiance. Alternative plus stricte :
#      $env:CLAUDE_PERM = '--allowedTools Bash Read Edit'
$claudeBin = if ($env:CLAUDE_BIN) { $env:CLAUDE_BIN } else { 'claude' }
$perm      = if ($env:CLAUDE_PERM) { $env:CLAUDE_PERM } else { '--dangerously-skip-permissions' }
$permArgs  = $perm.Split(' ')

# 4) Lancer Claude headless sur /weekly. `-p` = mode non-interactif.
#    (Verifie les drapeaux dispo avec `claude --help` selon ta version.)
& $claudeBin -p "/weekly" @permArgs 2>&1 | Tee-Object -FilePath $log -Append
$rc = $LASTEXITCODE

if ($rc -eq 0) {
  Set-Content -Path $stamp -Value $thisWeek    # marque la semaine comme traitee
}
"===== fin $(Get-Date -Format o) — code $rc =====" | Tee-Object -FilePath $log -Append
exit $rc
