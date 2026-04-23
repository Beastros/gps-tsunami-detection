@echo off
cd /d C:\Users\Mike\Desktop\repo
copy /Y "C:\Users\Mike\Desktop\Earthquake Feed Listener Engine\poll_log.json" poll_log.json >nul
copy /Y "C:\Users\Mike\Desktop\Earthquake Feed Listener Engine\running_log.json" running_log.json >nul
git add poll_log.json running_log.json
git commit -m "Auto-update logs %date% %time%"
git push
