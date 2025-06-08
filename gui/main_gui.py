# gui/main_gui.py
from .src.login_window import LoginWindow

class MainApplication:
    def __init__(self, app):
        self.app = app
        self.login_window = LoginWindow()
        self.login_window.show()