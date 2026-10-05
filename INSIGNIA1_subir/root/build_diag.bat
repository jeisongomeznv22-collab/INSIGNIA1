@echo off
setlocal
cd /d "%~dp0"

echo CHECKPOINT_0_START > build_diag_log.txt
echo Fecha/hora: %date% %time% >> build_diag_log.txt

echo CHECKPOINT_1_antes_de_where >> build_diag_log.txt
where python >> build_diag_log.txt 2>&1
echo CHECKPOINT_2_errorlevel_where=%errorlevel% >> build_diag_log.txt

echo CHECKPOINT_3_antes_de_version >> build_diag_log.txt
python --version >> build_diag_log.txt 2>&1
echo CHECKPOINT_4_errorlevel_version=%errorlevel% >> build_diag_log.txt

echo CHECKPOINT_5_antes_de_pip_version >> build_diag_log.txt
python -m pip --version >> build_diag_log.txt 2>&1
echo CHECKPOINT_6_errorlevel_pip=%errorlevel% >> build_diag_log.txt

echo CHECKPOINT_7_FIN_OK >> build_diag_log.txt
echo Si ves esta linea, el diagnostico termino sin que nada lo matara. >> build_diag_log.txt
