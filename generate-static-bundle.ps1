# ============================================================
# generate-static-bundle.ps1
# tarkov.dev API에서 전체 데이터를 받아 STATIC_FALLBACK_DATA 형태로 출력
# 사용법: .\generate-static-bundle.ps1
# 출력:   static-bundle.js (index.html에 붙여넣을 코드)
# ============================================================

$GQL = "https://api.tarkov.dev/graphql"

function Invoke-GQL($query) {
    $body = @{ query = $query } | ConvertTo-Json -Compress
    $r = Invoke-RestMethod -Uri $GQL -Method Post -Body $body -ContentType "application/json" -TimeoutSec 60
    if ($r.errors) { Write-Warning "GraphQL error: $($r.errors[0].message)" }
    return $r.data
}

Write-Host "[1/7] Regular EN tasks..."
$FULL = "id name wikiLink kappaRequired experience factionName minPlayerLevel availableDelaySecondsMin availableDelaySecondsMax requiredPrestige { id name prestigeLevel } trader { name imageLink normalizedName } taskRequirements { task { id name } status } traderRequirements { trader { name normalizedName } level } objectives { id description type optional maps { name } ... on TaskObjectiveItem { type item { id name shortName iconLink } count foundInRaid zones { id } requiredKeys { id name shortName } } ... on TaskObjectiveShoot { count } ... on TaskObjectiveSkill { skillLevel { name level } } ... on TaskObjectiveBasic { zones { id } requiredKeys { id name shortName } } ... on TaskObjectiveMark { zones { id } requiredKeys { id name shortName } } } neededKeys { keys { id name shortName iconLink } map { name normalizedName } } startRewards { items { item { id name } count } traderStanding { trader { name } standing } } finishRewards { items { item { name iconLink } count } traderStanding { trader { name normalizedName imageLink } standing } offerUnlock { trader { name } } }"
$KO   = "id name wikiLink objectives { id description }"

$regularEn = Invoke-GQL "{ tasks(lang: en, gameMode: regular) { $FULL } }"
Write-Host "  → $($regularEn.tasks.Count) tasks"

Write-Host "[2/7] PVE EN tasks..."
$pveEn = Invoke-GQL "{ tasks(lang: en, gameMode: pve) { $FULL } }"
Write-Host "  → $($pveEn.tasks.Count) tasks"

Write-Host "[3/7] KO translations..."
$regularKo = Invoke-GQL "{ tasks(lang: ko, gameMode: regular) { $KO } }"
$pveKo     = Invoke-GQL "{ tasks(lang: ko, gameMode: pve)     { $KO } }"

Write-Host "[4/7] Hideout stations..."
$hideout = Invoke-GQL "{ hideoutStations(lang: en) { name normalizedName imageLink levels { id level constructionTime itemRequirements { item { id name shortName iconLink } count attributes { name value } } stationLevelRequirements { station { name } level } traderRequirements { trader { name normalizedName } requirementType value } skillRequirements { name skill { name } level } } } }"

Write-Host "[5/7] Traders loyalty..."
$traders = Invoke-GQL "{ traders(lang: en) { normalizedName currency { shortName } levels { level requiredPlayerLevel requiredReputation requiredCommerce } } }"

Write-Host "[6/7] Gun presets..."
$presets = Invoke-GQL "{ items(type: gun) { id properties { ... on ItemPropertiesWeapon { defaultPreset { id } presets { id } } } } }"

Write-Host "[7/7] KO item names..."
$koItems = Invoke-GQL "{ items(lang: ko) { id name } }"

# ── KO 번역 적용 ──
Write-Host "Applying KO translations..."
$koMap = @{}
foreach ($t in $regularKo.tasks) { $koMap[$t.id] = $t }
foreach ($t in $pveKo.tasks)     { if (-not $koMap[$t.id]) { $koMap[$t.id] = $t } }

$QUEST_NAME_KO_RAW = @{} # 필요 시 여기에 수동 번역 추가

foreach ($tasks in @($regularEn.tasks, $pveEn.tasks)) {
    foreach ($t in $tasks) {
        if ($null -eq $t) { continue }
        $t | Add-Member -NotePropertyName nameEn -NotePropertyValue $t.name -Force
        $ko = $koMap[$t.id]
        $koName = if ($ko) { $ko.name } else { $null }
        $hasKo = $koName -and $koName -ne $t.name
        if ($hasKo) {
            $t | Add-Member -NotePropertyName nameDisplay -NotePropertyValue "$koName ($($t.name))" -Force
        } else {
            $t | Add-Member -NotePropertyName nameDisplay -NotePropertyValue $t.name -Force
        }
        if ($ko -and $ko.objectives) {
            $koObjMap = @{}
            foreach ($o in $ko.objectives) { $koObjMap[$o.id] = $o }
            foreach ($o in $t.objectives) {
                if ($o -and $koObjMap[$o.id] -and $koObjMap[$o.id].description) {
                    $o | Add-Member -NotePropertyName description -NotePropertyValue $koObjMap[$o.id].description -Force
                }
            }
        }
    }
}

# ── koItemMap 구축 ──
$koItemMapObj = @{}
foreach ($it in $koItems.items) {
    if ($it.id -and $it.name -and $it.name -notmatch '[�]') {
        $koItemMapObj[$it.id] = $it.name.Trim()
    }
}

# ── presetToBaseWeaponId 구축 ──
$presetMapObj = @{}
foreach ($it in $presets.items) {
    $dp = $it.properties.defaultPreset
    if ($dp -and $dp.id) { $presetMapObj[$dp.id] = $it.id }
    foreach ($p in $it.properties.presets) {
        if ($p -and $p.id) { $presetMapObj[$p.id] = $it.id }
    }
}

# ── 번들 객체 구성 ──
$bundle = [ordered]@{
    ts              = [long](([datetime]::UtcNow - [datetime]"1970-01-01").TotalMilliseconds)
    regularEnTasks  = @($regularEn.tasks | Where-Object { $_ -ne $null })
    pveEnTasks      = @($pveEn.tasks     | Where-Object { $_ -ne $null })
    hideoutStations = $hideout.hideoutStations
    traders         = $traders.traders
    crafts          = $null   # 용량 절감: 제작법 제외 (캐시 후 로드)
    food            = $null
    drink           = $null
    koItemMap       = $koItemMapObj
    presetMap       = $presetMapObj
}

Write-Host "Serializing..."
$json = $bundle | ConvertTo-Json -Depth 20 -Compress

$sizeMB = [math]::Round($json.Length / 1MB, 2)
Write-Host "Bundle size: ${sizeMB} MB"

$output = "// 생성 시각: $(Get-Date -Format 'yyyy-MM-dd HH:mm') UTC`n// 크기: ${sizeMB} MB`nlet STATIC_FALLBACK_DATA = $json;"
$output | Out-File -FilePath "static-bundle.js" -Encoding utf8

Write-Host ""
Write-Host "완료! static-bundle.js 생성됨"
Write-Host "index.html 에서 'let STATIC_FALLBACK_DATA = null;' 줄을 static-bundle.js 내용으로 교체하세요."
