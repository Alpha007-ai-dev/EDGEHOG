@echo off
cd /d C:\dev\edgehog\app\devnet
if not exist ..\..\output mkdir ..\..\output
echo EDGEHOG devnet LP teszt fut... (output\devnet.log) - ne zard be ezt az ablakot
echo ==== %DATE% %TIME% >> ..\..\output\devnet.log
where node >> ..\..\output\devnet.log 2>&1
node -v >> ..\..\output\devnet.log 2>&1
if not exist node_modules\@pm-amm call npm install --no-audit --no-fund >> ..\..\output\devnet.log 2>&1
node lp_devnet.cjs >> ..\..\output\devnet.log 2>&1
echo KESZ >> ..\..\output\devnet.log
