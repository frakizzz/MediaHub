import webview
import threading
import uvicorn
import time
from main import app  # Твій FastAPI додаток

def run_server():
    # Запуск сервера
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error")

if __name__ == '__main__':
    # Запуск сервера у фоні
    threading.Thread(target=run_server, daemon=True).start()
    time.sleep(1) # Чекаємо поки сервер підніметься

    # Створення вікна
    webview.create_window("MediaHub Pro", "http://127.0.0.1:8000", width=1200, height=800)
    webview.start()