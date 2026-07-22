# ============================================================
# generate-static-bundle.ps1
# json.tarkov.dev REST API에서 전체 데이터를 받아 STATIC_FALLBACK_DATA 형태로 출력
# 사용법: .\generate-static-bundle.ps1
# 출력:   static-bundle.js (index.html에 붙여넣을 코드)
# ============================================================

$JSON_API = "https://json.tarkov.dev"
$UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

function Invoke-JsonAPI($path) {
    $uri = "$JSON_API/$path"
    try {
        $r = Invoke-RestMethod -Uri $uri -Method Get `
            -Headers @{ "Accept" = "application/json"; "User-Agent" = $UA } `
            -TimeoutSec 60
        if (-not $r.data) { Write-Warning "데이터 없음: $path"; return $null }
        return $r.data
    } catch {
        Write-Error "요청 실패 ($path): $_"
        return $null
    }
}

Write-Host "[1/7] Regular tasks..."
$regTasksData = Invoke-JsonAPI "regular/tasks"
$regTasksEn   = Invoke-JsonAPI "regular/tasks_en"
$regTasksKo   = Invoke-JsonAPI "regular/tasks_ko"
Write-Host "  → $($regTasksData.tasks.PSObject.Properties.Count) tasks"

Write-Host "[2/7] PVE tasks..."
$pveTasksData = Invoke-JsonAPI "pve/tasks"
$pveTasksEn   = Invoke-JsonAPI "pve/tasks_en"
$pveTasksKo   = Invoke-JsonAPI "pve/tasks_ko"
Write-Host "  → $($pveTasksData.tasks.PSObject.Properties.Count) tasks"

Write-Host "[3/7] Traders..."
$tradersData  = Invoke-JsonAPI "regular/traders"
$tradersEn    = Invoke-JsonAPI "regular/traders_en"

Write-Host "[4/7] Hideout..."
$hideoutData  = Invoke-JsonAPI "regular/hideout"
$hideoutEn    = Invoke-JsonAPI "regular/hideout_en"

Write-Host "[5/7] Items..."
$itemsData    = Invoke-JsonAPI "regular/items"
$itemsEn      = Invoke-JsonAPI "regular/items_en"
$itemsKo      = Invoke-JsonAPI "regular/items_ko"

Write-Host "[6/7] Maps..."
$mapsEn       = Invoke-JsonAPI "regular/maps_en"

Write-Host "[7/7] Processing data..."

# ── 헬퍼: 로케일 키로 번역값 조회 ──────────────────────────────────────────
function Get-Prop($obj, $key) {
    if ($null -eq $obj) { return $null }
    return $obj.$key
}

# ── 아이템 조회 테이블 ──────────────────────────────────────────────────────
$rawItems = if ($itemsData.items) { $itemsData.items } else { $itemsData }
$itemsById = @{}
$koItemMap = @{}

foreach ($prop in $rawItems.PSObject.Properties) {
    $id = $prop.Name
    $it = $prop.Value
    if (-not $it -or -not $it.id) { continue }
    $itemsById[$id] = $it
    $koName = Get-Prop $itemsKo $it.name
    if ($koName -and $koName -notmatch '[�]' -and $koName -notmatch '\x08') {
        $koItemMap[$id] = $koName.Trim()
    }
}

function Get-ItemObj($itemId) {
    $it = $itemsById[$itemId]
    if (-not $it) { return [ordered]@{ id=$itemId; name=$itemId; shortName=$itemId; iconLink=$null } }
    $enName = Get-Prop $itemsEn $it.name
    if (-not $enName) { $enName = $it.normalizedName }
    if (-not $enName) { $enName = $itemId }
    $shortKey = $it.shortName
    $enShort = Get-Prop $itemsEn $shortKey
    if (-not $enShort) { $enShort = ($shortKey -replace '\s*(Name|ShortName)$','') }
    if (-not $enShort) { $enShort = $itemId }
    return [ordered]@{ id=($it.id ?? $itemId); name=$enName; shortName=$enShort; iconLink=$it.iconLink }
}

