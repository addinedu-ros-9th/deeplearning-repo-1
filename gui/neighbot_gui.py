# gui/neighbot_gui.py

import sys
import socket
from PyQt5.QtWidgets import QApplication, QMessageBox
from gui.src.login_window import LoginWindow
from gui.src.main_window import MainWindow

# 서버 연결 설정 (모든 창에서 공통으로 사용)
SERVER_IP = "127.0.0.1"
DB_SERVER_PORT = 9005

class MainApplication(QApplication):
    """
    애플리케이션의 전체 생명주기와 창 전환을 관리하는 메인 컨트롤러 클래스.
    """
    def __init__(self, sys_argv):
        super(MainApplication, self).__init__(sys_argv)
        self.main_window = None
        self.login_window = None
        
        # DB Manager와 통신할 소켓 생성
        db_socket = self.create_socket()
        
        if not db_socket:
            self.show_connection_error()
            # 소켓 연결 실패 시 프로그램 종료
            sys.exit(1)

        # 로그인 윈도우 생성 및 시그널-슬롯 연결
        self.login_window = LoginWindow(db_socket)
        self.login_window.login_success.connect(self.show_main_window)
        self.login_window.show()

    def create_socket(self):
        """서버와 연결된 소켓을 생성하고 반환합니다."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # 서버에 연결
            sock.connect((SERVER_IP, DB_SERVER_PORT))
            print(f"[GUI] DB 서버({SERVER_IP}:{DB_SERVER_PORT}) 연결 성공")
            return sock
        except Exception as e:
            print(f"[GUI] DB 서버 연결 실패: {e}")
            return None

    def show_main_window(self, user_name):
        """로그인 성공 시그널을 받으면 메인 윈도우를 표시하는 슬롯"""
        print(f"[GUI] 로그인 성공! {user_name}님 환영합니다. 메인 윈도우를 엽니다.")
        if self.login_window:
            self.login_window.close() # 기존 로그인 창 닫기
            
        # 새로운 메인 윈도우 생성 및 표시
        self.main_window = MainWindow() 
        self.main_window.show()

    def show_connection_error(self):
        """서버 연결 실패 시 에러 메시지 박스를 표시합니다."""
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setText("서버 연결 실패")
        msg_box.setInformativeText("DB Manager 서버에 연결할 수 없습니다.\nSystem Manager가 실행 중인지 확인하세요.")
        msg_box.setWindowTitle("연결 오류")
        msg_box.exec_()

def main():
    app = MainApplication(sys.argv)
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()