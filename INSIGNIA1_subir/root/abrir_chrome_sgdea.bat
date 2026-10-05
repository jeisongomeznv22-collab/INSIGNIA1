@echo off
setlocal

rem Este script abre una ventana de Chrome APARTE (con su propio perfil,
rem no tu Chrome normal) en modo de "depuracion remota". Insignia se
rem conecta a esa ventana para leer SGDEA -- por eso el boton
rem "Sincronizar con SGDEA" / "Aprobar y enviar" no hace nada si abres
rem Chrome de la forma normal (haciendo doble clic en su icono).
rem
rem No necesitas cerrar tu Chrome normal: como esta ventana usa un
rem perfil distinto, las dos pueden estar abiertas al mismo tiempo.

set "CHROME_PATH=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_PATH%" set "CHROME_PATH=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_PATH%" set "CHROME_PATH=%LocalAppData%\Google\Chrome\Application\chrome.exe"

if not exist "%CHROME_PATH%" (
    echo No se encontro Google Chrome instalado en las rutas usuales.
    echo Instala Chrome o avisale a soporte.
    pause
    exit /b 1
)

echo ============================================
echo  Abriendo Chrome para Insignia / SGDEA
echo ============================================
echo.
echo Se va a abrir una ventana NUEVA de Chrome (perfil aparte).
echo.
echo   1. En esa ventana, inicia sesion en SGDEA como siempre
echo      (la primera vez toca iniciar sesion; despues Chrome
echo      recuerda la sesion en ese perfil).
echo   2. Deja esa ventana de Chrome ABIERTA Y MAXIMIZADA (no la achiques
echo      ni la muevas) -- Insignia ubica el bloque "Gestionar" del
echo      dashboard de SGDEA por una posicion fija en pantalla, asi que
echo      solo funciona si la ventana queda del mismo tamaño cada vez.
echo   3. Vuelve a Insignia y usa "Sincronizar con SGDEA" (Dashboard)
echo      o "Aprobar y enviar" (Memorandos).
echo.

start "" "%CHROME_PATH%" --remote-debugging-port=9222 --user-data-dir="%LocalAppData%\InsigniaChromeDebug" --start-maximized

echo Listo, la ventana de Chrome deberia estar abriendose.
pause
