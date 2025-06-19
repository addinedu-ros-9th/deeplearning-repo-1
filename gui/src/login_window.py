# gui/src/login_window.py

import json
import socket
from PyQt5.QtWidgets import QMainWindow, QMessageBox
from PyQt5.uic import loadUi
from gui.src.main_window import MainWindow

# 디버그 모드: True이면 터미널에 로그를 출력합니다
DEBUG = True

# 서버 연결 설정
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
        
        self.sock = None
        self.setup_connection()
        
        loadUi('./gui/ui/login.ui', self)
        self.btn_login.clicked.connect(self.handle_login)
        self.input_id.returnPressed.connect(self.handle_login)
        self.input_pw.returnPressed.connect(self.handle_login)

    def setup_connection(self):
        """서버 연결 설정"""
        try:
            if DEBUG:
                print(f"{self.DEBUG_TAG['CONN']} 서버 연결 시도: {SERVER_IP}:{SERVER_PORT}")
            
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((SERVER_IP, SERVER_PORT))
            
            if DEBUG:
                print(f"{self.DEBUG_TAG['CONN']} 서버 연결 성공")
                
        except Exception as e:
            if DEBUG:
                print(f"{self.DEBUG_TAG['ERR']} 서버 연결 실패: {e}")
            QMessageBox.critical(self, "연결 오류", "서버 연결에 실패했습니다.\n다시 시도해주세요.")
            self.sock = None

    def handle_login(self):
        """로그인 처리"""
        if not self.sock:
            self.setup_connection()
            if not self.sock:
                return

        user_id = self.input_id.text()
        password = self.input_pw.text()
        message = {
            "user_id": user_id,
            "password": password
        }

        try:
            # 1) body에 개행문자 포함
            body = json.dumps(message).encode('utf-8') + b'\n'
            # 2) 헤더: body 전체 길이 계산
            header = len(body).to_bytes(4, 'big')
            # 3) 패킷 조립
            packet = header + body

            # 4) 디버그 출력
            if DEBUG:
                print(f"{self.DEBUG_TAG['AUTH']} 인증 요청:")
                print(f"  - 헤더 (4바이트 hex): {header.hex()}  (길이: {int.from_bytes(header, 'big')} 바이트)")
                print(f"  - 바디 (raw): {body!r}")
                print(f"  - 전체 패킷: {packet!r}")

            # 5) 전송
            self.sock.sendall(packet)

            # 6) 응답 수신
            response = self.sock.recv(4096)
            if DEBUG:
                resp_len = int.from_bytes(response[:4], 'big')
                print(f"{self.DEBUG_TAG['AUTH']} 수신된 응답:")
                print(f"  - 헤더 (4바이트 hex): {response[:4].hex()}  (길이: {resp_len} 바이트)")
                print(f"  - 바디: {response[4:4+resp_len].decode().strip()}")
                print(f"  - 전체 패킷: {response!r}")

            # 7) 응답 파싱
            response_data = json.loads(response[4:4+resp_len].decode())
            if DEBUG:
                print(f"{self.DEBUG_TAG['AUTH']} 응답 파싱 결과: {response_data}")

            # 8) 결과 처리
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
            QMessageBox.critical(self, "오류", f"로그인 처리 중 오류가 발생했습니다:\n{e}")
            self.sock = None

    def closeEvent(self, event):
        """윈도우 종료 시 소켓 정리"""
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        super().closeEvent(event)
