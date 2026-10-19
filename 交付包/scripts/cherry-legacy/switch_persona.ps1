# 小九人格切换器 —— 交互式菜单
$ErrorActionPreference = 'Stop'
$P = 'E:\本地ai\personas'
$CherryExe = 'E:\本地ai\CherryStudio\Cherry-Studio-CN-portable.exe'
$Applier = 'E:\本地ai\apply_persona.py'

function Get-Personas {
    Get-ChildItem "$P\*.txt" -File | Sort-Object Name | ForEach-Object {
        [PSCustomObject]@{
            Name  = $_.BaseName
            Chars = ([System.IO.File]::ReadAllText($_.FullName)).Length
        }
    }
}

function Show-Header {
    Clear-Host
    Write-Host '==================================================' -ForegroundColor Cyan
    Write-Host '   小九 · 人格切换' -ForegroundColor Cyan
    Write-Host '==================================================' -ForegroundColor Cyan
    Write-Host ''
}

while ($true) {
    Show-Header
    $list = @(Get-Personas)
    Write-Host '  可用人格：' -ForegroundColor White
    Write-Host ''
    for ($i = 0; $i -lt $list.Count; $i++) {
        Write-Host ("    [{0}] {1,-24} {2,5} 字符" -f ($i + 1), $list[$i].Name, $list[$i].Chars)
    }
    Write-Host ''
    Write-Host '    [Q] 退出' -ForegroundColor DarkGray
    Write-Host ''

    $cur = & python $Applier --current 2>$null | Select-String '提示词'
    if ($cur) { Write-Host "  当前：$($cur.ToString().Trim())" -ForegroundColor DarkGray; Write-Host '' }

    $sel = Read-Host '  请输入编号'
    if ($sel -match '^[Qq]') { Write-Host ''; Write-Host '  已退出。' -ForegroundColor DarkGray; break }

    $idx = 0
    if (-not [int]::TryParse($sel, [ref]$idx) -or $idx -lt 1 -or $idx -gt $list.Count) {
        Write-Host ''
        Write-Host '  ❌ 编号无效' -ForegroundColor Red
        Start-Sleep -Seconds 2
        continue
    }

    $pick = $list[$idx - 1].Name
    Write-Host ''
    Write-Host "  已选择：$pick" -ForegroundColor Green
    Write-Host ''

    Write-Host '  [1/4] 关闭 Cherry Studio ...' -ForegroundColor Yellow
    Get-Process | Where-Object { $_.ProcessName -match 'Cherry' } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 7
    $left = @(Get-Process | Where-Object { $_.ProcessName -match 'Cherry' }).Count
    Write-Host "        剩余进程 $left" -ForegroundColor DarkGray

    Write-Host '  [2/4] 应用人格 ...' -ForegroundColor Yellow
    & python $Applier $pick 2>&1 | Select-Object -Last 6 | ForEach-Object {
        Write-Host "        $_" -ForegroundColor DarkGray
    }

    Write-Host '  [3/4] 重启 Cherry Studio ...' -ForegroundColor Yellow
    Start-Process $CherryExe
    Write-Host '  [4/4] 等待窗口就绪 ...' -ForegroundColor Yellow
    Start-Sleep -Seconds 22
    $n = @(Get-Process | Where-Object { $_.ProcessName -match 'Cherry' }).Count
    $win = @(Get-Process | Where-Object { $_.ProcessName -match 'Cherry' -and $_.MainWindowTitle }).Count

    Write-Host ''
    if ($n -gt 0) {
        Write-Host "  ✅ 完成 —— Cherry Studio 已启动（$n 个进程）" -ForegroundColor Green
    } else {
        Write-Host '  ⚠️ Cherry Studio 没起来，请手动双击 启动CherryStudio.bat' -ForegroundColor Red
    }
    Write-Host ''
    Write-Host '  按任意键返回菜单 ...' -ForegroundColor DarkGray
    $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
}
