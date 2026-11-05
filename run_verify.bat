@echo off
set PYTHONIOENCODING=utf-8
cd /d C:\dev\edgehog
echo EDGEHOG felar-ellenorzes fut... (kimenet: output\premium.log)
python verify_premium.py %* > output\premium.log 2>&1
echo KESZ >> output\premium.log
