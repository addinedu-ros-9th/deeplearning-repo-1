# gui/src/login_window.py

import json
import socket
import traceback  # Add traceback module
from PyQt5.QtWidgets import QMainWindow, QMessageBox
from PyQt5.QtCore import QTimer, Qt
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
        self.welcome_msg = None  # 환영 메시지 팝업 인스턴스를 저장할 속성
        self.main_window = None  # 메인 윈도우 인스턴스를 저장할 속성
        self.setup_connection()
        
        loadUi('./gui/ui/login.ui', self)
        self.setWindowTitle("NeighBot 로그인")
        
        # 비밀번호 입력란 마스킹 처리
        from PyQt5.QtWidgets import QLineEdit
        self.input_pw.setEchoMode(QLineEdit.Password)
        
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
            "id": user_id,
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
            resp_len = int.from_bytes(response[:4], 'big')
            response_data = json.loads(response[4:4+resp_len].decode())
            if DEBUG:
                print(f"{self.DEBUG_TAG['AUTH']} 응답 파싱 결과: {response_data}")

            # 8) 결과 처리
            if response_data.get("result") == "succeed":
                if DEBUG:
                    print(f"{self.DEBUG_TAG['AUTH']} 인증 성공")
                
                # 환영 메시지 팝업 표시 (클래스 속성에 저장)
                self.welcome_msg = QMessageBox(self)
                self.welcome_msg.setWindowTitle("환영합니다")
                self.welcome_msg.setIcon(QMessageBox.Information)
                self.welcome_msg.setText(f"{response_data.get('name')}님 환영합니다.")
                # X 버튼과 OK 버튼을 추가하여 사용자가 직접 닫을 수 있게 함
                self.welcome_msg.setStandardButtons(QMessageBox.Ok)
                # 모달리스 설정 - 팝업이 다른 창 조작을 방해하지 않게 함
                self.welcome_msg.setWindowModality(Qt.NonModal)
                # 타이머에 의한 자동 닫기가 실패해도 사용자가 OK를 눌러 닫을 수 있음
                self.welcome_msg.buttonClicked.connect(self.close_welcome_and_open_main)
                self.welcome_msg.show()
                
                try:
                    # 서버 응답에서 사용자 ID 및 이름 가져오기
                    user_id = response_data.get("id")
                    user_name = response_data.get("name", "사용자")
                    
                    if DEBUG:
                        print(f"{self.DEBUG_TAG['AUTH']} 사용자 정보: ID={user_id}, NAME={user_name}")
                    
                    # 메인 윈도우 준비 (사용자 ID 및 이름 전달)
                    self.main_window = MainWindow(user_id=user_id, user_name=user_name)
                    
                    # 2초 후 환영 메시지 닫고 메인 윈도우 표시
                    QTimer.singleShot(2000, self.close_welcome_and_open_main)
                except Exception as e:
                    if DEBUG:
                        print(f"{self.DEBUG_TAG['ERR']} 메인 윈도우 생성 실패: {e}")
                        traceback.print_exc()
                    
                    # 메인 윈도우 생성에 실패하면 환영 메시지를 즉시 닫고 오류 메시지 표시
                    if self.welcome_msg:
                        self.welcome_msg.close()
                        self.welcome_msg = None
                    
                    QMessageBox.critical(self, "오류", f"메인 윈도우를 생성하는 중 오류가 발생했습니다:\n{e}")
            else:
                # 실패 사유에 따른 메시지 구분
                error_result = response_data.get("result", "unknown_error")
                if DEBUG:
                    print(f"{self.DEBUG_TAG['AUTH']} 인증 실패: {error_result}")
                
                if error_result == "id_error":
                    QMessageBox.warning(self, "로그인 실패", "존재하지 않는 아이디입니다.\n아이디를 확인해주세요.")
                elif error_result == "password_error":
                    QMessageBox.warning(self, "로그인 실패", "비밀번호가 일치하지 않습니다.\n비밀번호를 확인해주세요.")
                else:
                    QMessageBox.warning(self, "로그인 실패", f"알 수 없는 오류가 발생했습니다.\n다시 시도해주세요. (오류 코드: {error_result})")

        except Exception as e:
            if DEBUG:
                print(f"{self.DEBUG_TAG['ERR']} 처리 실패: {e}")
                traceback.print_exc()
            QMessageBox.critical(self, "오류", f"로그인 처리 중 오류가 발생했습니다:\n{e}")
            self.sock = None

    def close_welcome_and_open_main(self, button=None):
        """환영 메시지를 닫고 메인 윈도우를 표시
        
        Args:
            button: QMessageBox에서 클릭된 버튼 (있는 경우)
        """
        if DEBUG:
            print(f"{self.DEBUG_TAG['INIT']} 환영 메시지 닫기 및 메인 윈도우 표시")
        
        # 팝업이 이미 닫혀있지 않은지 확인
        if self.welcome_msg:
            self.welcome_msg.close()
            self.welcome_msg = None
        
        # 메인 윈도우가 준비되었는지 확인
        if self.main_window:
            # 메인 윈도우가 아직 표시되지 않았는지 확인
            if not self.main_window.isVisible():
                self.main_window.show()
                self.close()

    def closeEvent(self, event):
        """윈도우 종료 시 정리 작업"""
        # 환영 메시지가 아직 표시되어 있다면 닫기
        if self.welcome_msg:
            try:
                self.welcome_msg.close()
                self.welcome_msg = None
            except:
                pass
            
        # 소켓 연결 닫기
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        
        super().closeEvent(event)
