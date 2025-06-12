# gui/src/login_window.py

import json
import socket
from PyQt5.QtWidgets import QWidget, QMessageBox
from PyQt5.uic import loadUi
from gui.src.main_window import MainWindow

SERVER_IP = "192.168.0.23" # addinedu wifi ip address
SERVER_PORT = 9999


class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        loadUi('../ui/login.ui', self)

        self.btn_login.clicked.connect(self.handle_login)

    def handle_login(self):
        user_id = self.input_id.text()
        password = self.input_pw.text()

        message = {
            "user_id": user_id,
            "password": password
        }

        # socket open
        try:
            # neighbot_gui -> db_manager
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.connect((SERVER_IP, SERVER_PORT))
                body = json.dumps(message).encode('utf-8')
                packet = len(body).to_bytes(4, 'big') + body + b'\n'
                sock.sendall(packet)

                # db_manager -> neighbot_gui
                response = sock.recv(4096)
                response_data = json.loads(response[4:].decode())

                if response_data.get("result") == "succeed":
                    self.main_window = MainWindow()
                    self.main_window.show()
                    self.close()                
                else:
                    QMessageBox.warning(self, "Login Failed", "Invalid ID or password.")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Connection failed:\n{e}")
