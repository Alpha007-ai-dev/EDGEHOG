@echo off
set PYTHONIOENCODING=utf-8
cd /d C:\dev\edgehog
python venue_probe.py > output\venue.log 2>&1
echo KESZ >> output\venue.log
