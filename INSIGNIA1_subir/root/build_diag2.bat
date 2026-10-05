@echo off
setlocal
cd /d "%~dp0"

echo CHECKPOINT_0_START > build_diag2_log.txt
echo Fecha/hora: %date% %time% >> build_diag2_log.txt

echo CHECKPOINT_1_antes_de_pip_upgrade >> build_diag2_log.txt
python -m pip install --upgrade pip >> build_diag2_log.txt 2>&1
echo CHECKPOINT_2_errorlevel_pip_upgrade=%errorlevel% >> build_diag2_log.txt

echo CHECKPOINT_3_antes_de_requirements >> build_diag2_log.txt
python -m pip install -r requirements.txt >> build_diag2_log.txt 2>&1
echo CHECKPOINT_4_errorlevel_requirements=%errorlevel% >> build_diag2_log.txt

echo CHECKPOINT_5_antes_de_pyinstaller_install >> build_diag2_log.txt
python -m pip install pyinstaller >> build_diag2_log.txt 2>&1
echo CHECKPOINT_6_errorlevel_pyinstaller_install=%errorlevel% >> build_diag2_log.txt

echo CHECKPOINT_7_FIN_OK >> build_diag2_log.txt
echo Si ves esta linea, el diagnostico 2 termino sin que nada lo matara. >> build_diag2_log.txt
