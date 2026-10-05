@echo off
setlocal
cd /d "%~dp0"

del /q build_status.txt >nul 2>nul

echo ============================================ > build_log.txt
echo  Compilando Insignia (modo automatico) >> build_log.txt
echo ============================================ >> build_log.txt

where python >nul 2>nul
if errorlevel 1 (
    echo NO_PYTHON: no se encontro Python en el sistema (instalar desde python.org, marcando "Add Python to PATH"). >> build_log.txt
    echo NO_PYTHON > build_status.txt
    exit /b 1
)

echo. >> build_log.txt
echo [1/3] Instalando dependencias (sobre el Python del sistema)... >> build_log.txt
python -m pip install --upgrade pip >> build_log.txt 2>&1
if errorlevel 1 (
    echo ERROR_PIP_UPGRADE >> build_log.txt
    echo ERROR_PIP_UPGRADE > build_status.txt
    exit /b 1
)

python -m pip install -r requirements.txt >> build_log.txt 2>&1
if errorlevel 1 (
    echo ERROR_REQUIREMENTS >> build_log.txt
    echo ERROR_REQUIREMENTS > build_status.txt
    exit /b 1
)

python -m pip install pyinstaller >> build_log.txt 2>&1
if errorlevel 1 (
    echo ERROR_PYINSTALLER_INSTALL >> build_log.txt
    echo ERROR_PYINSTALLER_INSTALL > build_status.txt
    exit /b 1
)

echo. >> build_log.txt
echo [2/3] Compilando ejecutable (esto puede tardar varios minutos)... >> build_log.txt
python -m flet.cli pack main.py -y ^
    --name "Insignia" ^
    --icon "assets\icon.ico" ^
    --add-data "assets;assets" ^
    --product-name "Insignia - Centro de Gestion Ejecutiva" ^
    --company-name "Ministerio de Educacion Nacional" ^
    --file-description "Insignia - Dashboard, Portal de Acuses 4-72 y Memorandos SGDEA" >> build_log.txt 2>&1

if errorlevel 1 (
    echo ERROR_FLET_PACK >> build_log.txt
    echo ERROR_FLET_PACK > build_status.txt
    exit /b 1
)

if not exist "dist\Insignia.exe" (
    echo ERROR_NO_EXE_OUTPUT >> build_log.txt
    echo ERROR_NO_EXE_OUTPUT > build_status.txt
    exit /b 1
)

echo. >> build_log.txt
echo [3/3] Listo. dist\Insignia.exe generado correctamente. >> build_log.txt
echo OK > build_status.txt
