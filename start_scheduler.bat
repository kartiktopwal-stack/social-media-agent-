@echo off
echo Starting Celery Worker...
start "empire_worker" cmd /k "call venv\Scripts\activate && celery -A celery_app worker --loglevel=info --pool=solo"

timeout /t 3

echo Starting Celery Beat...
start "empire_beat" cmd /k "call venv\Scripts\activate && celery -A celery_app beat --loglevel=info"

echo.
echo Both processes started in separate windows.
echo Worker window: empire_worker
echo Scheduler window: empire_beat
echo Pipeline will run daily at 9:00 AM IST.
echo Close both windows to stop.