# ── 상인 조회 테이블 ──────────────────────────────────────────────────────
$tradersById = @{}
foreach ($prop in $tradersData.PSObject.Properties) {
    $t = $prop.Value
    if ($t -and $t.id) { $tradersById[$prop.Name] = $t }
}

function Get-TraderObj($traderId) {
    $t = $tradersById[$traderId]
    if (-not $t) { return [ordered]@{ name=$traderId; normalizedName=$traderId; imageLink=$null } }
    $name = Get-Prop $tradersEn $t.name
    if (-not $name) { $name = $t.normalizedName }
    return [ordered]@{ name=$name; normalizedName=$t.normalizedName; imageLink=$t.imageLink }
}

# ── 지도 이름 조회 ──────────────────────────────────────────────────────────
function Get-MapName($mapId) {
    $n = Get-Prop $mapsEn "$mapId Name"
    if (-not $n) { return $mapId }
    return $n
}

# ── 퀘스트 적용 ──────────────────────────────────────────────────────────────
$taskRefMap = @{}

function Adapt-Tasks($rawTasksData, $enTrans, $koTrans) {
    $result = [System.Collections.Generic.List[object]]::new()
    foreach ($prop in $rawTasksData.tasks.PSObject.Properties) {
        $task = $prop.Value
        if (-not $task -or -not $task.id) { continue }

        $enName = Get-Prop $enTrans $task.name
        if (-not $enName) { $enName = $task.name }
        $koName = Get-Prop $koTrans $task.name
        $hasKo = $koName -and $koName -ne $enName
        $nameDisplay = if ($hasKo) { "$koName ($enName)" } else { $enName }

        $taskRefMap[$task.id] = @{ enName=$enName; nameDisplay=$nameDisplay }

        $objectives = @()
        foreach ($obj in ($task.objectives ?? @())) {
            $descEn = Get-Prop $enTrans $obj.description
            if (-not $descEn) { $descEn = $obj.description }
            $descKo = Get-Prop $koTrans $obj.description
            $desc = if ($descKo) { $descKo } else { $descEn }

            $maps = @()
            foreach ($mid in ($obj.maps ?? @())) {
                $maps += @{ name=(Get-MapName $mid) }
            }

            $rkeys = @()
            foreach ($group in ($obj.requiredKeys ?? @())) {
                $grpItems = @()
                $arr = if ($group -is [System.Array]) { $group } else { @($group) }
                foreach ($k in $arr) {
                    $grpItems += Get-ItemObj $k
                }
                $rkeys += ,@($grpItems)
            }

            $adaptedObj = [ordered]@{
                id          = $obj.id
                description = $desc
                type        = if ($obj.type) { $obj.type } else { 'basic' }
                optional    = [bool]$obj.optional
                count       = [int]($obj.count ?? 0)
                foundInRaid = [bool]$obj.foundInRaid
                maps        = $maps
                zones       = @($obj.zones ?? @())
                requiredKeys= $rkeys
                skillLevel  = $null
            }

            if ($obj.items -and $obj.items.Count -gt 0) {
                $adaptedObj.item = Get-ItemObj $obj.items[0]
            }
            if ($obj.skillLevel -and $obj.skillLevel -is [object]) {
                $sl = $obj.skillLevel
                $adaptedObj.skillLevel = @{
                    name  = if (Get-Prop $enTrans $sl.skill) { Get-Prop $enTrans $sl.skill } else { $sl.skill }
                    level = [int]($sl.level ?? 0)
                }
            }
            $objectives += $adaptedObj
        }

        $neededKeys = @()
        foreach ($nk in ($task.neededKeys ?? @())) {
            $keys = @()
            foreach ($k in ($nk.keys ?? @())) { $keys += Get-ItemObj $k }
            $mapObj = if ($nk.map) { @{ name=(Get-MapName $nk.map); normalizedName=$nk.map } } else { $null }
            $neededKeys += @{ keys=$keys; map=$mapObj }
        }

        $traderReqs = @()
        foreach ($req in ($task.traderRequirements ?? @())) {
            if ($req.requirementType -eq 'level') {
                $traderReqs += @{ trader=(Get-TraderObj $req.trader); level=[int]($req.value ?? 0) }
            }
        }

        $taskReqs = @()
        foreach ($req in ($task.taskRequirements ?? @())) {
            $statusArr = if ($req.status -is [System.Array]) { @($req.status) } else { @($req.status ?? 'complete') }
            $taskReqs += @{
                task   = @{ id=$req.task; name=$req.task; nameEn=$req.task; nameDisplay=$req.task }
                status = $statusArr
            }
        }

        $finItems = @()
        foreach ($r in ($task.finishRewards.items ?? @())) {
            $finItems += @{ item=(Get-ItemObj $r.item); count=[int]($r.count ?? 1) }
        }
        $finStanding = @()
        foreach ($ts in ($task.finishRewards.traderStanding ?? @())) {
            $finStanding += @{ trader=(Get-TraderObj $ts.trader); standing=[double]$ts.standing }
        }
        $finOffers = @()
        foreach ($o in ($task.finishRewards.offerUnlock ?? @())) {
            $finOffers += @{ trader=(Get-TraderObj $o.trader) }
        }

        $startItems = @()
        foreach ($r in ($task.startRewards.items ?? @())) {
            $it = $itemsById[$r.item]
            $itName = if ($it) { Get-Prop $itemsEn $it.name } else { $r.item }
            if (-not $itName) { $itName = $r.item }
            $startItems += @{ item=@{ id=$r.item; name=$itName }; count=[int]($r.count ?? 1) }
        }
        $startStanding = @()
        foreach ($ts in ($task.startRewards.traderStanding ?? @())) {
            $startStanding += @{ trader=@{ name=(Get-TraderObj $ts.trader).name }; standing=[double]$ts.standing }
        }

        $prestige = @()
        if ($task.requiredPrestige) {
            if ($task.requiredPrestige -is [System.Array]) { $prestige = @($task.requiredPrestige) }
            else { $prestige = @($task.requiredPrestige) }
        }

        $adapted = [ordered]@{
            id                        = $task.id
            name                      = $enName
            nameEn                    = $enName
            nameDisplay               = $nameDisplay
            wikiLink                  = $task.wikiLink
            kappaRequired             = [bool]$task.kappaRequired
            lightkeeperRequired       = [bool]$task.lightkeeperRequired
            experience                = [int]($task.experience ?? 0)
            factionName               = if ($task.factionName) { $task.factionName } else { 'Any' }
            minPlayerLevel            = [int]($task.minPlayerLevel ?? 0)
            availableDelaySecondsMin  = [int]($task.availableDelaySecondsMin ?? 0)
            availableDelaySecondsMax  = [int]($task.availableDelaySecondsMax ?? 0)
            trader                    = Get-TraderObj $task.trader
            taskRequirements          = $taskReqs
            traderRequirements        = $traderReqs
            objectives                = $objectives
            neededKeys                = $neededKeys
            startRewards              = @{ items=$startItems; traderStanding=$startStanding }
            finishRewards             = @{ items=$finItems; traderStanding=$finStanding; offerUnlock=$finOffers }
            requiredPrestige          = $prestige
            taskImageLink             = $task.taskImageLink
            normalizedName            = $task.normalizedName
        }
        $result.Add($adapted)
    }
    return $result
}

