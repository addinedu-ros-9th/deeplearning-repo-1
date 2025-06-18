# gui/tabs/monitoring_tab.py (수정된 최종 버전)

import os
from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QSizePolicy
)
from PyQt5.QtCore import (
    Qt, QPropertyAnimation, QPoint,
    QEasingCurve, QTimer, pyqtSignal
)
from PyQt5.QtGui import QPixmap
from PyQt5.uic import loadUi
import traceback # ✨ 추가됨

# 디버그 모드 설정
DEBUG = True

# UI 파일 경로
MONITORING_TAP_UI_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ui', 'monitoring_tab2.ui')
MONITORING_TAP_MAP_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ui', 'neighbot_map6.jpg')

class MonitoringTab(QWidget):
    robot_command = pyqtSignal(str)
    stream_command = pyqtSignal(bool)
    connection_error = pyqtSignal(str)
    
    LOCATIONS = {
        'BASE': QPoint(150, 250),
        'A': QPoint(50, 100),
        'B': QPoint(250, 100)
    }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_location = 'BASE'
        self.current_status = 'idle'
        self.is_moving = False
        self.streaming = False
        self.STATUS_MESSAGES = {
            'idle': '대기 중',
            'moving': '이동 중',
            'patrolling': '순찰 중'
        }
        self.init_ui()
        self.init_map()
        self.init_robot()
        
    def init_ui(self):
        try:
            loadUi(MONITORING_TAP_UI_FILE, self)
            if DEBUG: print("MonitoringTab UI 로드 완료")
                
            self.btn_move_to_A = self.findChild(QPushButton, "btn_move_to_A")
            self.btn_move_to_B = self.findChild(QPushButton, "btn_move_to_B")
            self.btn_return_home = self.findChild(QPushButton, "btn_return_to_home")
            self.btn_start_video_stream = self.findChild(QPushButton, "btn_start_video_stream")

            self.btn_move_to_A.clicked.connect(self.send_move_to_a_command)
            self.btn_move_to_B.clicked.connect(self.send_move_to_b_command)
            self.btn_return_home.clicked.connect(self.send_return_to_base_command)
            self.btn_start_video_stream.clicked.connect(self.start_stream)

            self.btn_fire_report = self.findChild(QPushButton, "btn_fire_report")
            self.btn_police_report = self.findChild(QPushButton, "btn_police_report")
            self.btn_illegal_warning = self.findChild(QPushButton, "btn_illegal_warning")
            self.btn_danger_warning = self.findChild(QPushButton, "btn_danger_warning")
            self.btn_emergency_warning = self.findChild(QPushButton, "btn_emergency_warning")
            self.btn_case_closed = self.findChild(QPushButton, "btn_case_closed")

            self.btn_fire_report.clicked.connect(lambda: self.robot_command.emit("FIRE_REPORT"))
            self.btn_police_report.clicked.connect(lambda: self.robot_command.emit("POLICE_REPORT"))
            self.btn_illegal_warning.clicked.connect(lambda: self.robot_command.emit("ILLEGAL_WARNING"))
            self.btn_danger_warning.clicked.connect(lambda: self.robot_command.emit("DANGER_WARNING"))
            self.btn_emergency_warning.clicked.connect(lambda: self.robot_command.emit("EMERGENCY_WARNING"))
            self.btn_case_closed.clicked.connect(lambda: self.robot_command.emit("CASE_CLOSED"))

            self.live_feed_label = self.findChild(QLabel, "live_feed_label")
            self.detection_image = self.findChild(QLabel, "detection_image")
            self.connectivity_label = self.findChild(QLabel, "connectivity_label")
            self.system_status_label = self.findChild(QLabel, "robot_status")
            self.detections_label = self.findChild(QLabel, "detections")
            
            self.connectivity_label.setText("연결 대기 중...")
            self.system_status_label.setText("시스템 초기화 중...")
            self.detections_label.setText("탐지 대기 중...")
            self.live_feed_label.setText("스트리밍 대기 중...")

        except Exception as e:
            if DEBUG:
                print(f"UI 초기화 실패: {e}")
                print(traceback.format_exc())
                        
    # ✨ 수정됨: 이미지 로드 실패 시 예외처리 보강
    def init_map(self):
        """맵 이미지 초기화"""
        try:
            self.map_display_label = self.findChild(QLabel, "map_display_label")
            if not self.map_display_label:
                if DEBUG: print("map_display_label을 찾을 수 없음")
                return

            self.map_pixmap = QPixmap(MONITORING_TAP_MAP_FILE)
            if self.map_pixmap.isNull():
                error_msg = f"맵 이미지 로드 실패!\n경로 확인: {MONITORING_TAP_MAP_FILE}"
                if DEBUG: print(error_msg)
                self.map_display_label.setText(error_msg)
                self.map_display_label.setAlignment(Qt.AlignCenter)
                self.map_display_label.setWordWrap(True)
                return

            QTimer.singleShot(100, self.resize_map)
            if DEBUG: print("맵 이미지 로드 시작")

        except Exception as e:
            if DEBUG:
                print(f"맵 초기화 실패: {e}")
                print(traceback.format_exc())

    def resize_map(self):
        """맵 이미지 크기 조정"""
        try:
            if self.map_pixmap.isNull(): return
            
            scaled_map = self.map_pixmap.scaled(
                self.map_display_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.map_display_label.setPixmap(scaled_map)
            self.map_display_label.setAlignment(Qt.AlignCenter)

        except Exception as e:
            if DEBUG:
                print(f"맵 크기 조정 실패: {e}")
                print(traceback.format_exc())

    def init_robot(self):
        """로봇 이미지 초기화"""
        try:
            self.robot_label = QLabel(self)
            robot_pixmap = QPixmap('./gui/ui/neigh_bot.png')
            if robot_pixmap.isNull():
                if DEBUG: print("로봇 이미지 로드 실패!")
                self.robot_label.setText("R") # 로봇 이미지 없으면 텍스트로 표시
            else:
                scaled_robot = robot_pixmap.scaled(30, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.robot_label.setPixmap(scaled_robot)

            self.robot_label.setParent(self.map_display_label)
            
            self.robot_animation = QPropertyAnimation(self.robot_label, b"pos")
            self.robot_animation.setEasingCurve(QEasingCurve.InOutQuad)
            self.robot_animation.setDuration(2000)
            self.robot_animation.finished.connect(self.movement_finished)
            
            self.move_robot_instantly('BASE')
            if DEBUG: print("로봇 이미지 초기화 완료")
                
        except Exception as e:
            if DEBUG:
                print(f"로봇 이미지 초기화 실패: {e}")
                print(traceback.format_exc())

    def move_robot_instantly(self, location):
        if location in self.LOCATIONS:
            pos = self.LOCATIONS[location]
            self.robot_label.move(pos.x() - 15, pos.y() - 15)
            self.current_location = location

    def animate_robot_movement(self, target_location):
        if self.is_moving or target_location not in self.LOCATIONS:
            return
        self.is_moving = True
        self.disable_movement_buttons()
        start_pos = self.robot_label.pos()
        target_pos = self.LOCATIONS[target_location]
        self.robot_animation.setStartValue(start_pos)
        self.robot_animation.setEndValue(QPoint(target_pos.x() - 15, target_pos.y() - 15))
        self.robot_animation.start()
        if DEBUG: print(f"로봇 이동 시작: {self.current_location} -> {target_location}")

    def movement_finished(self):
        self.is_moving = False
        # 이동이 끝나면 현재 위치를 타겟으로 확정
        for loc, pos in self.LOCATIONS.items():
            if self.robot_label.pos().x() + 15 == pos.x():
                self.current_location = loc
                break
        self.enable_movement_buttons()
        if DEBUG: print(f"로봇 이동 완료. 현재 위치: {self.current_location}")

    def disable_movement_buttons(self):
        self.btn_move_to_A.setEnabled(False)
        self.btn_move_to_B.setEnabled(False)
        self.btn_return_home.setEnabled(False)

    def enable_movement_buttons(self):
        self.btn_move_to_A.setEnabled(self.current_location != 'A')
        self.btn_move_to_B.setEnabled(self.current_location != 'B')
        self.btn_return_home.setEnabled(self.current_location != 'BASE')

    def update_robot_status(self, status: str):
        if self.current_status != status:
            self.current_status = status
            message = self.STATUS_MESSAGES.get(status, status)
            if DEBUG: print(f"로봇 상태 UI 업데이트: {status} ({message})")
            
            if status == 'moving':
                self.disable_movement_buttons()
            elif status in ['patrolling', 'idle']:
                self.movement_finished() # 이동이 끝났음을 명시적으로 처리
                self.enable_movement_buttons()
    
    def send_move_to_a_command(self):
        if self.current_location != 'A' and not self.is_moving:
            self.robot_command.emit("MOVE_TO_A")
            self.animate_robot_movement('A')
            self.update_status("system", "A 지점으로 이동 중...")
            self.update_robot_status("moving")

    def send_move_to_b_command(self):
        if self.current_location != 'B' and not self.is_moving:
            self.robot_command.emit("MOVE_TO_B")
            self.animate_robot_movement('B')
            self.update_status("system", "B 지점으로 이동 중...")
            self.update_robot_status("moving")

    def send_return_to_base_command(self):
        if self.current_location != 'BASE' and not self.is_moving:
            self.robot_command.emit("RETURN_TO_BASE")
            self.animate_robot_movement('BASE')
            self.update_status("system", "기지로 복귀 중...")
            self.update_robot_status("moving")

    def start_stream(self):
        try:
            if not self.streaming:
                self.streaming = True
                self.stream_command.emit(self.streaming)
                self.btn_start_video_stream.setText("영상 스트리밍 중")
                self.btn_start_video_stream.setEnabled(False)
                self.update_status("system", "스트리밍 시작 요청됨")
        except Exception as e:
            if DEBUG: print(f"스트리밍 제어 실패: {e}")
            self.connection_error.emit("스트리밍 제어 실패")

    def update_camera_feed(self, image_data: bytes):
        try:
            if not image_data or not self.live_feed_label: return

            pixmap = QPixmap()
            if not pixmap.loadFromData(image_data):
                if DEBUG: print("카메라 피드: QPixmap 변환 실패")
                return

            scaled_pixmap = pixmap.scaled(
                self.live_feed_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.live_feed_label.setPixmap(scaled_pixmap)
            self.live_feed_label.setAlignment(Qt.AlignCenter)
            
        except Exception as e:
            if DEBUG:
                print(f"카메라 피드 업데이트 실패: {e}")
                print(traceback.format_exc())
                
    def update_status(self, status_type: str, message: str):
        try:
            if status_type == "connectivity":
                self.connectivity_label.setText(message)
            elif status_type == "system":
                self.system_status_label.setText(message)
                if "상태:" in message:
                    status = message.split("상태:")[1].strip()
                    self.update_robot_status(status)
            elif status_type == "detections":
                self.detections_label.setText(message)
        except Exception as e:
            if DEBUG:
                print(f"상태 업데이트 실패: {e}")
                print(traceback.format_exc())