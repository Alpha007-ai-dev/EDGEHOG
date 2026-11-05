@echo off
set PYTHONIOENCODING=utf-8
cd /d C:\dev\edgehog
echo EDGEHOG probe fut... (a kimenet: output\run.log, a jelentes: output\report.txt)
python probe.py %* > output\run.log 2>&1
echo KESZ >> output\run.log
