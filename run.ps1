# «Модус Голос» без Docker — Windows (PowerShell). Создаёт окружение .venv, ставит зависимости, поднимает демо-базу и сервер.
# Требуется Python 3.11 или новее (python.org, при установке отметить «Add python.exe to PATH»).
# Запуск из папки проекта:  powershell -ExecutionPolicy Bypass -File .\run.ps1
# Порт — переменная MF_PORT (по умолчанию 8090). Ключи и настройки — в .env по образцу .env.example (без ключа — демо-режим).
$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot
$Port = if ($env:MF_PORT) { $env:MF_PORT } else { '8090' }

function Test-Python([string[]]$cmd) {
    try {
        $exe = $cmd[0]; $rest = @($cmd | Select-Object -Skip 1)
        & $exe @rest -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

$py = $null
foreach ($c in @(@('py', '-3.13'), @('py', '-3.12'), @('py', '-3.11'), @('python'), @('python3'))) {
    if (Test-Python $c) { $py = $c; break }
}
if (-not $py) {
    Write-Host 'Нужен Python 3.11 или новее: https://www.python.org/downloads/ (отметить «Add python.exe to PATH»). Либо Docker Desktop: docker compose up --build' -ForegroundColor Red
    exit 1
}
$pyExe = $py[0]; $pyArgs = @($py | Select-Object -Skip 1)
Write-Host ("Python: " + (& $pyExe @pyArgs --version))

$venvPy = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
    Write-Host 'Создаём окружение .venv…'
    & $pyExe @pyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'не удалось создать .venv' }
}
Write-Host 'Ставим зависимости (первый раз — пара минут)…'
& $venvPy -m pip install --quiet --upgrade pip
& $venvPy -m pip install --quiet -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'не удалось поставить зависимости' }

$env:MF_DEMO_SNAPSHOT = '1'                                  # пустая база при первом запуске — демо-снапшот
if (-not $env:MF_STT) { $env:MF_STT = 'openai' }             # голос без видеокарты — через OpenAI (нужен ключ в .env)
$env:MF_STT_WARMUP = '0'
Write-Host ''
Write-Host "Готово. Откройте http://localhost:$Port  — демо-вход без паролей: /login → «Войти как…». Остановить — Ctrl+C." -ForegroundColor Green
Write-Host ''
& $venvPy -m uvicorn mf.main:app --host 127.0.0.1 --port $Port
