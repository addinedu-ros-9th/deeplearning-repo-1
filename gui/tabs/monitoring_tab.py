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
MONITORING_TAP_UI_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ui', 'monitoring_tab5.ui')
MONITORING_TAP_MAP_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ui', 'neighbot_map6.jpg')

# MonitoringTab: Main Monitoring 탭의 UI 로드만 담당
class MonitoringTab(QWidget):
    # 시그널 정의
    robot_command = pyqtSignal(str)      # 로봇 명령 시그널
    stream_command = pyqtSignal(bool)    # 스트리밍 제어 시그널
    connection_error = pyqtSignal(str)   # 연결 에러 시그널
    
    # 지역 좌표 정의 (맵 상의 픽셀 좌표)
    LOCATIONS = {
        'BASE': QPoint(250, 270),        # 기지 위치
        'A': QPoint(190, 125),           # A 구역 위치
        'B': QPoint(315, 125),           # B 구역 위치
        'BASE_A_MID': QPoint(220, 198),  # BASE-A 중간지점
        'BASE_B_MID': QPoint(283, 198),  # BASE-B 중간지점 
        'A_B_MID': QPoint(253, 125)      # A-B 중간지점
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
    
    def __init__(self, parent=None, user_name=None):
        super().__init__(parent)
        self.current_location = 'BASE'     # 현재 위치
        self.target_location = None        # 목표 위치
        self.current_status = 'idle'       # 현재 상태
        self.is_moving = False            # 이동 중 여부
        self.waiting_server_confirm = False # 서버 확인 대기 중 여부
        self.user_name = user_name or "사용자"  # 사용자 이름 (기본값 설정)
        self.system_ready = False          # 시스템 준비 상태 (첫 스트리밍 시작 후 True)
        self.streaming = False             # 스트리밍 표시 여부 (화면에 보여주는지)
        self.init_ui()
        self.init_map()
        self.init_robot()
        
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
            
            # 사용자 이름 표시 라벨 설정
            self.label_user_name = self.findChild(QLabel, "label_user_name")
            if self.label_user_name:
                self.label_user_name.setText(f"사용자: {self.user_name}")
                if DEBUG:
                    print(f"사용자 이름 설정됨: {self.user_name}")
            else:
                if DEBUG:
                    print("경고: label_user_name을 찾을 수 없습니다.")
                
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
            
            # CASE_CLOSED 버튼은 명령 전송 후 버튼 비활성화 처리
            self.btn_case_closed.clicked.connect(self.handle_case_closed)
            
            # 초기에 응답 버튼 비활성화 (탐지 팝업에서 "진행"을 선택해야 활성화됨)
            self.set_response_buttons_enabled(False)

            # 상태 표시 라벨 찾기
            self.live_feed_label = self.findChild(QLabel, "live_feed_label")  # 스트리밍 영상 표시
            self.detection_image = self.findChild(QLabel, "detection_image")   # 맵 이미지 표시
            self.connectivity_label = self.findChild(QLabel, "connectivity_label")
            self.robot_status_label = self.findChild(QLabel, "robot_status")
            self.robot_location_label = self.findChild(QLabel, "robot_location")
            self.detections_label = self.findChild(QLabel, "detections")
            
            # 상태 라벨 초기화 (접두사 추가)
            self.connectivity_label.setText("연결 상태: 연결 대기 중...")
            self.robot_status_label.setText("로봇 상태: 비활성화 - 시작 버튼을 눌러주세요")
            self.robot_location_label.setText("로봇 위치: 대기 중")
            self.detections_label.setText("탐지 상태: 시스템을 시작하면 탐지 결과가 표시됩니다")
            self.live_feed_label.setText("비디오 상태: 시스템 비활성화 - 시작 버튼을 눌러주세요")
            
            # 스트리밍 버튼 초기 텍스트 설정
            self.btn_start_video_stream.setText("Start Video Stream")
            
            if DEBUG:
                print("UI 요소 초기화 완료:")
                print(f"  - live_feed_label: {self.live_feed_label is not None}")
                print(f"  - detection_image: {self.detection_image is not None}")
                print(f"  - connectivity_label: {self.connectivity_label is not None}")
                print(f"  - robot_status_label: {self.robot_status_label is not None}")
                print(f"  - robot_location_label: {self.robot_location_label is not None}")
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
            QTimer.singleShot(500, self.resize_map)

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
            if DEBUG:
                print(f"이동 불가: 목적지={target_location}, 이동 중={self.is_moving}")
            return
            
        self.is_moving = True
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
        if self.robot_animation.receivers(self.robot_animation.finished) > 0:
            self.robot_animation.finished.disconnect()
        self.robot_animation.finished.connect(self.midpoint_reached)
        
        if DEBUG:
            print(f"로봇 이동 시작: {self.current_location} -> {mid_point} -> {target_location}")
            
        self.robot_animation.start()

    def movement_finished(self):
        """이동 애니메이션 완료 처리"""
        if not self.is_moving:
            # 이미 이동이 완료되었으면 버튼 상태만 업데이트
            if self.streaming:
                self.enable_movement_buttons()
        
        if DEBUG:
            print(f"로봇 이동 애니메이션 완료: {self.current_location}")

    def complete_movement_to_target(self):
        """최종 목적지로 이동"""
        if DEBUG:
            print(f"최종 목적지로 이동 시작: {self.target_location}")
            
        self.waiting_server_confirm = False
        target_pos = self.LOCATIONS[self.target_location]
        
        # 최종 목적지로 이동 시작
        self.robot_animation.setStartValue(self.robot_label.pos())
        self.robot_animation.setEndValue(QPoint(target_pos.x() - 15, target_pos.y() - 15))
        self.robot_animation.setDuration(1000)
        
        # 이전 연결 해제 및 새 연결 설정
        if self.robot_animation.receivers(self.robot_animation.finished) > 0:
            self.robot_animation.finished.disconnect()
        self.robot_animation.finished.connect(self._movement_complete_callback)
        
        # 애니메이션 시작
        self.robot_animation.start()
        
    def _movement_complete_callback(self):
        """이동 완료 콜백 - 상태 업데이트 및 UI 갱신"""
        # 이동 완료 처리
        self.is_moving = False
        self.current_location = self.target_location
        
        if DEBUG:
            print(f"로봇 이동 완료: 위치={self.current_location}")
        
        # UI 갱신
        if self.system_ready:
            self.enable_movement_buttons()
            
        # 추가 이벤트가 필요하면 여기에 추가

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
        if self.system_ready:  # 시스템이 활성화된 경우에만 (스트리밍 표시 여부와 무관)
            if self.current_location == 'BASE':
                self.btn_move_to_a.setEnabled(True)
                self.btn_move_to_b.setEnabled(True)
                self.btn_return_base.setEnabled(False)
                if DEBUG:
                    print("BASE 위치: A, B 버튼 활성화")
            elif self.current_location == 'A':
                self.btn_move_to_a.setEnabled(False)  # A에 있을 때는 A로 이동 불가
                self.btn_move_to_b.setEnabled(True)
                self.btn_return_base.setEnabled(True)
                if DEBUG:
                    print("A 위치: B, BASE 버튼 활성화")
            elif self.current_location == 'B':
                self.btn_move_to_a.setEnabled(True)
                self.btn_move_to_b.setEnabled(False)  # B에 있을 때는 B로 이동 불가
                self.btn_return_base.setEnabled(True)
                if DEBUG:
                    print("B 위치: A, BASE 버튼 활성화")

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
                if self.system_ready:  # 시스템이 활성화된 경우에만 버튼 활성화 (스트리밍 표시 여부와 무관)
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
        """영상 스트리밍을 토글합니다 (시스템은 계속 가동)"""
        try:
            # 시스템 초기 활성화 (최초 1회)
            if not self.system_ready:
                self.system_ready = True
                self.streaming = True
                self.stream_command.emit(True)  # 시스템 활성화 신호 전송
                self.btn_start_video_stream.setText("Stop Video Stream")
                
                # 영상 피드 초기화 (접두사 추가)
                self.live_feed_label.setText("비디오 상태: 스트리밍 시작 중...")
                
                # 현재 위치에 따라 이동 버튼 활성화 (최초 1회만)
                self.enable_movement_buttons()
                
                if DEBUG:
                    print("시스템 및 스트리밍 최초 활성화: 이동 버튼 활성화됨")
            
            # 이미 시스템이 활성화된 상태에서는 영상 표시 토글만 수행
            else:
                # 스트리밍 토글
                self.streaming = not self.streaming
                
                if self.streaming:
                    # 영상 표시 활성화
                    self.btn_start_video_stream.setText("Stop Video Stream")
                    self.live_feed_label.setText("비디오 상태: 스트리밍 활성화됨")
                    if DEBUG:
                        print("비디오 스트림 표시 활성화")
                else:
                    # 영상 표시 비활성화 (백그라운드 수신은 계속)
                    self.btn_start_video_stream.setText("Start Video Stream")
                    self.live_feed_label.setText("비디오 상태: 스트리밍 비활성화 - 시작 버튼을 눌러주세요")
                    if DEBUG:
                        print("비디오 스트림 표시 중지 (백그라운드에서는 계속 수신)")
            
        except Exception as e:
            if DEBUG:
                print(f"스트리밍 토글 실패: {e}")
                import traceback
                print(traceback.format_exc())
            self.connection_error.emit("스트리밍 토글 실패")

    def update_camera_feed(self, image_data: bytes):
        """서버에서 받은 카메라 피드를 업데이트
        카메라 스트림은 항상 백그라운드에서 수신하지만,
        self.streaming이 True일 때만 화면에 표시합니다.
        """
        try:
            # 영상 데이터 유효성 검사 (항상 수행)
            if not image_data:
                if DEBUG:
                    print("이미지 데이터가 없습니다.")
                return

            if not self.live_feed_label:
                if DEBUG:
                    print("live_feed_label이 초기화되지 않았습니다.")
                return
            
            # 스트리밍 비활성화 상태일 때는 화면 표시하지 않음
            if not self.streaming:
                # 화면을 업데이트하지 않고 데이터만 처리 (백그라운드 수신)
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
                # 연결 상태 라벨에 접두사 추가
                formatted_msg = f"연결 상태: {message}"
                self.connectivity_label.setText(formatted_msg)
            elif status_type == "robot_status":
                # 로봇 상태만 업데이트
                # 시스템이 준비되지 않은 경우 (첫 Start 버튼을 누르기 전)
                if not self.system_ready:
                    self.robot_status_label.setText("로봇 상태: 비활성화 - 시작 버튼을 눌러주세요")
                    return
                
                # 시스템은 준비되었지만 스트리밍 화면이 비활성화된 경우
                if not self.streaming:
                    self.robot_status_label.setText("로봇 상태: 스트리밍 비활성화 - 시작 버튼을 눌러주세요")
                    return
                
                # 로봇 상태 업데이트
                formatted_msg = f"로봇 상태: {message}"
                self.robot_status_label.setText(formatted_msg)
                self.update_robot_status(message)
                
            elif status_type == "robot_location":
                # 로봇 위치만 업데이트
                # 시스템이 준비되지 않은 경우
                if not self.system_ready:
                    self.robot_location_label.setText("로봇 위치: 대기 중")
                    return
                
                # 시스템은 준비되었지만 스트리밍 비활성화
                if not self.streaming:
                    self.robot_location_label.setText("로봇 위치: 대기 중")
                    return
                
                # 로봇 위치 업데이트
                formatted_msg = f"로봇 위치: {message}"
                self.robot_location_label.setText(formatted_msg)
                
                # 위치 정보 처리 
                actual_location, is_moving, destination = self.parse_location(message)
                
                if actual_location:
                    # 이동 중인 경우 중간 지점 이동 상태라고 설정
                    if is_moving and destination:
                        if not self.is_moving:
                            # 이동 중으로 상태 변경
                            self.is_moving = True
                            self.target_location = destination
                            if DEBUG:
                                print(f"이동 중 감지: {self.current_location} -> {destination}")
                            # 이동 버튼 비활성화
                            self.disable_movement_buttons()
                    # 이동중이 아니고 실제 위치값(A, B, BASE)이 온 경우
                    elif not is_moving:
                        # 이동 중이었고, 서버에서 온 위치가 목적지와 같으면
                        if self.is_moving and self.waiting_server_confirm and actual_location == self.target_location:
                            if DEBUG:
                                print(f"목적지 도착 확인: {actual_location}, complete_movement_to_target 호출")
                            # 최종 목적지로 이동 애니메이션 실행
                            self.complete_movement_to_target()
                        # 일반 위치 업데이트 (이동 중이 아닐 때)
                        elif actual_location != self.current_location:
                            self.current_location = actual_location
                            if self.system_ready:
                                self.enable_movement_buttons()
                                
            elif status_type == "system":
                # 기존 로직 유지 (하위 호환성)
                # 시스템이 준비되지 않은 경우 (첫 Start 버튼을 누르기 전)
                if not self.system_ready:
                    self.update_status("robot_status", "비활성화 - 시작 버튼을 눌러주세요")
                    self.update_status("robot_location", "대기 중")
                    return
                
                # 시스템은 준비되었지만 스트리밍 화면이 비활성화된 경우
                if not self.streaming:
                    self.update_status("robot_status", "스트리밍 비활성화 - 시작 버튼을 눌러주세요")
                    self.update_status("robot_location", "대기 중")
                    return
                
                # 메시지에서 상태와 위치 분리
                if "상태:" in message and "위치:" in message:
                    location_raw = message.split("위치:")[1].split(",")[0].strip()
                    status = message.split("상태:")[1].strip()
                    
                    # 각 상태별 업데이트 메서드 호출
                    self.update_status("robot_location", location_raw)
                    self.update_status("robot_status", status)
                    
            elif status_type == "detections":
                # 시스템이 준비되지 않은 경우 (첫 Start 버튼을 누르기 전)
                if not self.system_ready:
                    self.detections_label.setText("탐지 상태: 시스템을 시작하면 탐지 결과가 표시됩니다")
                # 스트리밍 화면이 비활성화된 경우
                elif not self.streaming:
                    self.detections_label.setText("탐지 상태: 스트리밍을 시작하면 탐지 결과가 표시됩니다")
                # 정상 동작 (시스템 활성화 + 스트리밍 활성화)
                else:
                    # 탐지 메시지에 접두사 추가
                    formatted_msg = f"탐지 상태:\n{message}"
                    self.detections_label.setText(formatted_msg)
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
        
        # 디버깅용 - 5초 후 응답이 없으면 자동으로 다음 단계로 진행 (필요시 주석 해제)
        # QTimer.singleShot(5000, self._check_server_response_timeout)
    
    def _check_server_response_timeout(self):
        """서버 응답 타임아웃 체크 - 테스트용"""
        if self.waiting_server_confirm:
            if DEBUG:
                print("서버 응답 타임아웃 - 자동으로 다음 단계 진행")
            self.complete_movement_to_target()

    def server_confirmed_location(self, confirmed_location):
        """서버로부터 위치 확인을 받았을 때 호출"""
        if not self.waiting_server_confirm:
            # 서버 확인을 기다리는 중이 아니면 무시
            if DEBUG:
                print(f"서버 확인 대기 중이 아님, 위치 무시: {confirmed_location}")
            return
        
        # "A", "B", "BASE" 같은 실제 위치가 오면 최종 목적지로 이동
        if confirmed_location == self.target_location:
            # 목적지에 도착한 경우
            if DEBUG:
                print(f"목적지({confirmed_location})에 도착, complete_movement_to_target 호출")
            self.complete_movement_to_target()
        elif "이동 중" in confirmed_location:
            # "A 지역으로 이동 중" 같은 메시지는 계속 대기
            if DEBUG:
                print(f"이동 중 확인: {confirmed_location}, 계속 대기")
        else:
            # 기대하지 않은 위치가 왔을 때
            if DEBUG:
                print(f"위치 불일치: 예상={self.target_location}, 실제={confirmed_location}")
            
    def complete_movement_to_target(self):
        """최종 목적지로 이동"""
        if DEBUG:
            print(f"최종 목적지로 이동 시작: {self.target_location}")
            
        self.waiting_server_confirm = False
        target_pos = self.LOCATIONS[self.target_location]
        
        # 최종 목적지로 이동 시작
        self.robot_animation.setStartValue(self.robot_label.pos())
        self.robot_animation.setEndValue(QPoint(target_pos.x() - 15, target_pos.y() - 15))
        self.robot_animation.setDuration(1000)
        
        # 이전 연결 해제 및 새 연결 설정
        if self.robot_animation.receivers(self.robot_animation.finished) > 0:
            self.robot_animation.finished.disconnect()
        self.robot_animation.finished.connect(self._movement_complete_callback)
        
        # 애니메이션 시작
        self.robot_animation.start()
        
    def parse_location(self, location_str):
        """
        위치 문자열 파싱
        'A', 'B', 'BASE' 또는 'A 지역으로 이동 중', 'B 지역으로 이동 중' 등 모두 처리
        
        Returns:
            tuple: (실제 위치(A/B/BASE), 이동중 여부, 목적지)
        """
        is_moving = "이동 중" in location_str
        actual_location = None
        destination = None
        
        # 이동 중인 경우 ('A 지역으로 이동 중', 'B 지역으로 이동 중', 'BASE 지역으로 이동 중')
        if is_moving:
            # 목적지 추출 (예: "A 지역으로 이동 중" -> 목적지 "A")
            for loc in self.LOCATIONS:
                if location_str.startswith(loc):
                    destination = loc
                    break
            
            # 현재 위치는 현재 self.current_location 유지 (이동 중에는 변경 안함)
            actual_location = self.current_location
        else:
            # 정지 상태면 위치는 그대로 (예: "A", "B", "BASE")
            for loc in self.LOCATIONS:
                if location_str == loc:
                    actual_location = loc
                    break
        
        if DEBUG:
            if is_moving:
                print(f"위치 파싱: '{location_str}' -> 현재 위치: {actual_location}, 이동 중: {is_moving}, 목적지: {destination}")
            else:
                print(f"위치 파싱: '{location_str}' -> 현재 위치: {actual_location}")
                
        return actual_location, is_moving, destination

    def set_response_buttons_enabled(self, enabled=False):
        """탐지 응답 명령 버튼들의 활성화 상태 설정
        
        Args:
            enabled (bool): True면 활성화, False면 비활성화
        """
        try:
            # 모든 응답 버튼에 상태 적용
            self.btn_fire_report.setEnabled(enabled)
            self.btn_police_report.setEnabled(enabled)
            self.btn_illegal_warning.setEnabled(enabled)
            self.btn_danger_warning.setEnabled(enabled)
            self.btn_emergency_warning.setEnabled(enabled)
            self.btn_case_closed.setEnabled(enabled)
            
            if DEBUG:
                print(f"응답 버튼 상태 변경: {'활성화' if enabled else '비활성화'}")
                
        except Exception as e:
            if DEBUG:
                print(f"응답 버튼 상태 변경 실패: {e}")
                import traceback
                print(traceback.format_exc())

    def handle_case_closed(self):
        """CASE_CLOSED 버튼 클릭 처리: 명령 전송 후 버튼 비활성화"""
        # CASE_CLOSED 명령 전송
        self.robot_command.emit("CASE_CLOSED")
        
        # 버튼 비활성화
        self.set_response_buttons_enabled(False)
        
        if DEBUG:
            print("사건 종료 처리: 명령 버튼 비활성화 완료")

