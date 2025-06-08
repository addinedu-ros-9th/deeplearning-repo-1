# gui/threads/video_receive_thread.py
import socket
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap

class VideoReceiveThread(QThread):
    change_pixmap_signal = pyqtSignal(QPixmap)

    def __init__(self, parent=None, tcp_host='127.0.0.1', tcp_port=9997):
        super().__init__(parent)
        self._run_flag = True
        self.server_addr = (tcp_host, tcp_port)

    def run(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.connect(self.server_addr)
                print("[GUI] 이미지 매니저에 연결 성공.")
            except Exception as e:
                print(f"[GUI] 이미지 매니저 연결 실패: {e}")
                return

            while self._run_flag:
                try:
                    # 데이터 길이 수신
                    len_bytes = s.recv(4)
                    if not len_bytes: break
                    data_len = int.from_bytes(len_bytes, 'big')

                    # 실제 데이터 수신
                    data = b''
                    while len(data) < data_len:
                        packet = s.recv(data_len - len(data))
                        if not packet: break
                        data += packet
                    
                    if not self._run_flag: break

                    # 수신한 데이터(JPEG)를 QPixmap으로 변환하여 시그널 발생
                    pixmap = QPixmap()
                    pixmap.loadFromData(data, "JPG")
                    self.change_pixmap_signal.emit(pixmap)

                except Exception:
                    break
        print("[GUI] 비디오 수신 스레드 종료.")

    def stop(self):
        self._run_flag = False