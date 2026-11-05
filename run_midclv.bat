@echo off
set PYTHONIOENCODING=utf-8
cd /d C:\dev\edgehog
echo EDGEHOG kozep-CLV fut... (kimenet: output\midclv.log)
python midclv.py %* > output\midclv.log 2>&1
echo KESZ >> output\midclv.log
