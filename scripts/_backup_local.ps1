# Daily backup of critical project state to a separate disk.
#
# What we back up (in priority order):
#   1. data/articles/        (canonical past-article store, 247 + files)
#   2. data/telemetry.sqlite3 (engagement / regen / cost trace)
#   3. data/rag_index/       (chromadb — re-buildable but slow)
#   4. data/knowledge_topics.json   (seeded topic pool)
#   5. data/knowledge_cooldown.jsonl
#   6. data/seen_urls.json   (collection dedup state)
#   7. docs/knowledge/       (canonical markdown source for RAG)
#   8. config/settings.yaml  (operator config)
#
# What we DO NOT back up daily:
#   - data/images/covers/    (3+ GB, weekly archive instead — see below)
#   - .brave-cdp-profile/    (browser cache, regeneratable)
#   - data/seen_urls.json could be skipped but it's small
#
# Run manually or via Task Scheduler:
#   pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/_backup_local.ps1
#
# Optional: pass -Dest to override the default destination
#   pwsh ... _backup_local.ps1 -Dest "D:\backups\ai-article"

param(
    # 2026-05-11 default switched from D:\ (DVD drive on this machine,
    # 0 free) to E:\backups — same volume as the project but at least
    # outside the repo dir so a misconfigured rm won't take the backup
    # with it. Pass -Dest to override.
    [string]$Dest = "E:\backups\ai-article",
    [switch]$WithImages = $false,
    [int]$RetentionDays = 14
)

$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..")

$stamp = Get-Date -Format "yyyyMMdd_HHmm"
$dest_today = Join-Path $Dest $stamp

if (-not (Test-Path $Dest)) {
    Write-Host "creating backup root: $Dest"
    New-Item -ItemType Directory -Path $Dest | Out-Null
}
New-Item -ItemType Directory -Path $dest_today | Out-Null
Write-Host "backup -> $dest_today"

# Items to mirror. Each entry is (source, destination-subdir).
$items = @(
    @("data\articles",                "data\articles"),
    @("data\telemetry.sqlite3",       "data\telemetry.sqlite3"),
    @("data\rag_index",               "data\rag_index"),
    @("data\knowledge_topics.json",   "data\knowledge_topics.json"),
    @("data\knowledge_cooldown.jsonl","data\knowledge_cooldown.jsonl"),
    @("data\seen_urls.json",          "data\seen_urls.json"),
    @("data\article_performance.jsonl","data\article_performance.jsonl"),
    @("data\rss_feed_failures.json",  "data\rss_feed_failures.json"),
    @("docs\knowledge",               "docs\knowledge"),
    @("config\settings.yaml",         "config\settings.yaml"),
    @("config\prompts.yaml",          "config\prompts.yaml")
)

foreach ($pair in $items) {
    $src = Join-Path $repo $pair[0]
    $dst = Join-Path $dest_today $pair[1]
    if (-not (Test-Path $src)) {
        Write-Host "  skip (missing): $($pair[0])"
        continue
    }
    $dst_parent = Split-Path $dst -Parent
    if (-not (Test-Path $dst_parent)) {
        New-Item -ItemType Directory -Path $dst_parent -Force | Out-Null
    }
    if (Test-Path $src -PathType Container) {
        # Directory mirror via Robocopy (NTFS-friendly, atomic).
        $rc_log = Join-Path $dest_today "_robocopy.log"
        & robocopy $src $dst /MIR /NFL /NDL /NJH /NJS /NP /R:2 /W:5 |
            Out-File -Append -Encoding utf8 $rc_log
        Write-Host "  dir : $($pair[0])"
    } else {
        Copy-Item $src $dst -Force
        Write-Host "  file: $($pair[0])"
    }
}

# Optional image archive (slow / big — opt-in)
if ($WithImages) {
    $img_src = Join-Path $repo "data\images"
    if (Test-Path $img_src) {
        $img_dst = Join-Path $dest_today "data\images"
        Write-Host "  images: $img_src -> $img_dst (this is slow)"
        & robocopy $img_src $img_dst /MIR /NFL /NDL /NJH /NJS /NP /R:2 /W:5 |
            Out-File -Append -Encoding utf8 (Join-Path $dest_today "_robocopy_images.log")
    }
}

# Write a summary manifest at the destination root for human review.
$summary = @"
backup_stamp: $stamp
source_repo:  $repo
included:
$($items | ForEach-Object { "  - " + $_[0] } | Out-String)
images_included: $WithImages
host: $env:COMPUTERNAME
"@
$summary | Out-File (Join-Path $dest_today "_MANIFEST.txt") -Encoding utf8

# Retention: drop directories older than $RetentionDays.
Write-Host ""
Write-Host "applying retention ($RetentionDays days) ..."
$cutoff = (Get-Date).AddDays(-$RetentionDays)
Get-ChildItem $Dest -Directory | Where-Object {
    $_.Name -match '^\d{8}_\d{4}$' -and $_.CreationTime -lt $cutoff
} | ForEach-Object {
    Write-Host "  pruning $($_.Name)"
    Remove-Item $_.FullName -Recurse -Force
}

Write-Host ""
Write-Host "DONE: $dest_today"
