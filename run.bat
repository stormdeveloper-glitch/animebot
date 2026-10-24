@echo off
if not exist venv (
    echo Virtual environment creating...
    python -m venv venv
)
call venv\Scripts\activate
pip install -r requirements.txt
python main.py
pause
