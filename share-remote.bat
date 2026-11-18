@echo off
REM Double-click this to share CacheCollapse with teammates over the internet.
REM Keep this window OPEN while they use it. Close it to stop sharing.
REM It prints a public https://...trycloudflare.com link - send that to your team.
echo Starting public tunnel to CacheCollapse (http://localhost:8090)...
echo Keep this window open. Your public link will appear below.
echo.
"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://localhost:8090
pause
