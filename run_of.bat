@echo off
set PYTHONIOENCODING=utf-8
cd /d C:\dev\edgehog
echo EDGEHOG order-flow teszt fut... (output\of.log)
python of_test.py >> output\of.log 2>&1
echo KESZ >> output\of.log