$regularTasks = Adapt-Tasks $regTasksData $regTasksEn $regTasksKo
$pveTasks     = Adapt-Tasks $pveTasksData $pveTasksEn $pveTasksKo

# 2차 패스: taskRequirements 이름 해석
foreach ($tasks in @($regularTasks, $pveTasks)) {
    foreach ($task in $tasks) {
        foreach ($req in $task.taskRequirements) {
            $ref = $taskRefMap[$req.task.id]
            if ($ref) {
                $req.task.name        = $ref.enName
                $req.task.nameEn      = $ref.enName
                $req.task.nameDisplay = $ref.nameDisplay
            }
        }
    }
}

# ── 하이드아웃 ──────────────────────────────────────────────────────────────
$hideoutStations = @()
foreach ($prop in $hideoutData.PSObject.Properties) {
    $station = $prop.Value
    if (-not $station -or -not $station.id) { continue }

    $stnName = Get-Prop $hideoutEn $station.name
    if (-not $stnName) { $stnName = $station.normalizedName }

    $levels = @()
    foreach ($lv in ($station.levels ?? @())) {
        $itemReqs = @()
        foreach ($req in ($lv.itemRequirements ?? @())) {
            $attrs = @()
            if ($req.attributes -is [System.Management.Automation.PSCustomObject]) {
                foreach ($ap in $req.attributes.PSObject.Properties) {
                    $attrs += @{ name=$ap.Name; value=[string]$ap.Value }
                }
            }
            $itemReqs += @{ item=(Get-ItemObj $req.item); count=[int]$req.count; attributes=$attrs }
        }

        $stnReqs = @()
        foreach ($req in ($lv.stationLevelRequirements ?? @())) {
            $reqStn = $hideoutData.($req.station)
            $reqStnName = if ($reqStn) { Get-Prop $hideoutEn $reqStn.name; if (-not $_) { $reqStn.normalizedName } } else { [string]$req.station }
            if (-not $reqStnName -and $reqStn) { $reqStnName = $reqStn.normalizedName }
            if (-not $reqStnName) { $reqStnName = [string]$req.station }
            $stnReqs += @{ station=@{ name=$reqStnName }; level=[int]$req.level }
        }

        $tReqs = @()
        foreach ($req in ($lv.traderRequirements ?? @())) {
            $tReqs += @{ trader=(Get-TraderObj $req.trader); requirementType=$req.requirementType; value=[int]($req.value ?? 0) }
        }

        $skReqs = @()
        foreach ($req in ($lv.skillRequirements ?? @())) {
            $skName = Get-Prop $hideoutEn $req.skill
            if (-not $skName) { $skName = $req.skill }
            $skReqs += @{ name=($req.id ?? $req.skill); skill=@{ name=$skName }; level=[int]($req.level ?? 0) }
        }

        $levels += [ordered]@{
            id                       = $lv.id
            level                    = [int]$lv.level
            constructionTime         = [int]($lv.constructionTime ?? 0)
            itemRequirements         = $itemReqs
            stationLevelRequirements = $stnReqs
            traderRequirements       = $tReqs
            skillRequirements        = $skReqs
        }
    }

    $hideoutStations += [ordered]@{
        name           = $stnName
        normalizedName = $station.normalizedName
        imageLink      = $station.imageLink
        levels         = $levels
    }
}

