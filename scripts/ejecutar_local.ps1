# Corre el monitor en esta PC y sube los datos a GitHub (modo híbrido).
#
# Para qué sirve: si algún portal estatal bloquea las IP de GitHub Actions, el mismo
# código corre desde tu conexión argentina. Programalo con el Programador de tareas de
# Windows (por ejemplo a las 8:00 y 18:00) apuntando a este archivo:
#   powershell -ExecutionPolicy Bypass -File "C:\ruta\monitor-juridico\scripts\ejecutar_local.ps1"
#
# Requisitos: Python 3.10+, Git configurado con acceso al repositorio y un archivo .env
# con GEMINI_API_KEY en la carpeta del proyecto.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

git pull --rebase --autostash
python main.py --sin-exportar
if ($LASTEXITCODE -gt 1) { throw "El monitor terminó con error ($LASTEXITCODE)." }

git add data
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m "Datos: corrida local $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    git push
    Write-Host "Datos subidos. GitHub vuelve a publicar el sitio en la próxima corrida programada o al dispararlo a mano."
} else {
    Write-Host "Sin novedades nuevas."
}
