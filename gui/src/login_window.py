# gui/src/login_window.py
import os
import socket
from PyQt5.QtWidgets import QMainWindow, QMessageBox
from PyQt5.QtCore import QObject, QThread, pyqtSignal
from PyQt5 import uic
from .main_window import MainWindow # 같은 src 폴더 내의 main_window 임포트
from shared.protocols import create_request, parse_message # shared 폴더의 protocols 임포트

# 네트워크 통신 워커 (이전과 동일)
class LoginWorker(QObject):
    finished = pyqtSignal(dict)

    def __init__(self, user_id, password, server_addr=('127.0.0.1', 9999)):
        super().__init__()
        self.user_id, self.password = user_id, password
        self.server_addr = server_addr

    def run(self):
        try:
            req_bytes = create_request("login", {"id": self.user_id, "password": self.password})
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(self.server_addr)
                s.sendall(req_bytes)
                res_bytes = s.recv(1024)
                response = parse_message(res_bytes)
                self.finished.emit(response)
        except Exception as e:
            self.finished.emit({"status": "error", "message": f"서버 통신 오류: {e}"})

# LoginWindow 클래스 (이전과 동일)
class LoginWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # ui 파일 경로는 현재 파일 위치(__file__) 기준으로 재계산
        ui_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui", "login.ui")
        uic.loadUi(ui_path, self)
        
        self.btn_login.clicked.connect(self.attempt_login)
        self.input_pw.returnPressed.connect(self.attempt_login)
        self.main_window = None

    def attempt_login(self):
        # ... (이전 QThread 관련 코드와 완벽히 동일)
        self.btn_login.setEnabled(False)
        self.btn_login.setText("로그인 중...")

        self.thread = QThread()
        self.worker = LoginWorker(self.input_id.text().strip(), self.input_pw.text().strip())
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_login_finished)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def on_login_finished(self, response):
        # ... (이전 코드와 완벽히 동일)
        self.btn_login.setEnabled(True)
        self.btn_login.setText("로그인")
        status, message = response.get("status"), response.get("message")

        if status == "success":
            QMessageBox.information(self, "로그인 성공", message)
            self.main_window = MainWindow()
            self.main_window.show()
            self.close()
        elif status == "failed":
            QMessageBox.warning(self, "로그인 실패", message)
        else:
            QMessageBox.critical(self, "오류", message)