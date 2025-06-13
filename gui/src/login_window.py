# gui/src/login_window.py

import json
import socket
from PyQt5.QtWidgets import QMainWindow, QMessageBox
from PyQt5.uic import loadUi
from gui.src.main_window import MainWindow

# 디버그 모드: True이면 터미널에 로그를 출력합니다
DEBUG = True

# 서버 연결 설정
# SERVER_IP = "192.168.0.23" # addinedu wifi ip address
SERVER_IP = "127.0.0.1"    # local host
SERVER_PORT = 9005

class LoginWindow(QMainWindow):
    # 디버그 태그 정의
    DEBUG_TAG = {
        'INIT': '[초기화]',
        'CONN': '[연결]',
        'AUTH': '[인증]',
        'ERR': '[오류]'
    }

    def __init__(self):
        super().__init__()
        if DEBUG:
            print(f"{self.DEBUG_TAG['INIT']} LoginWindow 초기화")
        # 로그인 UI 파일 로드
        loadUi('./gui/ui/login.ui', self)
        # 로그인 버튼 클릭 시 handle_login 호출
        self.btn_login.clicked.connect(self.handle_login)

    def handle_login(self):
        # 입력값 추출
        user_id = self.input_id.text()
        password = self.input_pw.text()

        message = {
            "user_id": user_id,
            "password": password
        }

        try:
            if DEBUG:
                print(f"{self.DEBUG_TAG['CONN']} 서버 연결 시도: {SERVER_IP}:{SERVER_PORT}")

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.connect((SERVER_IP, SERVER_PORT))
                if DEBUG:
                    print(f"{self.DEBUG_TAG['CONN']} 서버 연결 성공")

                body = json.dumps(message).encode('utf-8')
                packet = len(body).to_bytes(4, 'big') + body + b'\n'
                sock.sendall(packet)
                if DEBUG:
                    print(f"{self.DEBUG_TAG['AUTH']} 인증 요청: {message}")

                response = sock.recv(4096)
                if DEBUG:
                    print(f"{self.DEBUG_TAG['AUTH']} 수신된 응답: {response}")

                response_data = json.loads(response[4:].decode())
                if DEBUG:
                    print(f"{self.DEBUG_TAG['AUTH']} 응답 파싱 결과: {response_data}")

                if response_data.get("result") == "succeed":
                    if DEBUG:
                        print(f"{self.DEBUG_TAG['AUTH']} 인증 성공")
                    self.main_window = MainWindow()
                    self.main_window.show()
                    self.close()
                else:
                    if DEBUG:
                        print(f"{self.DEBUG_TAG['AUTH']} 인증 실패")
                    QMessageBox.warning(self, "로그인 실패", "아이디 또는 비밀번호가 올바르지 않습니다.")

        except Exception as e:
            if DEBUG:
                print(f"{self.DEBUG_TAG['ERR']} 처리 실패: {e}")
            QMessageBox.critical(self, "오류", f"서버 연결에 실패했습니다:\n{e}")
