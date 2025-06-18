# gui/src/login_window.py

import json
import socket
import struct
import threading
from PyQt5.QtWidgets import QMainWindow, QMessageBox
from PyQt5.QtCore import pyqtSignal, pyqtSlot
from PyQt5.uic import loadUi

# MainWindow는 더 이상 여기서 직접 생성하지 않으므로 import 라인 제거
# from gui.src.main_window import MainWindow 

DEBUG = True

class LoginWindow(QMainWindow):
    """
    로그인 UI와 서버 통신을 담당하는 클래스.
    성공 또는 실패 시 시그널을 발생시켜 MainApplication에 알립니다.
    """
    # 시그널 정의
    login_success = pyqtSignal(str)     # 성공 시 사용자 이름을 전달
    login_failed = pyqtSignal(str, str) # 실패 시 (제목, 내용)을 전달

    DEBUG_TAG = {'INIT': '[초기화]', 'CONN': '[연결]', 'AUTH': '[인증]', 'ERR': '[오류]'}

    def __init__(self, sock):
        super().__init__()
        self.sock = sock
        self.running = True

        if DEBUG:
            print(f"{self.DEBUG_TAG['INIT']} LoginWindow 초기화")

        # UI 파일 로드
        loadUi('./gui/ui/login.ui', self)
        
        # 위젯 및 시그널-슬롯 연결
        self.btn_login.clicked.connect(self.handle_login)
        self.login_failed.connect(self.show_message_box) # 실패 시그널과 메시지 박스 슬롯 연결

        # 서버 응답을 수신할 스레드 시작
        self.receiver_thread = threading.Thread(target=self.receive_response)
        self.receiver_thread.daemon = True
        self.receiver_thread.start()

    def handle_login(self):
        user_id = self.input_id.text()
        password = self.input_pw.text()

        if not user_id or not password:
            self.show_message_box("입력 오류", "아이디와 비밀번호를 모두 입력해주세요.")
            return

        # 서버가 요청을 식별할 수 있도록 'cmd' 필드 추가
        message = {
            "cmd": "login_request",
            "user_id": user_id,
            "password": password
        }

        try:
            body = json.dumps(message).encode('utf-8')
            # 4바이트 길이 헤더 + JSON 데이터
            packet = struct.pack('>I', len(body)) + body
            self.sock.sendall(packet)

            if DEBUG:
                print(f"{self.DEBUG_TAG['AUTH']} 인증 요청: {message}")

        except Exception as e:
            if DEBUG:
                print(f"{self.DEBUG_TAG['ERR']} 로그인 요청 실패: {e}")
            self.login_failed.emit("전송 오류", f"서버에 요청을 보낼 수 없습니다:\n{e}")

    def receive_response(self):
        """서버로부터 응답을 수신하고 결과에 따라 시그널을 방출하는 스레드"""
        while self.running:
            try:
                # 4바이트 헤더(길이) 수신
                header = self.sock.recv(4)
                if not header:
                    if DEBUG: print(f"{self.DEBUG_TAG['ERR']} 서버로부터 응답 헤더 없음, 연결 종료됨.")
                    break

                msg_len = struct.unpack('>I', header)[0]
                
                # 실제 데이터 수신
                response_bytes = self.sock.recv(msg_len)
                if not response_bytes:
                    if DEBUG: print(f"{self.DEBUG_TAG['ERR']} 응답 데이터 없음, 연결 종료됨.")
                    break
                    
                response_data = json.loads(response_bytes.decode('utf-8'))

                if DEBUG:
                    print(f"{self.DEBUG_TAG['AUTH']} 응답 파싱 결과: {response_data}")

                if response_data.get("result") == "succeed":
                    user_name = response_data.get("user_name", "Unknown")
                    # 성공 시그널 방출
                    self.login_success.emit(user_name)
                    break # 성공했으므로 수신 스레드 종료
                else:
                    reason = response_data.get('reason', '아이디 또는 비밀번호가 올바르지 않습니다.')
                    # 실패 시그널 방출 (직접 QMessageBox 호출하지 않음)
                    self.login_failed.emit("로그인 실패", reason)

            except (ConnectionResetError, ConnectionAbortedError):
                if DEBUG: print(f"{self.DEBUG_TAG['ERR']} 서버와의 연결이 끊어졌습니다.")
                self.login_failed.emit("연결 오류", "서버와의 연결이 끊어졌습니다.")
                break
            except Exception as e:
                # 스레드가 정상 종료되는 경우를 제외하고 오류 출력
                if self.running and DEBUG: print(f"{self.DEBUG_TAG['ERR']} 응답 수신 실패: {e}")
                self.login_failed.emit("수신 오류", f"서버 응답 처리 중 오류가 발생했습니다:\n{e}")
                break
    
    @pyqtSlot(str, str)
    def show_message_box(self, title, message):
        """메인 GUI 스레드에서 안전하게 QMessageBox를 표시하는 슬롯"""
        QMessageBox.warning(self, title, message)

    def closeEvent(self, event):
        """창이 닫힐 때 스레드를 종료하고 소켓을 닫습니다."""
        self.running = False
        if self.sock:
            try:
                # 블록된 recv()를 해제하기 위해 소켓을 닫음
                self.sock.shutdown(socket.SHUT_RDWR)
                self.sock.close()
            except OSError:
                # 이미 닫힌 소켓에 대한 예외는 무시
                pass
        # 스레드가 완전히 종료될 때까지 최대 1초 대기
        self.receiver_thread.join(timeout=1) 
        event.accept()