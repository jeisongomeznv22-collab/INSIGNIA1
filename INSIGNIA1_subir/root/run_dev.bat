@echo off
rem Lanza Insignia directamente con el Python del sistema (sin empaquetar
rem con PyInstaller) -- mucho mas rapido para probar cambios mientras se
rem esta calibrando/probando la automatizacion SGDEA. Genera la misma
rem ventana nativa de Flet que produce Insignia.exe. La salida (incluyendo
rem cualquier traceback si algo falla al iniciar) queda en dev_run.log,
rem junto a este .bat, para poder revisarla despues sin necesitar una
rem consola interactiva.
setlocal
cd /d "%~dp0"
rem Borra el cache compilado (.pyc) del backend antes de correr -- evita
rem que Python siga usando una version vieja compilada de algun modulo
rem del backend despues de actualizarlo (ya paso varias veces).
if exist backend\__pycache__ rmdir /s /q backend\__pycache__
if exist __pycache__ rmdir /s /q __pycache__
python -u main.py > dev_run.log 2>&1
echo.
echo (Insignia se cerro. Salida completa en dev_run.log)
pause