# ── 상인 우호도 ─────────────────────────────────────────────────────────────
$adaptedTraders = @()
foreach ($prop in $tradersData.PSObject.Properties) {
    $t = $prop.Value
    if (-not $t -or -not $t.id) { continue }
    $lvls = @()
    foreach ($l in ($t.levels ?? @())) {
        $lvls += @{
            level                = [int]$l.level
            requiredPlayerLevel  = [int]($l.requiredPlayerLevel ?? 0)
            requiredReputation   = [double]($l.requiredReputation ?? 0)
            requiredCommerce     = [int]($l.requiredCommerce ?? 0)
        }
    }
    $adaptedTraders += @{
        normalizedName = $t.normalizedName
        currency       = @{ shortName = if ($t.currency) { $t.currency } else { 'RUB' } }
        levels         = $lvls
    }
}

# ── 번들 구성 ──────────────────────────────────────────────────────────────
$bundle = [ordered]@{
    ts              = [long](([datetime]::UtcNow - [datetime]"1970-01-01").TotalMilliseconds)
    regularEnTasks  = @($regularTasks)
    pveEnTasks      = @($pveTasks)
    hideoutStations = $hideoutStations
    traders         = $adaptedTraders
    koItemMap       = $koItemMap
    presetMap       = @{}   # JSON API에서 총기 프리셋 미구현
    crafts          = $null
    food            = $null
    drink           = $null
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
