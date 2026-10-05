@echo off
setlocal
cd /d "%~dp0"

echo CHECKPOINT_0_START > build_diag3_log.txt
echo Fecha/hora: %date% %time% >> build_diag3_log.txt

echo CHECKPOINT_1_antes_de_flet_pack >> build_diag3_log.txt
python -m flet.cli pack main.py -y ^
    --name "Insignia" ^
    --icon "assets\icon.ico" ^
    --add-data "assets;assets" ^
    --product-name "Insignia - Centro de Gestion Ejecutiva" ^
    --company-name "Ministerio de Educacion Nacional" ^
    --file-description "Insignia - Dashboard, Portal de Acuses 4-72 y Memorandos SGDEA" >> build_diag3_log.txt 2>&1
echo CHECKPOINT_2_errorlevel_flet_pack=%errorlevel% >> build_diag3_log.txt

echo CHECKPOINT_3_FIN_OK >> build_diag3_log.txt
echo Si ves esta linea, el diagnostico 3 termino sin que nada lo matara. >> build_diag3_log.txt
