@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo  Compilando Insignia
echo ============================================

where python >nul 2>nul
if errorlevel 1 (
    echo No se encontro Python en el sistema. Instalalo desde https://www.python.org/downloads/
    echo y marca la casilla "Add Python to PATH" durante la instalacion.
    pause
    exit /b 1
)

rem NOTA: ya no se crea un entorno virtual (venv). En varios intentos la
rem creacion del venv fallaba al copiar "venvlauncher.exe" -> "python.exe"
rem (probablemente bloqueado por el antivirus del equipo). Para evitar ese
rem problema por completo, instalamos las dependencias directamente sobre
rem el Python del sistema. Como este equipo es de un solo usuario y el
rem unico proposito de este Python es compilar este ejecutable, no hay
rem riesgo de conflicto de paquetes.

echo.
echo [1/3] Instalando dependencias (sobre el Python del sistema)...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo.
    echo ============================================
    echo  ERROR: no se pudo actualizar pip. Revisa el
    echo  detalle mas arriba en esta misma ventana.
    echo ============================================
    pause
    exit /b 1
)

python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ============================================
    echo  ERROR: fallo la instalacion de dependencias.
    echo  Revisa el detalle mas arriba en esta misma
    echo  ventana.
    echo ============================================
    pause
    exit /b 1
)

python -m pip install pyinstaller
if errorlevel 1 (
    echo.
    echo ============================================
    echo  ERROR: fallo la instalacion de pyinstaller.
    echo  Revisa el detalle mas arriba en esta misma
    echo  ventana.
    echo ============================================
    pause
    exit /b 1
)

echo.
echo [2/3] Compilando ejecutable (esto puede tardar varios minutos)...
rem -y = responde automaticamente "si" si build/dist ya existen (evita que
rem      el proceso se quede esperando una respuesta por teclado).
python -m flet.cli pack main.py -y ^
    --name "Insignia" ^
    --icon "assets\icon.ico" ^
    --add-data "assets;assets" ^
    --product-name "Insignia - Centro de Gestion Ejecutiva" ^
    --company-name "Ministerio de Educacion Nacional" ^
    --file-description "Insignia - Dashboard, Portal de Acuses 4-72 y Memorandos SGDEA"

if errorlevel 1 (
    echo.
    echo ============================================
    echo  ERROR: la compilacion fallo. Revisa el
    echo  detalle mas arriba en esta misma ventana.
    echo ============================================
    pause
    exit /b 1
)

if not exist "dist\Insignia.exe" (
    echo.
    echo ============================================
    echo  ERROR: el proceso termino pero no se encontro
    echo  el archivo dist\Insignia.exe
    echo ============================================
    pause
    exit /b 1
)

echo.
echo [3/3] Listo.
echo El ejecutable quedo en la carpeta "dist\Insignia.exe"
echo Puedes copiar ese unico archivo a cualquier otro PC con Windows y ejecutarlo con doble clic.
pause
