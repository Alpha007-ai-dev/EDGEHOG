@echo off
set PYTHONIOENCODING=utf-8
cd /d C:\dev\edgehog
echo EDGEHOG ejszakai flow-meres fut... (kimenet: output\flow.log) - ne zard be ezt az ablakot
python flow.py %* >> output\flow.log 2>&1
echo KESZ >> output\flow.log
