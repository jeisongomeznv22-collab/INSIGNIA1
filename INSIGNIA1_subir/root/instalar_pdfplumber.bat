@echo off
rem Instala pdfplumber (lectura del PDF de la peticion en SGDEA) sobre el
rem Python del sistema, sin correr todo build.bat de nuevo. requirements.txt
rem ya lo incluye para las proximas compilaciones -- este .bat es solo para
rem poder probar en modo desarrollo (run_dev.bat) sin esperar una
rem compilacion completa.
setlocal
cd /d "%~dp0"
python -m pip install "pdfplumber>=0.11" > instalar_pdfplumber.log 2>&1
echo.
echo Listo. Salida completa en instalar_pdfplumber.log
pause
