# gui/src/login_window.py

import json
import socket
import struct
from PyQt5.QtWidgets import QMainWindow, QMessageBox, QApplication
from PyQt5.uic import loadUi
import sys
import os

# 프로젝트 루트 경로를 sys.path에 추가 (상대 경로 ui 파일 로드를 위함)
# 이 스크립트의 위치를 기준으로 gui 폴더의 부모 디렉토리를 경로에 추가
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

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
        
        self.sock = None  # 소켓 객체 저장
        
        # 로그인 UI 파일 로드
        # 스크립트 실행 위치에 따라 경로 문제가 생길 수 있으므로 절대 경로 사용 권장
        ui_path = os.path.join(os.path.dirname(__file__), '../ui/login.ui')
        loadUi(ui_path, self)
        
        # 로그인 버튼 클릭 또는 Enter 키 입력시 handle_login 호출
        self.btn_login.clicked.connect(self.handle_login)
        self.input_id.returnPressed.connect(self.handle_login)
        self.input_pw.returnPressed.connect(self.handle_login)
        
        # 윈도우 표시 후 서버 연결 시도
        self.setup_connection()

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
            QMessageBox.critical(self, "연결 오류", "서버 연결에 실패했습니다.\n프로그램을 다시 시작해주세요.")
            self.sock = None

    def handle_login(self):
        """로그인 처리"""
        # 소켓이 없거나 끊어진 경우 재연결 시도
        if not self.sock:
            self.setup_connection()
            if not self.sock:
                return

        # 입력값 추출
        user_id = self.input_id.text()
        password = self.input_pw.text()

        # [수정 1] 서버가 기대하는 메시지 구조로 변경 (msg_type, payload)
        message = {
            "msg_type": "login_request",
            "payload": {
                "user_id": user_id,
                "password": password
            }
        }

        try:
            # [수정 2] 전송 로직 수정 (바이트 길이 기준, 개행문자 제거)
            body_bytes = json.dumps(message).encode('utf-8')
            header = len(body_bytes).to_bytes(4, 'big')
            packet = header + body_bytes # 개행문자(b'\n') 제거
            
            self.sock.sendall(packet)
            
            if DEBUG:
                print(f"{self.DEBUG_TAG['AUTH']} 인증 요청:")
                print(f"  - JSON 바디 길이: {len(body_bytes)} bytes")
                print(f"  - 헤더: {header.hex()}")
                print(f"  - 바디: {message}")
            
            # [수정 3] 안정적인 수신 로직으로 변경
            response_body = self.receive_packet()
            if response_body is None: return # 수신 실패 시 종료
            
            response_data = json.loads(response_body.decode('utf-8'))

            if DEBUG:
                print(f"{self.DEBUG_TAG['AUTH']} 응답 파싱 결과: {response_data}")

            # [수정 4] 응답 파싱 로직 수정 (payload 내부 확인)
            payload = response_data.get("payload", {})
            if payload.get("result") == "succeed":
                if DEBUG:
                    print(f"{self.DEBUG_TAG['AUTH']} 인증 성공")
                # MainWindow 인스턴스 생성 및 표시 로직은 main_app으로 이관하는 것이 좋음
                self.main_window = MainWindow() 
                self.main_window.show()
                self.close()
            else:
                if DEBUG:
                    print(f"{self.DEBUG_TAG['AUTH']} 인증 실패: {payload.get('reason')}")
                QMessageBox.warning(self, "로그인 실패", "아이디 또는 비밀번호가 올바르지 않습니다.")

        except Exception as e:
            if DEBUG:
                print(f"{self.DEBUG_TAG['ERR']} 처리 실패: {e}")
            QMessageBox.critical(self, "오류", f"로그인 처리 중 오류가 발생했습니다:\n{e}")
            self.close_connection() # 오류 발생 시 연결 종료

    def receive_packet(self):
        """ [추가됨] 안정적인 데이터 수신을 위한 헬퍼 메소드 """
        try:
            header = self.sock.recv(4)
            if not header:
                raise ConnectionAbortedError("서버로부터 헤더 수신 실패")
            
            body_len = struct.unpack('!I', header)[0]
            
            body = b''
            while len(body) < body_len:
                packet = self.sock.recv(body_len - len(body))
                if not packet:
                    raise ConnectionAbortedError("데이터 수신 중 연결 끊김")
                body += packet
            
            if DEBUG:
                print(f"{self.DEBUG_TAG['AUTH']} 수신된 응답:")
                print(f"  - 헤더 (4바이트): {header.hex()} (길이: {body_len})")
                print(f"  - 바디: {body.decode('utf-8')}")
                
            return body
        except Exception as e:
            print(f"{self.DEBUG_TAG['ERR']} 패킷 수신 오류: {e}")
            self.close_connection()
            return None

    def close_connection(self):
        """소켓 연결을 안전하게 종료합니다."""
        if self.sock:
            try:
                self.sock.close()
                if DEBUG:
                    print(f"{self.DEBUG_TAG['CONN']} 소켓 연결을 종료했습니다.")
            except Exception as e:
                if DEBUG:
                    print(f"{self.DEBUG_TAG['ERR']} 소켓 종료 중 오류: {e}")
            finally:
                self.sock = None

    def closeEvent(self, event):
        """윈도우 종료 시 소켓 정리"""
        self.close_connection()
        super().closeEvent(event)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = LoginWindow()
    window.show()
    sys.exit(app.exec_())