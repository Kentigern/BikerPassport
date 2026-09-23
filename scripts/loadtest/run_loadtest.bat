@echo off
rem Bike + Brew load test - simulates volunteers logging passports on staging.
rem Read README.txt first: the test accounts must be created on the server beforehand.
cd /d "%~dp0"

python --version >nul 2>&1 || (echo Python is not installed or not on PATH - see README.txt. & pause & exit /b 1)
python -c "import requests" >nul 2>&1 || python -m pip install --user requests

set "SITE=https://staging.bikeandbrew.org"
set "USERS=40"
set "MINUTES=10"
set /p "SITE=Site to test [%SITE%]: "
set /p "USERS=Number of volunteers [%USERS%]: "
set /p "MINUTES=Minutes to run [%MINUTES%]: "
set /p "PASSWORD=Password given to loadtest_fixtures --create: "

echo.
python loadtest.py "%SITE%" --users %USERS% --minutes %MINUTES% --password "%PASSWORD%" --output results_latest.txt
echo.
pause
