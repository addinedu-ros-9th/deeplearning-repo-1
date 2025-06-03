# gui/tabs/monitoring_tab.py

import sys
import os # 폴더 생성 및 경로 관련
from datetime import datetime # 파일명에 타임스탬프를 위해

# 현재 파일의 디렉토리 (gui/tabs)
# 스크립트가 심볼릭 링크인 경우 등 실제 파일 위치를 정확히 찾기 위해 realpath 사용 고려
# SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 하지만 여기서는 사용자가 제공한 경로가 명확하므로 다음과 같이 단순화 가능:
SCRIPT_DIR = os.path.dirname(__file__) # monitoring_tab.py 가 있는 gui/tabs/

# 프로젝트 루트 디렉토리 (mldl_project)
# os.path.join(SCRIPT_DIR, '..', '..') 는 gui/tabs/ 에서 두 단계 위로 올라가 mldl_project/ 를 가리킵니다.
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# --- 기존 import 구문들은 이 아래에 위치합니다 ---
# import cv2 # 이제 CameraThread 안에 있으므로 여기선 필요 없음
from PyQt5.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout,
                             QGridLayout, QComboBox, QTableWidget,
                             QTableWidgetItem, QGroupBox, QPushButton,
                             QApplication, QMessageBox) # QMessageBox 추가
from PyQt5.QtGui import QPixmap, QPainter, QColor, QPen, QFont, QImage
from PyQt5.QtCore import Qt, QTimer, pyqtSlot

# CameraThread 클래스를 새 파일에서 임포트
from gui.threads.camera_thread import CameraThread # 이제 이 임포트가 정상적으로 동작해야 합니다.

# ModuleNotFoundError: No module named 'gui' 오류는 Python이 gui 모듈을 찾을 수 없을 때 발생합니다. 
# 현재 /home/robolee/dev_ws/mldl_project/gui/tabs/monitoring_tab.py 파일을 직접 실행하려고 하셨는데, 
# 이 경우 Python은 monitoring_tab.py 파일이 있는 디렉토리 (.../gui/tabs/)를 실행 경로에 포함하지만, 
# 프로젝트의 최상위 디렉토리 (.../mldl_project/)를 항상 올바르게 인식하지는 못합니다.
# from gui.threads.camera_thread import CameraThread와 같은 절대 경로 임포트는 프로젝트 최상위 디렉토리(mldl_project)가 Python의 모듈 검색 경로(sys.path)에 있어야 올바르게 동작합니다.


class MonitoringTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("monitoringTab")
        self.camera_thread = None
        self.is_camera_active = False
        self.current_qimage = None # 현재 프레임(QImage)을 저장할 변수 추가
        # self.capture_base_dir = "Captured_image" # main.py 실행 위치 기준 상대 경로

        # 프로젝트 루트를 기준으로 경로 설정 (main.py가 mldl_project 폴더에 있다고 가정)
        # main.py 에서 실행될 때의 현재 작업 디렉토리가 mldl_project 이므로,
        # "Captured_image"는 mldl_project/Captured_image 에 해당됩니다.
        self.capture_dir = "captured_image"

        self.init_ui()

    def init_ui(self):
        # --- 전체 레이아웃 설정 ---
        main_layout = QHBoxLayout(self)
        left_panel_widget = QWidget()
        left_panel_layout = QVBoxLayout(left_panel_widget)
        right_panel_widget = QWidget()
        right_panel_layout = QVBoxLayout(right_panel_widget)

        # --- 좌측 패널 ---
        # 1. Live 영상 섹션
        live_group = QGroupBox("Live")
        live_group_layout = QVBoxLayout()
        self.live_feed_label = QLabel("실시간 영상이 여기에 표시됩니다.")
        self.live_feed_label.setMinimumSize(640, 480)
        self.live_feed_label.setAlignment(Qt.AlignCenter)
        self.live_feed_label.setStyleSheet("background-color: black; color: white;")
        live_group_layout.addWidget(self.live_feed_label)
        live_group.setLayout(live_group_layout)
        left_panel_layout.addWidget(live_group)

        # 2. Robot Status 섹션
        status_group = QGroupBox("Robot Status")
        status_group_layout = QGridLayout()
        self.connectivity_label = QLabel("Connectivity: N/A")
        self.system_status_label = QLabel("STATUS: N/A")
        status_group_layout.addWidget(self.connectivity_label, 0, 0, 1, 2)
        status_group_layout.addWidget(self.system_status_label, 1, 0, 1, 2)

        self.btn_activate_robot = QPushButton("노트북 카메라 활성화") # 버튼 텍스트 변경
        self.btn_move_to_A = QPushButton("A구역 이동")
        self.btn_move_to_B = QPushButton("B구역 이동")
        self.btn_return_home = QPushButton("홈으로 복귀")

        status_group_layout.addWidget(self.btn_activate_robot, 2, 0, 1, 2)
        status_group_layout.addWidget(self.btn_move_to_A, 3, 0)
        status_group_layout.addWidget(self.btn_move_to_B, 3, 1)
        status_group_layout.addWidget(self.btn_return_home, 4, 0, 1, 2)

        self.btn_activate_robot.clicked.connect(self.handle_activate_robot)
        self.btn_move_to_A.clicked.connect(lambda: self.handle_move_robot("A구역"))
        self.btn_move_to_B.clicked.connect(lambda: self.handle_move_robot("B구역"))
        self.btn_return_home.clicked.connect(lambda: self.handle_move_robot("홈"))

        status_group.setLayout(status_group_layout)
        left_panel_layout.addWidget(status_group)
        left_panel_layout.addStretch(1)

        # 3. Capture 섹션 (Robot Status 밑)
        capture_group = QGroupBox("Capture")
        capture_group_layout = QVBoxLayout() # 버튼 하나이므로 QVBoxLayout 사용
        self.btn_capture_image = QPushButton("영상캡쳐")
        self.btn_capture_image.clicked.connect(self.handle_capture_image) # 핸들러 연결
        capture_group_layout.addWidget(self.btn_capture_image)
        capture_group.setLayout(capture_group_layout)
        left_panel_layout.addWidget(capture_group) # status_group 다음에 추가

        left_panel_layout.addStretch(1) # Capture 그룹 밑에 여백 추가

        # --- 우측 패널 (기존과 동일 부분 생략) ---
        # 4. Map 섹션
        map_group = QGroupBox("Map")
        map_group_layout = QVBoxLayout()
        self.map_display_label = QLabel()
        self.map_display_label.setMinimumSize(300, 200)
        self.current_robot_location = "홈"
        self.draw_simplified_map()
        map_group_layout.addWidget(self.map_display_label)
        map_group.setLayout(map_group_layout)
        right_panel_layout.addWidget(map_group)

        # 5. Recent Detections 섹션
        detections_group = QGroupBox("Recent Detections")
        detections_group_layout = QVBoxLayout()
        self.detections_table = QTableWidget()
        self.detections_table.setColumnCount(4)
        self.detections_table.setHorizontalHeaderLabels(["상황", "시간", "장소", "내용"])
        # 컬럼 너비 설정 (생략) ...
        detections_group_layout.addWidget(self.detections_table)
        detections_group.setLayout(detections_group_layout)
        right_panel_layout.addWidget(detections_group)
        # ... 컬럼 너비 설정 및 테스트 데이터 추가 부분은 이전 코드와 동일 ...
        self.detections_table.setColumnWidth(0, 80)
        self.detections_table.setColumnWidth(1, 100)
        self.detections_table.setColumnWidth(2, 100)
        self.detections_table.setColumnWidth(3, 150)
        self.add_detection_event("위험", "10:03:15", "A구역", "칼 감지")
        self.add_detection_event("위법", "10:05:22", "B구역", "흡연 감지")


        main_layout.addWidget(left_panel_widget, 1)
        main_layout.addWidget(right_panel_widget, 1)


    @pyqtSlot(QImage)
    def update_image_slot(self, qt_image):
        # 수신된 QImage를 저장 (캡쳐 시 사용하기 위함). copy()로 안전하게 복사본 저장.
        self.current_qimage = qt_image.copy()

        pixmap = QPixmap.fromImage(qt_image) # pixmap 변환은 여기서만
        self.update_live_feed(pixmap) # QLabel 업데이트는 기존 로직 사용

    def handle_activate_robot(self):
        if not self.is_camera_active:
            # 카메라 활성화 로직
            self.is_camera_active = True
            # 기존 QLabel의 내용을 먼저 정리하고 로딩 메시지 표시
            self.live_feed_label.clear()
            self.live_feed_label.setText("카메라 로딩 중...")
            self.live_feed_label.setStyleSheet("background-color: black; color: white;") # 로딩 중에도 검은 배경 유지

            self.camera_thread = CameraThread(self)
            self.camera_thread.change_pixmap_signal.connect(self.update_image_slot)
            self.camera_thread.start()
            self.btn_activate_robot.setText("노트북 카메라 비활성화")
            self.update_robot_status("Connected (Laptop Cam)", "카메라 활성화됨")
        else:
            # 카메라 비활성화 로직
            self.is_camera_active = False
            if self.camera_thread:
                # 1. 시그널 연결 먼저 해제
                try:
                    self.camera_thread.change_pixmap_signal.disconnect(self.update_image_slot)
                except TypeError:
                    # 이미 연결이 끊어져 있거나, 연결된 적이 없는 경우 TypeError 발생 가능
                    pass
                
                self.camera_thread.stop() # 스레드에 중지 신호 보내기
                # self.camera_thread.wait(500) # 스레드가 완전히 종료될 때까지 최대 0.5초 대기 (선택적, GUI 반응성 저하 주의)
                                            # wait를 사용하려면 CameraThread의 stop에서 self.quit()와 함께 사용하는 것이 일반적
                self.camera_thread = None

            self.btn_activate_robot.setText("노트북 카메라 활성화")
            
            # 2. QLabel 내용 초기화 후 텍스트 및 스타일 설정
            self.live_feed_label.clear() # 이전 Pixmap을 완전히 제거
            self.live_feed_label.setText("실시간 영상이 여기에 표시됩니다.")
            self.live_feed_label.setStyleSheet("background-color: black; color: white;")
            
            self.update_robot_status("N/A", "카메라 비활성화됨")


    def handle_move_robot(self, destination):
        if self.is_camera_active:
            # 카메라가 활성화된 경우: 기존 이동 로직 수행
            print(f"'{destination}'으로 이동 명령 버튼 클릭됨 (카메라 활성 상태)")
            
            # 여기에 실제 로봇을 해당 목적지로 이동시키는 로직이 있다면 추가합니다.
            # 예: self.robot_controller.move_to(destination) 
            
            self.update_robot_location_on_map(destination) # 지도에 로봇 위치 업데이트
            self.update_robot_status("Connected (Laptop Cam)", f"{destination}(으)로 이동 중...") # 로봇 상태 업데이트
        else:
            # 카메라가 비활성화된 경우: 알림창 표시
            QMessageBox.warning(self, "알림", "카메라를 활성화하고 눌러주세요.")
            print(f"'{destination}' 이동 버튼 클릭 시도 (카메라 비활성 상태) - 알림 표시됨")


    def handle_capture_image(self):
        if not self.is_camera_active or self.current_qimage is None:
            QMessageBox.warning(self, "알림", "카메라가 활성화되어 영상이 표시 중일 때 캡쳐할 수 있습니다.")
            return

        # 1. 저장 폴더 생성 (없으면 자동으로 만듦)
        try:
            # self.capture_dir 은 __init__ 에서 "Captured_image"로 정의됨
            # main.py를 mldl_project 폴더에서 실행하면 mldl_project/Captured_image 에 생성됨
            os.makedirs(self.capture_dir, exist_ok=True)
        except OSError as e:
            QMessageBox.critical(self, "폴더 생성 오류", f"캡쳐 폴더를 생성할 수 없습니다:\n{self.capture_dir}\n{e}")
            return

        # 2. 파일명 생성 (타임스탬프 기반으로 고유하게)
        try:
            now = datetime.now()
            # 파일명 예: capture_20250604_010530_123.png (밀리초까지 포함)
            filename = f"capture_{now.strftime('%Y%m%d_%H%M%S')}_{now.microsecond // 1000:03d}.png"
            filepath = os.path.join(self.capture_dir, filename)
        except Exception as e:
            QMessageBox.critical(self, "파일명 생성 오류", f"캡쳐 파일명 생성 중 오류 발생:\n{e}")
            return

        # 3. 이미지 저장 (QImage의 save 메서드 사용)
        try:
            if self.current_qimage.save(filepath):
                # 성공 시 절대 경로를 포함하여 메시지 박스 표시
                QMessageBox.information(self, "캡쳐 성공", f"이미지가 다음 경로에 저장되었습니다:\n{os.path.abspath(filepath)}")
                print(f"Image captured and saved to: {os.path.abspath(filepath)}")
            else:
                # save 메서드가 False를 반환하는 경우는 드물지만, 실패 메시지 처리
                QMessageBox.warning(self, "캡쳐 실패", f"이미지를 저장하는데 실패했습니다:\n{filepath}")
        except Exception as e:
            QMessageBox.critical(self, "이미지 저장 오류", f"이미지 저장 중 오류 발생:\n{filepath}\n{e}")


    # --- 기존 메서드들 ---
    def draw_simplified_map(self):
        pixmap_width = self.map_display_label.width()
        pixmap_height = self.map_display_label.height()
        if pixmap_width == 0 or pixmap_height == 0 :
             pixmap_width, pixmap_height = self.map_display_label.minimumSize().width(), self.map_display_label.minimumSize().height()

        pixmap = QPixmap(pixmap_width, pixmap_height)
        pixmap.fill(Qt.lightGray)

        painter = QPainter(pixmap)
        painter.setFont(QFont("Arial", 10))

        # --- 구역 정의 수정 ---
        padding = 10  # 구역과 맵 경계 사이의 간격
        
        # 공통 높이 및 너비 비율 정의 (조정 가능)
        zone_common_height = int(pixmap_height * 0.25) # 모든 구역의 높이를 맵 높이의 25%로 설정
        
        # A구역 (좌측 위)
        rect_A_width = int(pixmap_width * 0.4) # A구역 너비는 맵 너비의 40%
        rect_A = (padding, padding, rect_A_width, zone_common_height)
        
        # B구역 (우측 위)
        rect_B_width = int(pixmap_width * 0.4) # B구역 너비도 맵 너비의 40%
        rect_B_x = pixmap_width - rect_B_width - padding # B구역 x좌표
        rect_B = (rect_B_x, padding, rect_B_width, zone_common_height)
        
        # 홈 (가로 가운데 아래)
        rect_Home_width = int(pixmap_width * 0.5) # 홈 구역 너비는 맵 너비의 50%
        rect_Home_x = (pixmap_width - rect_Home_width) // 2 # 홈 구역 x좌표 (가운데 정렬)
        rect_Home_y = pixmap_height - zone_common_height - padding # 홈 구역 y좌표 (아래 정렬)
        rect_Home = (rect_Home_x, rect_Home_y, rect_Home_width, zone_common_height)

        zones = {
            "A구역": {"rect": rect_A, "color": QColor("lightblue")}, # A구역 정의
            "B구역": {"rect": rect_B, "color": QColor("lightyellow")}, # B구역 정의
            "홈": {"rect": rect_Home, "color": QColor("lightgreen")}  # 홈 구역 정의
        }
        # --- 구역 정의 수정 끝 ---

        for name, zone_info in zones.items():
            rect_coords = zone_info["rect"]
            painter.setBrush(zone_info["color"])
            painter.setPen(QPen(Qt.black, 1))
            painter.drawRect(rect_coords[0], rect_coords[1], rect_coords[2], rect_coords[3])
            
            # 텍스트 위치를 사각형 중앙에 가깝게 조정 (선택 사항)
            text_x = rect_coords[0] + 5
            text_y = rect_coords[1] + painter.fontMetrics().ascent() + 5 # 폰트 높이 고려
            if text_y > rect_coords[1] + rect_coords[3] - 5 : # 너무 아래로 내려가지 않도록
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

    def update_live_feed(self, pixmap): # QPixmap을 직접 받도록 수정
        self.live_feed_label.setPixmap(pixmap.scaled(
            self.live_feed_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        ))

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
        print(f"지도 업데이트: 로봇 위치 - {location_name}")

    def update_robot_status(self, connectivity_status, system_status):
        self.connectivity_label.setText(f"Connectivity: {connectivity_status}")
        self.system_status_label.setText(f"STATUS: {system_status}")

    # 탭이 닫히거나 프로그램 종료 시 카메라 스레드 정리 (더 견고한 처리가 필요할 수 있음)
    def closeEvent(self, event): # QWidget에는 closeEvent가 직접적으로 동일하게 동작하지 않음
        print("MonitoringTab closeEvent (or equivalent) called")
        if self.camera_thread and self.camera_thread.isRunning():
            self.camera_thread.stop()
            # self.camera_thread.wait() # 여기서 wait()는 GUI를 멈출 수 있음
        super().closeEvent(event) # QWidget의 경우 이 방식이 아님

# 이 파일을 직접 실행해서 테스트해볼 수 있도록 임시 코드 추가
if __name__ == '__main__':
    import sys
    app = QApplication(sys.argv)
    main_tab = MonitoringTab()
    # 프로그램 종료 시 카메라 자원 해제를 위한 테스트 코드
    def app_about_to_quit():
        print("Application about to quit")
        if main_tab.camera_thread and main_tab.camera_thread.isRunning():
            print("Stopping camera thread from app_about_to_quit")
            main_tab.camera_thread.stop()
            main_tab.camera_thread.wait(1000) # 최대 1초 대기

    app.aboutToQuit.connect(app_about_to_quit) # 애플리케이션 종료 직전에 호출

    main_tab.show()
    sys.exit(app.exec_())