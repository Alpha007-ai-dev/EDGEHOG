@echo off
set PYTHONIOENCODING=utf-8
cd /d C:\dev\edgehog
echo EDGEHOG koltsegmeres fut... (output\cost.log) - ne zard be ezt az ablakot
python cost_sample.py >> output\cost.log 2>&1
echo KESZ >> output\cost.log
