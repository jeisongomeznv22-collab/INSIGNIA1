@echo off
rem Corre la prueba manual supervisada del cliente del portal ANTIGUO
rem (legacy_portal_client.py) contra un ID real, con el navegador visible
rem para poder ver cada paso. Pide usuario/clave por consola (la clave no
rem se muestra en pantalla). No toca Insignia ni main.py.
setlocal
cd /d "%~dp0"
rem Borra el cache compilado (.pyc) del backend antes de correr -- si no,
rem Python a veces sigue usando una version vieja compilada de
rem legacy_portal_client.py aunque el .py ya se haya actualizado (mismo
rem problema que ya vimos con Insignia y __pycache__).
if exist backend\__pycache__ rmdir /s /q backend\__pycache__
python -u backend\test_legacy_portal_manual.py
pause
