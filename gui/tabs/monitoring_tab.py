# gui/tabs/monitoring_tab.py

import os
from datetime import datetime # handle_capture_image 에서 사용

from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QTableWidget, QTableWidgetItem, QGroupBox, QPushButton, QMessageBox
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import pyqtSlot, Qt, QTimer
from PyQt5 import uic

from gui.threads.camera_thread import CameraThread

class MonitoringTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # .ui 파일 로드
        # monitoring_tab.ui 파일의 실제 경로를 정확히 지정해야 합니다.
        ui_file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui", "monitoring_tab.ui")
        uic.loadUi(ui_file_path, self)

        # 변수 초기화
        self.camera_thread = None
        self.is_camera_active = False
        self.current_qimage = None
        self.capture_dir = "captured_image"
        # os.makedirs(self.capture_dir, exist_ok=True) # 필요시 폴더 미리 생성

        # 시그널-슬롯 연결 (XML에 정의된 objectName 사용)
        if hasattr(self, 'btn_activate_robot'):
            self.btn_activate_robot.clicked.connect(self.handle_activate_robot)
        if hasattr(self, 'btn_move_to_A'):
            self.btn_move_to_A.clicked.connect(lambda: self.handle_move_robot("A구역"))
        if hasattr(self, 'btn_move_to_B'):
            self.btn_move_to_B.clicked.connect(lambda: self.handle_move_robot("B구역"))
        if hasattr(self, 'btn_return_home'):
            self.btn_return_home.clicked.connect(lambda: self.handle_move_robot("홈"))
        if hasattr(self, 'btn_capture_image'): # Remote 그룹으로 이동된 버튼
            self.btn_capture_image.clicked.connect(self.handle_capture_image)

        # 테이블 초기 설정 (컬럼 너비 등)
        if hasattr(self, 'detections_table'):
            # XML에서 컬럼 수와 헤더를 설정했으므로, 여기서는 주로 너비 조정
            self.detections_table.setColumnWidth(0, 80)
            self.detections_table.setColumnWidth(1, 100)
            self.detections_table.setColumnWidth(2, 100)
            self.detections_table.setColumnWidth(3, 150)
            # 테스트 데이터 추가 (필요시)
            self.add_detection_event("정보", "09:00:00", "N/A", "시스템 시작됨")


        # 초기 라벨 텍스트 및 스타일 설정 (XML에서 이미 설정했다면 중복될 수 있음)
        if hasattr(self, 'live_feed_label'):
            self.live_feed_label.setText("실시간 영상 대기 중...") # 초기 텍스트
            self.live_feed_label.setAlignment(Qt.AlignCenter)
            self.live_feed_label.setStyleSheet("background-color: black; color: white;")

        if hasattr(self, 'map_display_label'):
            self.map_display_label.setText("지도 로딩 중...") # 초기 텍스트
            self.map_display_label.setAlignment(Qt.AlignCenter)
            self.map_display_label.setStyleSheet("background-color: lightgrey;")


        # 지도 초기화 관련
        if hasattr(self, 'map_display_label'):
            self.current_robot_location = "홈"
            # UI가 완전히 표시된 후 지도를 그리기 위해 QTimer 사용 권장
            QTimer.singleShot(0, self.draw_simplified_map)


    @pyqtSlot(QImage)
    def update_image_slot(self, qt_image):
        self.current_qimage = qt_image.copy()
        if hasattr(self, 'live_feed_label'):
            pixmap = QPixmap.fromImage(qt_image)
            self.live_feed_label.setPixmap(pixmap.scaled(
                self.live_feed_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))

    def handle_activate_robot(self):
        if not self.is_camera_active:
            self.is_camera_active = True
            if hasattr(self, 'live_feed_label'):
                self.live_feed_label.clear() # 이전 Pixmap 또는 텍스트 제거
                self.live_feed_label.setText("카메라 로딩 중...")
            if hasattr(self, 'btn_activate_robot'):
                self.btn_activate_robot.setText("카메라 비활성화") # 버튼 텍스트 변경
            
            self.camera_thread = CameraThread(self)
            self.camera_thread.change_pixmap_signal.connect(self.update_image_slot)
            self.camera_thread.start()
            self.update_robot_status("Connected (Laptop Cam)", "카메라 활성화됨")
        else:
            self.is_camera_active = False
            if self.camera_thread:
                try: # 시그널 연결 해제
                    self.camera_thread.change_pixmap_signal.disconnect(self.update_image_slot)
                except TypeError:
                    pass # 이미 끊어졌거나 연결된 적 없는 경우
                self.camera_thread.stop()
                # self.camera_thread.wait(500) # 필요시 사용, GUI 반응성 저하 주의
                self.camera_thread = None
            
            if hasattr(self, 'btn_activate_robot'):
                self.btn_activate_robot.setText("카메라 활성화") # 버튼 텍스트 복원
            if hasattr(self, 'live_feed_label'):
                self.live_feed_label.clear() # 이전 Pixmap 또는 텍스트 제거
                self.live_feed_label.setText("실시간 영상 대기 중...")
                self.live_feed_label.setStyleSheet("background-color: black; color: white;")
            self.update_robot_status("N/A", "카메라 비활성화됨")

    def handle_move_robot(self, destination):
        if self.is_camera_active: # 예시로 카메라 활성화 상태에서만 이동하도록
            print(f"'{destination}'으로 이동 명령")
            self.update_robot_location_on_map(destination)
            self.update_robot_status(self.connectivity_label.text().split(': ')[1], f"{destination}(으)로 이동 중...") # 현재 연결상태 유지
        else:
            QMessageBox.warning(self, "알림", "카메라를 먼저 활성화해주세요.")

    def handle_capture_image(self):
        if not self.is_camera_active or self.current_qimage is None or self.current_qimage.isNull():
            QMessageBox.warning(self, "캡쳐 불가", "카메라가 활성화되어 영상이 표시 중일 때 캡쳐할 수 있습니다.")
            return

        capture_time = datetime.now()
        # 파일명 예: capture_20250605_221530_123.png
        filename = f"capture_{capture_time.strftime('%Y%m%d_%H%M%S')}_{capture_time.microsecond // 1000:03d}.png"
        
        # 저장 경로 구성 (self.capture_dir 사용)
        # main.py가 프로젝트 루트에 있고, capture_dir이 상대경로 "captured_image"라면
        # 프로젝트 루트/captured_image/ 에 저장됩니다.
        # os.path.join을 사용하여 운영체제에 맞는 경로 구분자 사용
        filepath = os.path.join(self.capture_dir, filename)

        try:
            os.makedirs(self.capture_dir, exist_ok=True) # 저장 폴더가 없으면 생성
            if self.current_qimage.save(filepath):
                QMessageBox.information(self, "캡쳐 성공", f"이미지가 다음 경로에 저장되었습니다:\n{os.path.abspath(filepath)}")
                print(f"Image captured: {os.path.abspath(filepath)}")
            else:
                QMessageBox.warning(self, "캡쳐 실패", f"이미지 저장에 실패했습니다 (경로: {filepath}). QImage.save() 실패.")
        except Exception as e:
            QMessageBox.critical(self, "캡쳐 오류", f"이미지 저장 중 오류 발생:\n{e}\n경로: {filepath}")


    def draw_simplified_map(self):
        if not hasattr(self, 'map_display_label') or not self.map_display_label.isVisible():
            return

        label_size = self.map_display_label.size()
        pixmap_width = label_size.width()
        pixmap_height = label_size.height()

        if pixmap_width <= 10 or pixmap_height <= 10 : # 유효한 크기가 될 때까지 기다리거나 기본값 사용
             min_size = self.map_display_label.minimumSize()
             pixmap_width, pixmap_height = min_size.width(), min_size.height()
             if pixmap_width <=10 or pixmap_height <=10: # Designer에서 minimumSize를 설정 안했다면
                 pixmap_width, pixmap_height = 300, 200 # 최후의 기본값

        pixmap = QPixmap(pixmap_width, pixmap_height)
        pixmap.fill(Qt.lightGray) # 기본 배경색

        painter = QPainter(pixmap)
        painter.setFont(QFont("Arial", 10))

        padding = 10
        zone_common_height = int(pixmap_height * 0.25)
        
        rect_A_width = int(pixmap_width * 0.4)
        rect_A = (padding, padding, rect_A_width, zone_common_height)
        
        rect_B_width = int(pixmap_width * 0.4)
        rect_B_x = pixmap_width - rect_B_width - padding
        rect_B = (rect_B_x, padding, rect_B_width, zone_common_height)
        
        rect_Home_width = int(pixmap_width * 0.5)
        rect_Home_x = (pixmap_width - rect_Home_width) // 2
        rect_Home_y = pixmap_height - zone_common_height - padding
        rect_Home = (rect_Home_x, rect_Home_y, rect_Home_width, zone_common_height)

        zones = {
            "A구역": {"rect": rect_A, "color": QColor("lightblue")},
            "B구역": {"rect": rect_B, "color": QColor("lightyellow")},
            "홈": {"rect": rect_Home, "color": QColor("lightgreen")}
        }

        for name, zone_info in zones.items():
            rect_coords = zone_info["rect"]
            painter.setBrush(zone_info["color"])
            painter.setPen(QPen(Qt.black, 1))
            painter.drawRect(rect_coords[0], rect_coords[1], rect_coords[2], rect_coords[3])
            
            text_x = rect_coords[0] + 5
            text_y = rect_coords[1] + painter.fontMetrics().ascent() + 5
            if text_y > rect_coords[1] + rect_coords[3] - 5 :
                 text_y = rect_coords[1] + rect_coords[3] // 2
            painter.drawText(text_x, text_y, name)

        if hasattr(self, 'current_robot_location') and self.current_robot_location in zones:
            zone_rect = zones[self.current_robot_location]["rect"]
            center_x = zone_rect[0] + zone_rect[2] // 2
            center_y = zone_rect[1] + zone_rect[3] // 2
            painter.setBrush(Qt.red)
            painter.drawEllipse(center_x - 5, center_y - 5, 10, 10)

        painter.end()
        self.map_display_label.setPixmap(pixmap)

    def add_detection_event(self, situation, time_str, location_str, description_str):
        if hasattr(self, 'detections_table'):
            row_count = self.detections_table.rowCount()
            self.detections_table.insertRow(row_count)
            self.detections_table.setItem(row_count, 0, QTableWidgetItem(situation))
            self.detections_table.setItem(row_count, 1, QTableWidgetItem(time_str))
            self.detections_table.setItem(row_count, 2, QTableWidgetItem(location_str))
            self.detections_table.setItem(row_count, 3, QTableWidgetItem(description_str))
            self.detections_table.scrollToBottom()

    def update_robot_location_on_map(self, location_name):
        self.current_robot_location = location_name
        self.draw_simplified_map() # 지도 업데이트

    def update_robot_status(self, connectivity_status, system_status):
        if hasattr(self, 'connectivity_label'):
            self.connectivity_label.setText(f"Connectivity: {connectivity_status}")
        if hasattr(self, 'system_status_label'):
            self.system_status_label.setText(f"STATUS: {system_status}")

    # 이 위젯이 닫힐 때 (예: 탭이 닫히거나 프로그램 종료 시 MainWindow가 호출) 호출될 수 있는 메서드
    def clean_up(self):
        print("MonitoringTab clean_up called")
        if self.camera_thread and self.camera_thread.isRunning():
            self.is_camera_active = False # 상태 플래그 업데이트
            self.camera_thread.stop()
            # self.camera_thread.wait(500) # MainWindow의 closeEvent에서 처리하는 것이 더 적절할 수 있음
            print("Camera thread stopped during MonitoringTab clean_up.")
            self.camera_thread = None


# MainWindow의 closeEvent에서 각 탭의 clean_up 메서드를 호출하는 것을 고려할 수 있습니다.
# 예: MainWindow.closeEvent 내부에서
# if hasattr(self, 'monitoring_tab_content') and hasattr(self.monitoring_tab_content, 'clean_up'):
# self.monitoring_tab_content.clean_up()