# gui/tabs/monitoring_tab.py
import os, socket, select, time
from datetime import datetime
from PyQt5.QtWidgets import QWidget, QMessageBox, QTableWidgetItem
from PyQt5.QtGui import QPixmap, QPainter, QFont, QColor, QPen, QImage
from PyQt5.QtCore import pyqtSlot, Qt, QObject, QThread, pyqtSignal, QTimer
from PyQt5 import uic
from shared.protocols import create_request, parse_message

class VideoReceiverThread(QObject):
    """서버의 영상 중계 포트로부터 영상 데이터만 수신하는 역할"""
    new_pixmap_signal = pyqtSignal(QPixmap)
    def __init__(self, server_addr):
        super().__init__()
        self.server_addr, self._run_flag = server_addr, True
    @pyqtSlot()
    def run(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try: s.connect(self.server_addr)
            except Exception as e:
                print(f"[GUI-영상] 연결 실패: {e}"); return
            print(f"[GUI-영상] {self.server_addr}에 연결 성공.")
            while self._run_flag:
                try:
                    len_bytes = s.recv(4)
                    if not len_bytes: break
                    data_len = int.from_bytes(len_bytes, 'big')
                    data = b''
                    while len(data) < data_len:
                        packet = s.recv(data_len - len(data))
                        if not packet: break
                        data += packet
                    if not self._run_flag: break
                    pixmap = QPixmap(); pixmap.loadFromData(data, "JPG")
                    self.new_pixmap_signal.emit(pixmap)
                except Exception: break
        print("[GUI-영상] 스레드 종료.")
    def stop(self): self._run_flag = False

class ControlClientThread(QObject):
    """서버에 명령을 보내고, 비동기 이벤트를 수신하는 역할"""
    new_event_signal, command_response_signal = pyqtSignal(dict), pyqtSignal(dict)
    def __init__(self, server_addr):
        super().__init__()
        self.server_addr, self._run_flag, self.socket = server_addr, True, None
    @pyqtSlot()
    def run(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try: self.socket.connect(self.server_addr)
        except Exception as e:
            print(f"[GUI-제어] 연결 실패: {e}"); return
        print(f"[GUI-제어] {self.server_addr}에 연결 성공.")
        while self._run_flag:
            try:
                ready, _, _ = select.select([self.socket], [], [], 0.1)
                if ready:
                    res_bytes = self.socket.recv(1024)
                    if not res_bytes: break
                    response = parse_message(res_bytes)
                    if response.get("status") == "event": self.new_event_signal.emit(response)
                    else: self.command_response_signal.emit(response)
            except Exception: break
        print("[GUI-제어] 스레드 종료.")
    @pyqtSlot(str, dict)
    def send_command(self, req_type, payload):
        if self.socket and self._run_flag:
            try: self.socket.sendall(create_request(req_type, payload))
            except Exception as e: print(f"[GUI-제어] 명령 전송 실패: {e}")
    def stop(self):
        self._run_flag = False
        if self.socket: self.socket.close()

class MonitoringTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        ui_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui", "monitoring_tab.ui")
        uic.loadUi(ui_path, self)
        self.is_connected = False
        self.control_thread, self.video_thread = None, None
        self.control_worker, self.video_worker = None, None
        self.capture_dir, self.current_robot_location = "captured_image", "홈"
        self._setup_ui_connections()

    def _setup_ui_connections(self):
        self.btn_activate_robot.clicked.connect(self.toggle_connection)
        self.btn_move_to_A.clicked.connect(lambda: self.send_command_to_server("move_robot", {"destination": "A구역"}))
        self.btn_move_to_B.clicked.connect(lambda: self.send_command_to_server("move_robot", {"destination": "B구역"}))
        self.btn_return_home.clicked.connect(lambda: self.send_command_to_server("move_robot", {"destination": "홈"}))
        self.btn_human_decision.clicked.connect(lambda: self.send_command_to_server("human_decision", {"command": "EMERGENCY_STOP"}))
        self.btn_capture_image.clicked.connect(self.handle_capture_image)
        QTimer.singleShot(0, self.draw_simplified_map)

    def toggle_connection(self):
        if not self.is_connected:
            self.btn_activate_robot.setText("연결 끊기"); self.update_robot_status("Connecting...", "서버 연결 중...")
            self.control_thread, self.control_worker = QThread(), ControlClientThread(('127.0.0.1', 9999))
            self.control_worker.moveToThread(self.control_thread)
            self.control_thread.started.connect(self.control_worker.run); self.control_worker.new_event_signal.connect(self.handle_server_event)
            self.control_worker.command_response_signal.connect(self.handle_command_response); self.control_thread.start()
            self.video_thread, self.video_worker = QThread(), VideoReceiverThread(('127.0.0.1', 9997))
            self.video_worker.moveToThread(self.video_thread)
            self.video_thread.started.connect(self.video_worker.run); self.video_worker.new_pixmap_signal.connect(self.update_image_slot)
            self.video_thread.start()
            QTimer.singleShot(500, lambda: self.send_command_to_server("video_control", {"action": "start"}))
            self.is_connected = True
        else:
            self.clean_up()

    def send_command_to_server(self, req_type, payload):
        if self.is_connected and self.control_worker: self.control_worker.send_command(req_type, payload)
        else: QMessageBox.warning(self, "오류", "먼저 '원격 연결 시작' 버튼을 눌러주세요.")

    @pyqtSlot(QPixmap)
    def update_image_slot(self, pixmap):
        self.live_feed_label.setPixmap(pixmap.scaled(self.live_feed_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    @pyqtSlot(dict)
    def handle_server_event(self, event):
        message, location = event.get("message", "알 수 없는 이벤트"), event.get("payload", {}).get("location", "N/A")
        QMessageBox.information(self, "서버 알림", message); self.add_detection_event("이벤트", time.strftime("%H:%M:%S"), location, message)
        self.update_robot_location_on_map(location)

    @pyqtSlot(dict)
    def handle_command_response(self, response):
        message = response.get("message", "내용 없음")
        status_text = "Connected" if response.get("status") == "success" else "Command Failed"
        self.update_robot_status(status_text, message)

    def clean_up(self):
        if not self.is_connected: return
        print("모니터링 탭 리소스 정리 시작...")

        # 1. 사용자에게 즉각적인 피드백을 주기 위해 UI를 먼저 업데이트합니다.
        self.live_feed_label.setText("실시간 영상 대기 중...")
        self.live_feed_label.repaint() # UI 즉시 갱신

        # 2. 서버에 영상 중단 요청을 보냅니다.
        self.send_command_to_server("video_control", {"action": "stop"})
        time.sleep(0.1) # 서버가 명령을 처리할 시간을 줍니다.

        # 3. 스레드를 안전하게 종료합니다.
        if self.video_worker: self.video_worker.stop()
        if self.video_thread:
            self.video_thread.quit()
            self.video_thread.wait(1000) # 최대 1초만 기다립니다.

        if self.control_worker: self.control_worker.stop()
        if self.control_thread:
            self.control_thread.quit()
            self.control_thread.wait(1000) # 최대 1초만 기다립니다.

        # 4. 상태를 최종적으로 업데이트합니다.
        self.is_connected = False
        self.btn_activate_robot.setText("원격 연결 시작")
        self.update_robot_status("N/A", "연결되지 않음")
        
        print("모니터링 탭 리소스 정리 완료.")
        
    def draw_simplified_map(self):
        label_size = self.map_display_label.size()
        pixmap = QPixmap(label_size)
        pixmap.fill(Qt.lightGray)
        painter = QPainter(pixmap)
        painter.setFont(QFont("Arial", 10))
        padding, zone_height = 10, int(label_size.height() * 0.25)
        rect_A = (padding, padding, int(label_size.width() * 0.4), zone_height)
        rect_B = (label_size.width() - int(label_size.width() * 0.4) - padding, padding, int(label_size.width() * 0.4), zone_height)
        rect_Home = ((label_size.width() - int(label_size.width() * 0.5)) // 2, label_size.height() - zone_height - padding, int(label_size.width() * 0.5), zone_height)
        zones = {"A구역": rect_A, "B구역": rect_B, "홈": rect_Home}
        colors = {"A구역": "lightblue", "B구역": "lightyellow", "홈": "lightgreen"}
        for name, rect in zones.items():
            painter.setBrush(QColor(colors[name]))
            painter.setPen(QPen(Qt.black, 1))
            painter.drawRect(*rect)
            painter.drawText(rect[0] + 5, rect[1] + 15, name)
        if self.current_robot_location in zones:
            zone_rect = zones[self.current_robot_location]
            center_x, center_y = zone_rect[0] + zone_rect[2] // 2, zone_rect[1] + zone_rect[3] // 2
            painter.setBrush(Qt.red)
            painter.drawEllipse(center_x - 5, center_y - 5, 10, 10)
        painter.end()
        self.map_display_label.setPixmap(pixmap)

    def add_detection_event(self, situation, time_str, location_str, description_str):
        row_count = self.detections_table.rowCount()
        self.detections_table.insertRow(row_count)
        self.detections_table.setItem(row_count, 0, QTableWidgetItem(situation))
        self.detections_table.setItem(row_count, 1, QTableWidgetItem(time_str))
        self.detections_table.setItem(row_count, 2, QTableWidgetItem(location_str))
        self.detections_table.setItem(row_count, 3, QTableWidgetItem(description_str))
        self.detections_table.scrollToBottom()

    def update_robot_location_on_map(self, location_name):
        self.current_robot_location = location_name
        self.draw_simplified_map()

    def update_robot_status(self, connectivity, status):
        self.connectivity_label.setText(f"Connectivity: {connectivity}")
        self.system_status_label.setText(f"STATUS: {status}")

    def handle_capture_image(self):
        pixmap = self.live_feed_label.pixmap()
        if not pixmap or pixmap.isNull(): QMessageBox.warning(self, "캡쳐 불가", "표시되고 있는 영상이 없습니다."); return
        image_to_save = pixmap.toImage()
        filename = f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        filepath = os.path.join(self.capture_dir, filename)
        os.makedirs(self.capture_dir, exist_ok=True)
        if image_to_save.save(filepath): QMessageBox.information(self, "캡쳐 성공", f"이미지를 저장했습니다:\n{os.path.abspath(filepath)}")
        else: QMessageBox.warning(self, "캡쳐 실패", "이미지 저장에 실패했습니다.")