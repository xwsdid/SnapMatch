nohup uvicorn main:app --host 0.0.0.0 --port 8500 --workers 1 > output.log 2>&1 &
