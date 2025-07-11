# gui/neighbot_gui.py

import sys
from PyQt5.QtWidgets import QApplication
from gui.src.login_window import LoginWindow


def main():
    app = QApplication(sys.argv)

    login_window = LoginWindow()
    login_window.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
