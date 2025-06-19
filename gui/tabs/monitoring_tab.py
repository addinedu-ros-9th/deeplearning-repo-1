# gui/tabs/monitoring_tab.py

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


# 디버그 모드 설정
DEBUG = True

# UI 파일 경로
MONITORING_TAP_UI_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ui', 'monitoring_tab3.ui')
MONITORING_TAP_MAP_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ui', 'neighbot_map6.jpg')

# MonitoringTab: Main Monitoring 탭의 UI 로드만 담당
class MonitoringTab(QWidget):
    # 시그널 정의
    robot_command = pyqtSignal(str)      # 로봇 명령 시그널
    stream_command = pyqtSignal(bool)    # 스트리밍 제어 시그널
    connection_error = pyqtSignal(str)   # 연결 에러 시그널
    
    # 지역 좌표 정의 (맵 상의 픽셀 좌표)
    LOCATIONS = {
        'BASE': QPoint(250, 340),    # 기지 위치
        'A': QPoint(180, 120),         # A 구역 위치
        'B': QPoint(320, 120),        # B 구역 위치
        'BASE_A_MID': QPoint(215, 230),  # BASE-A 중간지점
        'BASE_B_MID': QPoint(285, 230),  # BASE-B 중간지점
        'A_B_MID': QPoint(250, 120)       # A-B 중간지점
    }
    
    # 각 경로별 중간지점 매핑
    PATH_MIDPOINTS = {
        ('BASE', 'A'): 'BASE_A_MID',
        ('A', 'BASE'): 'BASE_A_MID',
        ('BASE', 'B'): 'BASE_B_MID',
        ('B', 'BASE'): 'BASE_B_MID',
        ('A', 'B'): 'A_B_MID',
        ('B', 'A'): 'A_B_MID'
    }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_location = 'BASE'     # 현재 위치
        self.target_location = None        # 목표 위치
        self.current_status = 'idle'       # 현재 상태
        self.is_moving = False            # 이동 중 여부
        self.waiting_server_confirm = False # 서버 확인 대기 중 여부
        self.init_ui()
        self.init_map()
        self.init_robot()
        self.streaming = False
        
        # 상태별 메시지 정의
        self.STATUS_MESSAGES = {
            'idle': '대기 중',
            'moving': '이동 중',
            'patrolling': '순찰 중'
        }

    def init_ui(self):
        """UI 초기화"""
        try:
            # UI 파일 로드
            loadUi(MONITORING_TAP_UI_FILE, self)

            if DEBUG:
                print("MonitoringTab UI 로드 완료")
                
            # 이동 명령 버튼 시그널 연결
            self.btn_move_to_a = self.findChild(QPushButton, "btn_move_to_a")
            self.btn_move_to_b = self.findChild(QPushButton, "btn_move_to_b")
            self.btn_return_base = self.findChild(QPushButton, "btn_return_to_base")
            self.btn_start_video_stream = self.findChild(QPushButton, "btn_start_video_stream")

            # 이동 버튼들 초기 비활성화
            self.btn_move_to_a.setEnabled(False)
            self.btn_move_to_b.setEnabled(False)
            self.btn_return_base.setEnabled(False)

            self.btn_move_to_a.clicked.connect(self.send_move_to_a_command)
            self.btn_move_to_b.clicked.connect(self.send_move_to_b_command)
            self.btn_return_base.clicked.connect(self.send_return_to_base_command)
            self.btn_start_video_stream.clicked.connect(self.start_stream)

            # 응답 명령 버튼 찾기 및 시그널 연결
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

            # 상태 표시 라벨 찾기
            self.live_feed_label = self.findChild(QLabel, "live_feed_label")  # 스트리밍 영상 표시
            self.detection_image = self.findChild(QLabel, "detection_image")   # 맵 이미지 표시
            self.connectivity_label = self.findChild(QLabel, "connectivity_label")
            self.system_status_label = self.findChild(QLabel, "robot_status")
            self.detections_label = self.findChild(QLabel, "detections")
            
            # 상태 라벨 초기화
            self.connectivity_label.setText("연결 대기 중...")
            self.system_status_label.setText("시스템 초기화 중...")
            self.detections_label.setText("탐지 대기 중...")
            self.live_feed_label.setText("스트리밍 대기 중...")
            
            if DEBUG:
                print("UI 요소 초기화 완료:")
                print(f"  - live_feed_label: {self.live_feed_label is not None}")
                print(f"  - detection_image: {self.detection_image is not None}")
                print(f"  - connectivity_label: {self.connectivity_label is not None}")
                print(f"  - system_status_label: {self.system_status_label is not None}")
                print(f"  - detections_label: {self.detections_label is not None}")
            
        except Exception as e:
            if DEBUG:
                print(f"UI 초기화 실패: {e}")
                import traceback
                print(traceback.format_exc())
                        
    def init_map(self):
        """맵 이미지 초기화 (원본 비율 유지)"""
        try:
            # 1) QLabel 가져오기
            self.map_display_label = self.findChild(QLabel, "map_display_label")
            if not self.map_display_label:
                if DEBUG:
                    print("map_display_label을 찾을 수 없음")
                return

            # 2) 표시 영역 크기 직접 지정
            TARGET_W, TARGET_H = 300, 300
            self.map_display_label.setMinimumSize(TARGET_W, TARGET_H)

            # 3) 이미지 로드
            self.map_pixmap = QPixmap(MONITORING_TAP_MAP_FILE)
            if self.map_pixmap.isNull():
                if DEBUG:
                    print("맵 이미지 로드 실패")
                return

            # 4) 약간의 지연 후 이미지 크기 조정
            QTimer.singleShot(100, self.resize_map)

            if DEBUG:
                print("맵 이미지 로드 시작")

        except Exception as e:
            if DEBUG:
                print(f"맵 초기화 실패: {e}")
                import traceback
                print(traceback.format_exc())

    def resize_map(self):
        """맵 이미지 크기 조정"""
        try:
            # 원본 비율 유지하며 크기 조정
            scaled_map = self.map_pixmap.scaled(
                self.map_display_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.map_display_label.setPixmap(scaled_map)
            self.map_display_label.setAlignment(Qt.AlignCenter)

            if DEBUG:
                print(f"맵 이미지 크기 조정 완료 (크기: {scaled_map.width()}×{scaled_map.height()})")

        except Exception as e:
            if DEBUG:
                print(f"맵 크기 조정 실패: {e}")
                import traceback
                print(traceback.format_exc())

    def init_robot(self):
        """로봇 이미지 초기화"""
        try:
            # 로봇 이미지 라벨 생성
            self.robot_label = QLabel(self)
            robot_pixmap = QPixmap('./gui/ui/neigh_bot.png')
            scaled_robot = robot_pixmap.scaled(30, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.robot_label.setPixmap(scaled_robot)
            self.robot_label.setParent(self.map_display_label)
            
            # 애니메이션 객체 생성
            self.robot_animation = QPropertyAnimation(self.robot_label, b"pos")
            self.robot_animation.setEasingCurve(QEasingCurve.InOutQuad)
            self.robot_animation.setDuration(2000)  # 2초 동안 이동
            self.robot_animation.finished.connect(self.movement_finished)
            
            # 초기 위치 설정
            self.move_robot_instantly('BASE')
            
            if DEBUG:
                print("로봇 이미지 초기화 완료")
                
        except Exception as e:
            if DEBUG:
                print(f"로봇 이미지 초기화 실패: {e}")
                import traceback
                print(traceback.format_exc())

    def move_robot_instantly(self, location):
        """로봇을 즉시 해당 위치로 이동"""
        if location in self.LOCATIONS:
            pos = self.LOCATIONS[location]
            self.robot_label.move(pos.x() - 15, pos.y() - 15)  # 중앙 정렬을 위해 크기의 절반만큼 조정
            self.current_location = location

    def animate_robot_movement(self, target_location):
        """이동 명령 시 중간 지점으로 먼저 이동"""
        if target_location not in ['A', 'B', 'BASE'] or self.is_moving:
            return
            
        self.is_moving = True
        self.waiting_server_confirm = True
        self.target_location = target_location
        self.disable_movement_buttons()
        
        # 경로에 따른 중간지점 찾기
        path_key = (self.current_location, target_location)
        mid_point = self.PATH_MIDPOINTS.get(path_key)
        
        if not mid_point:
            if DEBUG:
                print(f"올바르지 않은 경로: {path_key}")
            return
            
        # 중간 지점으로 이동
        start_pos = self.robot_label.pos()
        mid_pos = self.LOCATIONS[mid_point]
        
        self.robot_animation.setStartValue(start_pos)
        self.robot_animation.setEndValue(QPoint(mid_pos.x() - 15, mid_pos.y() - 15))
        self.robot_animation.setDuration(1000)  # 1초
        
        # 중간 지점 도착 후 서버 응답 대기
        self.robot_animation.finished.disconnect() if self.robot_animation.receivers(self.robot_animation.finished) > 0 else None
        self.robot_animation.finished.connect(self.midpoint_reached)
        
        if DEBUG:
            print(f"로봇 이동 시작: {self.current_location} -> {mid_point} -> {target_location}")
            
        self.robot_animation.start()

    def movement_finished(self):
        """이동 애니메이션 완료 처리"""
        self.is_moving = False
        if DEBUG:
            print(f"로봇 이동 완료: {self.current_location}")

    def disable_movement_buttons(self):
        """이동 버튼 비활성화"""
        self.btn_move_to_a.setEnabled(False)
        self.btn_move_to_b.setEnabled(False)
        self.btn_return_base.setEnabled(False)

    def enable_movement_buttons(self):
        """현재 위치에 따라 이동 버튼 활성화
        - BASE 위치: A, B 버튼만 활성화
        - A 위치: B, BASE 버튼만 활성화
        - B 위치: A, BASE 버튼만 활성화
        """
        if self.streaming:  # 스트리밍이 시작된 경우에만
            if self.current_location == 'BASE':
                self.btn_move_to_a.setEnabled(True)
                self.btn_move_to_b.setEnabled(True)
                self.btn_return_base.setEnabled(False)
            elif self.current_location == 'A':
                self.btn_move_to_a.setEnabled(False)
                self.btn_move_to_b.setEnabled(True)
                self.btn_return_base.setEnabled(True)
            elif self.current_location == 'B':
                self.btn_move_to_a.setEnabled(True)
                self.btn_move_to_b.setEnabled(False)
                self.btn_return_base.setEnabled(True)

    def update_robot_status(self, status: str):
        """로봇 상태 업데이트"""
        if self.current_status != status:
            self.current_status = status
            message = self.STATUS_MESSAGES.get(status, status)
            
            if DEBUG:
                print(f"로봇 상태 변경: {status} ({message})")
            
            # 상태에 따른 UI 업데이트
            if status == 'moving':
                # moving 상태일 때는 모든 이동 버튼 비활성화
                self.disable_movement_buttons()
                if DEBUG:
                    print("로봇 이동 중: 모든 이동 버튼 비활성화")
            elif status == 'patrolling' or status == 'idle':
                # 순찰 중이거나 대기 중일 때는 현재 위치에 따라 버튼 활성화
                if self.streaming:  # 스트리밍 중인 경우에만 버튼 활성화
                    self.enable_movement_buttons()
                    if DEBUG:
                        print(f"로봇 {status}: 이동 버튼 활성화 (현재 위치: {self.current_location})")

    def send_move_to_a_command(self):
        """A 지역으로 이동 명령을 전송"""
        if self.current_location != 'A' and not self.is_moving:
            if DEBUG:
                print(f"A 지역 이동 명령 전송 시도 (현재 위치: {self.current_location})")
            self.robot_command.emit("MOVE_TO_A")
            self.animate_robot_movement('A')
            if DEBUG:
                print("A 지역 이동 명령 전송 완료")
                print(f"A 지역 이동 명령 전송")

    def send_move_to_b_command(self):
        """B 지역으로 이동 명령을 전송"""
        if self.current_location != 'B' and not self.is_moving:
            if DEBUG:
                print(f"B 지역 이동 명령 전송 시도 (현재 위치: {self.current_location})")
            self.robot_command.emit("MOVE_TO_B")
            self.animate_robot_movement('B')
            if DEBUG:
                print("B 지역 이동 명령 전송 완료")
                print(f"B 지역 이동 명령 전송")

    def send_return_to_base_command(self):
        """기지로 복귀 명령을 전송"""
        if self.current_location != 'BASE' and not self.is_moving:
            if DEBUG:
                print(f"BASE로 이동 명령 전송 시도 (현재 위치: {self.current_location})")
            self.robot_command.emit("RETURN_TO_BASE")
            self.animate_robot_movement('BASE')
            if DEBUG:
                print("BASE 이동 명령 전송 완료")
                print(f"기지 복귀 명령 전송")

    def start_stream(self):
        """영상 스트리밍을 시작합니다 (한 번 시작하면 끌 수 없음)"""
        try:
            if not self.streaming:
                self.streaming = True
                self.stream_command.emit(True)
                self.btn_start_video_stream.setEnabled(False)
                
                # 현재 위치에 따라 이동 버튼 활성화
                self.enable_movement_buttons()
                
                if DEBUG:
                    print("스트리밍 시작: 이동 버튼 활성화됨")
            
        except Exception as e:
            if DEBUG:
                print(f"스트리밍 시작 실패: {e}")
                import traceback
                print(traceback.format_exc())
            self.connection_error.emit("스트리밍 시작 실패")

    def update_camera_feed(self, image_data: bytes):
        """서버에서 받은 카메라 피드를 업데이트"""
        try:
            # 스트리밍이 활성화된 경우에만 화면에 표시
            if not self.streaming:
                return

            if not image_data:
                if DEBUG:
                    print("이미지 데이터가 없습니다.")
                return

            if not self.live_feed_label:
                if DEBUG:
                    print("live_feed_label이 초기화되지 않았습니다.")
                return

            # 바이트 데이터로부터 QPixmap 생성
            pixmap = QPixmap()
            if not pixmap.loadFromData(image_data):
                if DEBUG:
                    print("이미지 데이터를 QPixmap으로 변환하지 못했습니다.")
                return

            # 이미지 크기를 라벨 크기에 맞게 조정
            scaled_pixmap = pixmap.scaled(
                self.live_feed_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            
            # 이미지 표시
            self.live_feed_label.setPixmap(scaled_pixmap)
            self.live_feed_label.setAlignment(Qt.AlignCenter)
            
        except Exception as e:
            if DEBUG:
                print(f"카메라 피드 업데이트 실패: {e}")
                import traceback
                print(traceback.format_exc())
                
    def update_status(self, status_type: str, message: str):
        """상태 정보를 업데이트"""
        try:
            if status_type == "connectivity":
                self.connectivity_label.setText(message)
            elif status_type == "system":
                self.system_status_label.setText(message)
                # 로봇 상태 정보 처리
                if "상태:" in message:
                    status = message.split("상태:")[1].strip()
                    self.update_robot_status(status)
                # 위치 정보 처리
                if "위치:" in message:
                    location = message.split("위치:")[1].split(",")[0].strip()
                    if location in self.LOCATIONS:
                        if self.waiting_server_confirm:
                            # 서버로부터 위치 확인을 받은 경우
                            self.server_confirmed_location(location)
                        elif location != self.current_location:
                            # 일반적인 위치 업데이트
                            self.current_location = location
            elif status_type == "detections":
                self.detections_label.setText(message)
        except Exception as e:
            if DEBUG:
                print(f"상태 업데이트 실패: {e}")
                import traceback
                print(traceback.format_exc())

    def continue_movement(self, final_destination):
        """중간 지점에서 최종 목적지로 이동"""
        target_pos = self.LOCATIONS[final_destination]
        
        # 잠시 대기 후 다음 이동 시작
        QTimer.singleShot(500, lambda: self._execute_final_movement(final_destination, target_pos))
        
    def _execute_final_movement(self, final_destination, target_pos):
        """최종 목적지로의 이동 실행"""
        self.robot_animation.finished.disconnect()  # 기존 연결 해제
        self.robot_animation.finished.connect(self.movement_finished)  # 원래 완료 핸들러 복원
        
        # 최종 목적지로 이동
        self.robot_animation.setStartValue(self.robot_label.pos())
        self.robot_animation.setEndValue(QPoint(target_pos.x() - 15, target_pos.y() - 15))
        self.robot_animation.setDuration(1000)  # 1초
        self.robot_animation.start()
        
        # 현재 위치 업데이트
        self.current_location = final_destination

    def midpoint_reached(self):
        """중간 지점 도착 후 서버의 위치 확인 신호 대기"""
        if DEBUG:
            print(f"중간 지점 도착. 서버의 위치 확인 대기 중... (목표: {self.target_location})")
        self.waiting_server_confirm = True

    def server_confirmed_location(self, confirmed_location):
        """서버로부터 위치 확인을 받았을 때 호출"""
        if not self.waiting_server_confirm:
            return
            
        if confirmed_location == self.target_location:
            # 최종 목적지로 이동
            self.complete_movement_to_target()
        else:
            if DEBUG:
                print(f"위치 불일치: 예상={self.target_location}, 실제={confirmed_location}")

    def complete_movement_to_target(self):
        """최종 목적지로 이동"""
        self.waiting_server_confirm = False
        target_pos = self.LOCATIONS[self.target_location]
        
        # 최종 목적지로 이동 시작
        self.robot_animation.setStartValue(self.robot_label.pos())
        self.robot_animation.setEndValue(QPoint(target_pos.x() - 15, target_pos.y() - 15))
        self.robot_animation.setDuration(1000)
        
        self.robot_animation.finished.disconnect()
        self.robot_animation.finished.connect(self.movement_finished)
        
        if DEBUG:
            print(f"최종 목적지로 이동: {self.target_location}")
        
        self.robot_animation.start()

