# main.py

import sys
from PyQt5.QtWidgets import QApplication
from gui.src.login_window import LoginWindow # gui/src/login_window 모듈 임포트

if __name__ == '__main__':
    app = QApplication(sys.argv)
    login_window = LoginWindow()
    login_window.show()
    sys.exit(app.exec_())