# gui/src/login_window.py

from PyQt5.QtWidgets import QMainWindow, QMessageBox, QLineEdit
from PyQt5 import uic
import os

from backend.auth.auth_manager import AuthManager
from gui.src.main_window import MainWindow # 단일 MainWindow 클래스 임포트


class LoginWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # UI 파일 경로
        # login_window.py (현재 위치: gui/src) 에서 login.ui (실제 위치: gui/ui) 로 접근하기 위한 경로 설정
        ui_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui", "login.ui")
        uic.loadUi(ui_path, self)

        # 비밀번호 입력 필드 설정
        self.input_pw.setEchoMode(QLineEdit.Password)

        # DB 인증 관리자 설정
        self.auth_manager = AuthManager({
            "host": "34.47.96.177",
            "user": "root",
            "password": "qwer1234!@#$",
            "database": "neighbot_db"
        })

        # 로그인 버튼과 비밀번호 입력 필드의 Enter 키 이벤트를 핸들러에 연결
        self.btn_login.clicked.connect(self.handle_login)
        self.input_pw.returnPressed.connect(self.handle_login)

        self.main_window = None # 메인 윈도우 인스턴스를 저장할 변수


    def handle_login(self):
        user_id = self.input_id.text().strip()
        password = self.input_pw.text().strip()

        success = self.auth_manager.verify_user(user_id, password) # 인증 성공 여부만 반환
        if success:
            QMessageBox.information(self, "로그인 성공", f"✅ {user_id}님, 환영합니다!") # PyQt 메시지 (한국어)
            self.open_main() # 단일 메인 윈도우 열기
        else:
            QMessageBox.warning(self, "로그인 실패", "❌ 아이디 또는 비밀번호가 잘못되었습니다.") # PyQt 메시지 (한국어)

    def open_main(self):
        # 모든 로그인 성공 시 단일 MainWindow를 띄웁니다.
        self.main_window = MainWindow() # 단일 MainWindow 인스턴스 생성
        self.main_window.show() # 메인 윈도우 표시
        self.close() # 로그인 윈도우 닫기