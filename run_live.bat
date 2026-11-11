@echo off
set PYTHONIOENCODING=utf-8
cd /d C:\dev\edgehog
if not exist output mkdir output
echo EDGEHOG elo konyv-ellenorzes fut... (output\live.log)
python live_book.py >> output\live.log 2>&1
echo KESZ >> output\live.log
