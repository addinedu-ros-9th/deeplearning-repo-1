# gui/tabs/monitoring_tab.py

import os
import datetime
from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QSizePolicy, QMessageBox
)
from PyQt5.QtCore import (
    Qt, QPropertyAnimation, QPoint,
    QEasingCurve, QTimer, pyqtSignal, QSize, QVariantAnimation
)
from PyQt5.QtGui import QPixmap, QColor, QIcon, QTransform, QIcon
from PyQt5.uic import loadUi
from datetime import datetime, timezone, timedelta
import math

# 한국 시간대(타임존) 설정
# 한국 표준시(KST)는 UTC+9 입니다
KOREA_TIMEZONE = timezone(timedelta(hours=9))  # UTC+9 (한국 표준시, KST)


# 디버그 모드 설정
DEBUG = True

# UI 파일 경로
MONITORING_TAP_UI_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ui', 'monitoring_tab8.ui')
MONITORING_TAP_MAP_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ui', 'neighbot_new_map.png')

# MonitoringTab: Main Monitoring 탭의 UI 로드만 담당
class MonitoringTab(QWidget):
    # 시그널 정의
    robot_command = pyqtSignal(str)      # 로봇 명령 시그널
    stream_command = pyqtSignal(bool)    # 스트리밍 제어 시그널
    connection_error = pyqtSignal(str)   # 연결 에러 시그널
    
    # 지역 좌표 정의 (맵 상의 픽셀 좌표)
    LOCATIONS = {
        'BASE': QPoint(230, 250),        # 기지 위치
        'A': QPoint(200, 105),           # A 구역 위치
        'B': QPoint(350, 150),           # B 구역 위치
        'BASE_A_MID': QPoint(215, 177),  # BASE-A 중간지점 (BASE와 A의 중간)
        'BASE_B_MID': QPoint(290, 200),  # BASE-B 중간지점 (BASE와 B의 중간)
        'A_B_MID': QPoint(275, 127)      # A-B 중간지점 (A와 B의 중간)
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
        self.current_location = 'BASE'              # 현재 위치
        self.target_location = None                 # 목표 위치
        self.current_status = 'idle'                # 현재 상태
        self.is_moving = False                      # 이동 중 여부
        self.waiting_server_confirm = False         # 서버 확인 대기 중 여부
        self.user_name = user_name or "unknown"     # 사용자 이름 (기본값 설정)
        self.streaming = False                      # 스트리밍 표시 여부 (화면에 보여주는지)
        self.feedback_timer = QTimer()              # 피드백 메시지용 타이머
        self.feedback_timer.timeout.connect(self.clear_feedback_message)
        self.original_detections_text = ""          # 원래 탐지 라벨 텍스트 저장용
        self.command_buttons_state = None           # 현재 활성화된 명령 버튼 상태
        
        # 순찰 애니메이션 관련 변수
        self.patrol_timer = QTimer(self)            # 순찰 애니메이션용 타이머
        self.patrol_timer.timeout.connect(self.update_patrol_animation)
        self.patrol_center = None                   # 순찰 중심점
        self.patrol_radius = 60                     # 기본 순찰 반경 (픽셀)
        self.patrol_angle = 0                       # 현재 순찰 각도
        self.patrol_speed = 5                       # 초당 회전 각도 (도) (5도/초로 변경)
        self.is_patrolling = False                  # 순찰 중 여부
        self.arrival_animation = None               # 도착 애니메이션
        
        # 구역별 순찰 설정
        self.PATROL_CONFIG = {
            'A': {
                'radius': 60,       # A 구역 순찰 반경
                'start_angle': 135, # A 구역 순찰 시작 각도 (7시 30분 방향)
                'speed': 5          # A 구역 순찰 속도 (도/초)
            },
            'B': {
                'radius': 30,       # B 구역 순찰 반경
                'start_angle': 0,   # B 구역 순찰 시작 각도 (3시 방향)
                'speed': 5          # B 구역 순찰 속도 (도/초)
            },
            # 필요시 다른 구역에 대한 순찰 설정 추가 가능
        }
        
        # 녹화중 표시를 위한 설정
        self.recording_indicator = None             # 녹화중 표시 위젯 참조
        self.recording_blink_timer = QTimer(self)   # 녹화중 깜빡임 타이머
        self.recording_blink_timer.timeout.connect(self.blink_recording_indicator)
        self.recording_visible = False              # 깜빡임 상태 추적
        
        self.init_ui()
        self.init_map()
        self.init_robot()
        
        # 상태별 메시지 정의
        self.STATUS_MESSAGES = {
            'idle': '대기 중', 
            'moving': '이동 중',
            'patrolling': '순찰 중'
        }
        
        # 초기 상태 설정
        self.robot_status_label.setText("로봇 상태: 순찰 중")
        self.enable_movement_buttons()

    def init_ui(self):
        """UI 초기화"""
        try:
            # UI 파일 로드
            loadUi(MONITORING_TAP_UI_FILE, self)
            
            # 전역 툴팁 스타일 설정 - 모든 위젯에 적용되도록 앱 전체에 설정
            from PyQt5.QtWidgets import QApplication
            QApplication.instance().setStyleSheet("""
                QToolTip {
                    background-color: #fff9dc;        /* 연노랑 배경 */
                    color: #222222;                   /* 어두운 텍스트 */
                    border: 1px solid #aaa27c;        /* 어두운 회갈색 테두리 */
                    border-radius: 4px;
                    padding: 4px;
                    font-size: 12px;
                }
            """)


            if DEBUG:
                print("MonitoringTab UI 로드 완료")
            
            # 사용자 이름 표시 라벨 설정
            self.label_user_name = self.findChild(QLabel, "label_user_name")
            if self.label_user_name:
                self.label_user_name.setText(f"사용자: {self.user_name}")                
                self.label_user_name.setStyleSheet("font-weight: bold; font-size: 12pt;") # 폰트 사이즈 키우고 볼드체로 설정
                if DEBUG:
                    print(f"사용자 이름 설정됨: {self.user_name}")
            else:
                if DEBUG:
                    print("label_user_name을 찾을 수 없음")
            
            # 비디오 스트림 버튼 연결
            self.btn_start_video_stream.clicked.connect(self.start_stream)
            
            # 명령 버튼 연결 (이름 변경: warning 없이 간단한 이름으로)
            self.btn_danger = self.findChild(QPushButton, "btn_danger")
            self.btn_emergency = self.findChild(QPushButton, "btn_emergency")
            self.btn_illegal = self.findChild(QPushButton, "btn_illegal")
            self.btn_119_report = self.findChild(QPushButton, "btn_fire_report")
            self.btn_112_report = self.findChild(QPushButton, "btn_police_report")
            self.btn_case_closed = self.findChild(QPushButton, "btn_case_closed")
            
            # 버튼 이벤트 핸들러 연결
            self.btn_danger.clicked.connect(lambda: self.handle_command_button("DANGER_WARNING"))
            self.btn_emergency.clicked.connect(lambda: self.handle_command_button("EMERGENCY_WARNING"))
            self.btn_illegal.clicked.connect(lambda: self.handle_command_button("ILLEGAL_WARNING"))
            self.btn_119_report.clicked.connect(lambda: self.handle_command_button("FIRE_REPORT"))
            self.btn_112_report.clicked.connect(lambda: self.handle_command_button("POLICE_REPORT"))
            self.btn_case_closed.clicked.connect(self.handle_case_closed)
                
            # 로그 메시지 영역 초기화
            if hasattr(self, 'textEdit_log_box'):
                self.textEdit_log_box.clear()
                self.append_log("모니터링 시스템 초기화 완료")
            else:
                if DEBUG:
                    print("경고: label_user_name을 찾을 수 없습니다.")

            # 상태 표시 라벨 찾기
            self.live_feed_label = self.findChild(QLabel, "live_feed_label")   # 스트리밍 영상 표시
            self.detection_image = self.findChild(QLabel, "detection_image")   # 맵 이미지 표시
            self.robot_status_label = self.findChild(QLabel, "robot_status")
            self.robot_location_label = self.findChild(QLabel, "robot_location")
            self.detections_label = self.findChild(QLabel, "detections")
            
            # 상태 라벨 초기화 (접두사 추가)
            self.robot_status_label.setText("로봇 상태: 대기 중")
            self.robot_location_label.setText("로봇 위치: BASE")
            self.detections_label.setText("탐지 상태: 탐지 준비 완료")
            
            # 스트리밍 버튼 초기 텍스트 설정
            self.btn_start_video_stream.setText("Start Video Stream")
            
            if DEBUG:
                print("UI 요소 초기화 완료:")
                print(f"  - live_feed_label: {self.live_feed_label is not None}")
                print(f"  - detection_image: {self.detection_image is not None}")
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
            # 맵 표시 레이블 가져오기
            self.map_display_label = self.findChild(QLabel, "map_display_label")
            if not self.map_display_label:
                if DEBUG:
                    print("map_display_label을 찾을 수 없음")
                return
                
            # 맵 이미지 로드 및 설정
            self.map_pixmap = QPixmap(MONITORING_TAP_MAP_FILE)
            self.map_display_label.setPixmap(self.map_pixmap)
            self.map_display_label.setScaledContents(True)
            
            # 지도 위에 위치 버튼 추가 (A, B, BASE)
            self.setup_map_buttons()
            
            # 아이콘 (전원, 배터리, 와이파이, 카메라) 추가
            self.setup_icons()
            
            if DEBUG:
                print("맵 초기화 완료")
                
        except Exception as e:
            if DEBUG:
                print(f"맵 초기화 오류: {e}")
            
    def setup_map_buttons(self):
        """지도 위에 A, B, BASE 위치 버튼 추가"""
        try:
            # 버튼 크기 설정
            ICON_SIZE = 40         # A, B 위치 버튼 아이콘 크기
            ICON_BASE_SIZE = 60    # BASE 버튼 아이콘 크기
            BUTTON_SIZE = 120       # 실제 버튼 클릭 영역 (공통)

            # 공통 스타일 (hover 회색)
            COMMON_BUTTON_STYLE = """
                QPushButton {
                    background: transparent;
                    border: none;
                }
                QPushButton:hover:enabled {
                    background-color: rgba(128, 128, 128, 120);  /* 회색 hover */
                    border-radius: 30px;
                    box-shadow: 0 0 10px rgba(0, 0, 0, 50);
                }
            """

            # A 위치 버튼
            self.btn_a_location = QPushButton(self.map_display_label)
            self.btn_a_location.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
            a_icon = QPixmap("./gui/ui/a.png")
            self.btn_a_location.setIcon(QIcon(a_icon))
            self.btn_a_location.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
            self.btn_a_location.setStyleSheet(COMMON_BUTTON_STYLE)
            self.btn_a_location.move(self.LOCATIONS['A'].x() - BUTTON_SIZE // 2, self.LOCATIONS['A'].y() - BUTTON_SIZE // 2)
            self.btn_a_location.setEnabled(True)
            self.btn_a_location.clicked.connect(self.send_move_to_a_command)
            self.btn_a_location.setToolTip("<b>A 구역으로 이동</b><br>로봇을 A 구역으로 이동시킵니다.<br>클릭하면 로봇이 즉시 이동을 시작합니다.")

            # B 위치 버튼
            self.btn_b_location = QPushButton(self.map_display_label)
            self.btn_b_location.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
            b_icon = QPixmap("./gui/ui/b.png")
            self.btn_b_location.setIcon(QIcon(b_icon))
            self.btn_b_location.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
            self.btn_b_location.setStyleSheet(COMMON_BUTTON_STYLE)
            self.btn_b_location.move(self.LOCATIONS['B'].x() - BUTTON_SIZE // 2, self.LOCATIONS['B'].y() - BUTTON_SIZE // 2)
            self.btn_b_location.setEnabled(True)
            self.btn_b_location.clicked.connect(self.send_move_to_b_command)
            self.btn_b_location.setToolTip("<b>B 구역으로 이동</b><br>로봇을 B 구역으로 이동시킵니다.<br>클릭하면 로봇이 즉시 이동을 시작합니다.")

            # BASE 위치 버튼
            self.btn_base_location = QPushButton(self.map_display_label)
            self.btn_base_location.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
            base_icon = QPixmap("./gui/ui/base.png")
            self.btn_base_location.setIcon(QIcon(base_icon))
            self.btn_base_location.setIconSize(QSize(ICON_BASE_SIZE, ICON_BASE_SIZE))
            self.btn_base_location.setStyleSheet(COMMON_BUTTON_STYLE)
            self.btn_base_location.move(self.LOCATIONS['BASE'].x() - BUTTON_SIZE // 2, self.LOCATIONS['BASE'].y() - BUTTON_SIZE // 2)
            self.btn_base_location.setEnabled(False)  # 초기에는 비활성화
            self.btn_base_location.clicked.connect(self.send_return_to_base_command)
            self.btn_base_location.setToolTip("<b>기지로 이동</b><br>로봇을 기지(BASE)로 복귀시킵니다.<br>클릭하면 로봇이 즉시 기지로 돌아갑니다.")

            # 초기에 응답 버튼 비활성화 (탐지 팝업에서 "진행"을 선택해야 활성화됨)
            self.set_response_buttons_enabled(False)

            if DEBUG:
                print("맵 버튼 설정 완료")
                
        except Exception as e:
            if DEBUG:
                print(f"맵 버튼 설정 오류: {e}")
    
    def setup_icons(self):
        """지도 위에 고정 아이콘(전원, 배터리, 와이파이) 추가"""
        try:
            # 아이콘 위치 설정을 위한 기본 오프셋
            ICON_SIZE = 24
            ICON_MARGIN = 5
            TOP_OFFSET = 5
            RIGHT_MARGIN = 5
            LABEL_WIDTH = 410

            current_x = LABEL_WIDTH - ICON_SIZE - RIGHT_MARGIN

            def create_icon(parent, image_path, tooltip, x, y):
                label = QLabel(parent)
                label.setFixedSize(ICON_SIZE, ICON_SIZE)
                label.setPixmap(QPixmap(image_path))
                label.setScaledContents(True)
                label.move(x, y)
                label.setToolTip(tooltip)
                # 배경 투명 처리
                label.setStyleSheet("background-color: transparent;")
                return label

            # 배터리 아이콘
            self.battery_icon = create_icon(
                self.map_display_label,
                "./gui/ui/battery.png",
                "<b>배터리 상태(업데이트 예정)</b><br>로봇의 현재 배터리 상태를 표시합니다.",
                current_x,
                TOP_OFFSET
            )
            current_x -= (ICON_SIZE + ICON_MARGIN)

            # 와이파이 아이콘
            self.wifi_icon = create_icon(
                self.map_display_label,
                "./gui/ui/wifi.png",
                "<b>네트워크 연결 상태(업데이트 예정)</b><br>로봇과의 무선 통신 상태를 표시합니다.",
                current_x,
                TOP_OFFSET
            )
            current_x -= (ICON_SIZE + ICON_MARGIN)

            # 전원 아이콘
            self.power_icon = create_icon(
                self.map_display_label,
                "./gui/ui/power.png",
                "<b>전원 상태(업데이트 예정)</b><br>로봇의 전원 상태를 표시합니다.",
                current_x,
                TOP_OFFSET
            )
            current_x -= (ICON_SIZE + ICON_MARGIN)

            # 카메라 아이콘
            self.camera_icon = create_icon(
                self.map_display_label,
                "./gui/ui/camera_off.png",
                "<b>카메라 스트리밍 상태</b><br>활성화 시 실시간 영상을 수신 중임을 표시합니다.",
                current_x,
                TOP_OFFSET
            )

            if DEBUG:
                print("아이콘 설정 완료")

        except Exception as e:
            if DEBUG:
                print(f"아이콘 설정 오류: {e}")
    
    def update_camera_icon(self, active):
        """카메라 아이콘 상태 업데이트"""
        try:
            icon_path = "./gui/ui/camera.png" if active else "./gui/ui/camera_off.png"
            pixmap = QPixmap(icon_path)
            self.camera_icon.setPixmap(pixmap)
            self.camera_icon.setScaledContents(True)
            
        except Exception as e:
            if DEBUG:
                print(f"카메라 아이콘 업데이트 오류: {e}")
    
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
            robot_pixmap = QPixmap('./gui/ui/neighbot_2.png')  # 이미지 변경
            scaled_robot = robot_pixmap.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.robot_label.setPixmap(scaled_robot)
            self.robot_label.setParent(self.map_display_label)
            self.robot_label.setToolTip("<b>NeighBot</b><br>현재 로봇의 위치를 표시합니다.")
            self.robot_label.setStyleSheet("background-color: transparent;")            
            
            # 애니메이션 객체 생성
            self.robot_animation = QPropertyAnimation(self.robot_label, b"pos")
            self.robot_animation.setEasingCurve(QEasingCurve.InOutQuad)
            self.robot_animation.setDuration(1000)  # 1초 동안 이동
            
            # 로봇 초기 위치 설정
            self.move_robot_instantly('BASE')
            
            # 경로 표시 라벨 초기화
            self.path_line = None
            
            if DEBUG:
                print("로봇 초기화 완료")
                
        except Exception as e:
            if DEBUG:
                print(f"로봇 초기화 오류: {e}")

    def move_robot_instantly(self, location):
        """로봇을 즉시 해당 위치로 이동"""
        if location in self.LOCATIONS:
            # 현재 순찰 중이면 순찰 애니메이션 중지
            if self.is_patrolling:
                self.stop_patrol_animation()
                
            pos = self.LOCATIONS[location]
            self.robot_label.move(pos.x() - 15, pos.y() - 15)  # 중앙 정렬을 위해 크기의 절반만큼 조정
            self.current_location = location
            
            # 경로선 제거
            if hasattr(self, 'path_line') and self.path_line:
                self.path_line.setParent(None)
                self.path_line = None
                
            # BASE가 아닌 위치로 즉시 이동한 경우 
            # 도착 애니메이션 없이 바로 순찰 애니메이션 시작
            if location != 'BASE':
                self.start_patrol_animation()
            else:
                # BASE 위치에서는 상태 업데이트
                self.update_robot_status('idle')

    def animate_robot_movement(self, target_location):
        """이동 명령 시 중간 지점으로 먼저 이동"""
        import math
        
        if target_location not in ['A', 'B', 'BASE'] or self.is_moving:
            if DEBUG:
                print(f"이동 불가: 목적지={target_location}, 이동 중={self.is_moving}")
            return
        
        # 현재 순찰 중이면 순찰 애니메이션 중지
        if self.is_patrolling:
            self.stop_patrol_animation()
            if DEBUG:
                print(f"새 이동 명령으로 인해 순찰 애니메이션 정지")
            
        self.is_moving = True
        self.target_location = target_location
        self.disable_movement_buttons()
        
        # 로그 추가
        self.append_log(f"{self.current_location}에서 {target_location}(으)로 이동 시작")
        
        # 경로에 따른 중간지점 찾기
        path_key = (self.current_location, target_location)
        mid_point = self.PATH_MIDPOINTS.get(path_key)
        
        if not mid_point:
            if DEBUG:
                print(f"올바르지 않은 경로: {path_key}")
            self.is_moving = False
            self.enable_movement_buttons()
            return
            
        # 중간 지점으로 이동
        start_pos = self.robot_label.pos()
        mid_pos = self.LOCATIONS[mid_point]
        
        # 이동 애니메이션 설정
        self.robot_animation.setStartValue(start_pos)
        self.robot_animation.setEndValue(QPoint(mid_pos.x() - 15, mid_pos.y() - 15))
        
        # 이전 연결 해제
        try:
            self.robot_animation.finished.disconnect()
        except:
            pass
            
        # 중간 지점 도착 후 경로선 표시 및 서버 응답 대기
        self.robot_animation.finished.connect(lambda: self.midpoint_reached_with_path(mid_point, target_location))
        
        # 애니메이션 시작
        self.robot_animation.start()

    def draw_path_line(self, from_point, to_point):
        """두 지점 사이에 점선 경로 표시
        개선: 
        1. 점선을 가로로 회전(90도)
        2. 선의 두께를 10-15px로 키워서 더 잘 보이게 함
        3. 경로의 정확한 길이에 맞게 조정
        """
        import math
        
        try:
            # 기존 경로선 제거
            if hasattr(self, 'path_line') and self.path_line:
                self.path_line.setParent(None)
                self.path_line = None
                
            # 선 시작점과 끝점
            start_pos = self.LOCATIONS[from_point]
            end_pos = self.LOCATIONS[to_point]
            
            # 경로선 길이와 각도 계산
            dx = end_pos.x() - start_pos.x()
            dy = end_pos.y() - start_pos.y()
            line_length = math.sqrt(dx*dx + dy*dy)
            angle = math.degrees(math.atan2(dy, dx))
            
            # 점선 이미지 로드 
            dotted_line = QPixmap("./gui/ui/dotted_barline.png")
            
            # 먼저 90도 회전시켜 수평으로 만들기 (이미지가 세로 방향이므로 가로로 변환)
            transform_horizontal = QTransform().rotate(90)
            horizontal_line = dotted_line.transformed(transform_horizontal, Qt.SmoothTransformation)
            
            # 이제 수평 이미지를 경로 길이에 맞게 스케일링하고 두께를 12px로 설정
            PATH_LINE_HEIGHT = 12  # 경로선 두께 증가 (기존 3px -> 12px)
            scaled_horizontal_line = horizontal_line.scaled(
                int(line_length), 
                PATH_LINE_HEIGHT, 
                Qt.IgnoreAspectRatio,  # 가로/세로 비율 무시하고 정확한 크기로 조정
                Qt.SmoothTransformation
            )
            
            # 경로 각도에 맞게 회전
            transform_angle = QTransform().rotate(angle)
            rotated_line = scaled_horizontal_line.transformed(transform_angle, Qt.SmoothTransformation)
            
            # 경로선 라벨 생성
            self.path_line = QLabel(self.map_display_label)
            self.path_line.setPixmap(rotated_line)
            self.path_line.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.path_line.setStyleSheet("background-color: transparent;")  # 배경 투명 설정
            self.path_line.setToolTip(f"<b>이동 경로</b><br>{from_point}에서 {to_point}까지의 이동 경로입니다.")
            self.path_line.show()
            
            # 경로선 위치 조정 (회전 후 크기와 위치 보정)
            line_width = rotated_line.width()
            line_height = rotated_line.height()
            
            # 위치 계산 - 시작점에서 선의 중앙이 경로 중앙에 오도록 조정
            pos_x = start_pos.x() - line_width/2 + dx/2
            pos_y = start_pos.y() - line_height/2 + dy/2
            
            # 최종 위치 설정
            self.path_line.setGeometry(int(pos_x), int(pos_y), line_width, line_height)
            
            # 서버 응답을 기다리는 방식으로 변경되어 여기서는 complete_movement_to_target을 호출하지 않음
            # 대신 server_confirmed_location 함수에서 응답을 받으면 호출함
            
            if DEBUG:
                print(f"경로선 그리기 완료: 길이={line_length:.1f}px, 각도={angle:.1f}°, 두께={PATH_LINE_HEIGHT}px")
            
        except Exception as e:
            if DEBUG:
                print(f"경로선 그리기 오류: {e}")
            # 에러 발생시에도 서버 응답 대기는 유지하고, 경로선만 표시 못함

    def complete_movement_to_target(self):
        """최종 목적지로 로봇 이동"""
        try:
            if not self.target_location:
                return
            
            if DEBUG:
                print(f"최종 목적지로 이동 시작: {self.target_location}")
                
            # 현재 위치
            current_pos = self.robot_label.pos()
            # 최종 목적지
            target_pos = self.LOCATIONS[self.target_location]
            target_pos = QPoint(target_pos.x() - 15, target_pos.y() - 15)
            
            # 애니메이션 설정
            try:
                self.robot_animation.finished.disconnect()  # 이전 연결 해제
            except:
                # 연결이 없을 경우 무시
                pass
                
            self.robot_animation.setStartValue(current_pos)
            self.robot_animation.setEndValue(target_pos)
            self.robot_animation.setEasingCurve(QEasingCurve.InOutQuad)  # 부드러운 이동을 위한 곡선
            
            # 애니메이션 완료 핸들러 연결
            self.robot_animation.finished.connect(self._movement_complete_callback)
            
            # 애니메이션 시작
            self.robot_animation.start()
            
            if DEBUG:
                print(f"최종 이동 애니메이션 시작: {current_pos} -> {target_pos}")
            
        except Exception as e:
            if DEBUG:
                print(f"목적지 이동 오류: {e}")
                import traceback
                print(traceback.format_exc())
            # 에러 발생 시 직접 콜백 호출하여 이동 완료 처리
            self._movement_complete_callback()

    def movement_finished(self):
        """이동 애니메이션 완료 처리
        
        이 함수는 초기 구현에서 사용되었으나, 현재는 _movement_complete_callback으로 대체됨
        호환성을 위해 유지하며, _movement_complete_callback을 호출함
        """
        if DEBUG:
            print(f"movement_finished 호출됨 -> _movement_complete_callback으로 리다이렉트")
        
        self._movement_complete_callback()

    def disable_movement_buttons(self):
        """이동 버튼 비활성화"""
        self.btn_a_location.setEnabled(False)
        self.btn_b_location.setEnabled(False)
        self.btn_base_location.setEnabled(False)
        
        # 비활성화 상태에서도 시각적 피드백을 제공하도록 스타일 추가
        disabled_style = """
            QPushButton {
                background: transparent; 
                border: none;
                opacity: 0.7;
            }
            QPushButton:disabled {
                opacity: 0.5;
            }
        """
        
        self.btn_a_location.setStyleSheet(disabled_style)
        self.btn_b_location.setStyleSheet(disabled_style)
        self.btn_base_location.setStyleSheet(disabled_style)

    def enable_movement_buttons(self):
        """현재 위치에 따라 이동 버튼 활성화 및 스타일 복원
        - BASE 위치: A, B 버튼만 활성화
        - A 위치: B, BASE 버튼만 활성화
        - B 위치: A, BASE 버튼만 활성화
        """
        # 활성화 상태일 때 적용할 기본 스타일 (호버 효과 포함)
        hover_style_a_b = """
            QPushButton {
                background: transparent; 
                border: none;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 120);
                border-radius: 20px;
                box-shadow: 0 0 10px rgba(0, 0, 0, 50);
            }
        """
        
        hover_style_base = """
            QPushButton {
                background: transparent; 
                border: none;
            }
            QPushButton:hover:enabled {
                background-color: rgba(255, 255, 255, 120);
                border-radius: 30px;
                box-shadow: 0 0 10px rgba(0, 0, 0, 50);
            }
        """
        
        # 비활성화 상태일 때 적용할 스타일
        disabled_style = """
            QPushButton {
                background: transparent; 
                border: none;
                opacity: 0.5;
            }
        """
        
        # 현재 위치에 따라 버튼 활성화 및 스타일 설정
        if self.current_location == 'BASE':
            # A, B 버튼은 활성화
            self.btn_a_location.setEnabled(True)
            self.btn_a_location.setStyleSheet(hover_style_a_b)
            
            self.btn_b_location.setEnabled(True)
            self.btn_b_location.setStyleSheet(hover_style_a_b)
            
            # BASE 버튼은 비활성화 (현재 위치이므로)
            self.btn_base_location.setEnabled(False)
            self.btn_base_location.setStyleSheet(disabled_style)
            
            if DEBUG:
                print("BASE 위치: A, B 버튼 활성화")
                
        elif self.current_location == 'A':
            # A 버튼 비활성화 (현재 위치이므로)
            self.btn_a_location.setEnabled(False)
            self.btn_a_location.setStyleSheet(disabled_style)
            
            # B, BASE 버튼 활성화
            self.btn_b_location.setEnabled(True)
            self.btn_b_location.setStyleSheet(hover_style_a_b)
            
            self.btn_base_location.setEnabled(True)
            self.btn_base_location.setStyleSheet(hover_style_base)
            
            if DEBUG:
                print("A 위치: B, BASE 버튼 활성화")
                
        elif self.current_location == 'B':
            # A, BASE 버튼 활성화
            self.btn_a_location.setEnabled(True)
            self.btn_a_location.setStyleSheet(hover_style_a_b)
            
            # B 버튼 비활성화 (현재 위치이므로)
            self.btn_b_location.setEnabled(False)
            self.btn_b_location.setStyleSheet(disabled_style)
            
            self.btn_base_location.setEnabled(True)
            self.btn_base_location.setStyleSheet(hover_style_base)
            
            if DEBUG:
                print("B 위치: A, BASE 버튼 활성화")

    def update_robot_status(self, status: str):
        """로봇 상태 업데이트"""
        if self.current_status != status:
            # 이전 상태가 patrolling이고 새 상태가 다르면 순찰 중단
            if self.current_status == 'patrolling' and status != 'patrolling':
                self.stop_patrol_animation()
            
            self.current_status = status
            message = self.STATUS_MESSAGES.get(status, status)
            
            if DEBUG:
                print(f"로봇 상태 변경: {status} ({message})")
            
            # 상태에 따른 UI 업데이트
            if status == 'moving':
                # moving 상태일 때는 모든 이동 버튼 비활성화
                self.disable_movement_buttons()
                # 이동 중에는 순찰 애니메이션 중지
                self.stop_patrol_animation()
                if DEBUG:
                    print("로봇 이동 중: 모든 이동 버튼 비활성화")
            elif status == 'patrolling':
                # 순찰 중일 때는 현재 위치에 따라 버튼 활성화
                self.enable_movement_buttons()
                # 상태 텍스트 업데이트
                self.robot_status_label.setText(f"로봇 상태: 순찰 중 ({self.current_location} 구역)")
                if DEBUG:
                    print(f"로봇 {status}: 이동 버튼 활성화 (현재 위치: {self.current_location})")
            elif status == 'idle':
                # 대기 중일 때는 현재 위치에 따라 버튼 활성화
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
            # 로그 추가
            self.append_log(f"A 구역으로 이동 명령을 전송했습니다.")
            if DEBUG:
                print("A 지역 이동 명령 전송 완료")

    def send_move_to_b_command(self):
        """B 지역으로 이동 명령을 전송"""
        if self.current_location != 'B' and not self.is_moving:
            if DEBUG:
                print(f"B 지역 이동 명령 전송 시도 (현재 위치: {self.current_location})")
            self.robot_command.emit("MOVE_TO_B")
            self.animate_robot_movement('B')
            # 로그 추가
            self.append_log(f"B 구역으로 이동 명령을 전송했습니다.")
            if DEBUG:
                print("B 지역 이동 명령 전송 완료")

    def send_return_to_base_command(self):
        """기지로 복귀 명령을 전송"""
        if self.current_location != 'BASE' and not self.is_moving:
            if DEBUG:
                print(f"BASE로 이동 명령 전송 시도 (현재 위치: {self.current_location})")
            self.robot_command.emit("RETURN_TO_BASE")
            self.animate_robot_movement('BASE')
            # 로그 추가
            self.append_log("기지로 복귀 명령을 전송했습니다.")
            if DEBUG:
                print("BASE 이동 명령 전송 완료")
                print(f"기지 복귀 명령 전송")

    def start_stream(self):
        """영상 스트리밍 표시를 토글합니다 (화면 표시만 제어)
        
        중요: 비디오 스트림은 이동 버튼과 완전히 독립적으로 동작합니다.
        비디오를 중지하거나 시작해도 이동 버튼 상태에는 영향을 주지 않습니다.
        """
        try:
            # 스트리밍 토글 (화면에 보여주는지 여부만 제어)
            self.streaming = not self.streaming
            
            # 카메라 아이콘 상태 업데이트
            self.update_camera_icon(self.streaming)
            
            # 로그 추가
            status = "시작" if self.streaming else "중지"
            self.append_log(f"비디오 스트림 {status}")
            
            if self.streaming:
                # 영상 표시 활성화
                self.btn_start_video_stream.setText("Stop Video Stream")
                self.live_feed_label.setText("비디오 상태: 스트리밍 활성화됨")
                
                if DEBUG:
                    print("비디오 스트림 표시 활성화 (이동 버튼 상태는 변경하지 않음)")
            else:
                # 영상 표시 비활성화 (백그라운드 수신은 계속)
                self.btn_start_video_stream.setText("Start Video Stream")
                self.live_feed_label.setText("비디오 상태: 스트리밍 비활성화 - 시작 버튼을 눌러주세요")
                
                if DEBUG:
                    print("비디오 스트림 표시 중지 (이동 버튼 상태는 변경하지 않음)")
            
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
            
            # 이미지 수신 시간 기록 (한국 표준시, KST - MySQL DATETIME 형식)
            current_time_dt = datetime.now(KOREA_TIMEZONE)
            current_time = current_time_dt.strftime('%Y-%m-%d %H:%M:%S.') + f"{current_time_dt.microsecond // 1000:03d}"
            if DEBUG:
                print(f"[이미지 수신] 카메라 처리 완료 후 디스플레이 시간 => {current_time} (KST)")

        except Exception as e:
            if DEBUG:
                print(f"카메라 피드 업데이트 실패: {e}")
                import traceback
                print(traceback.format_exc())
                
    def update_detection_image(self, image_data: bytes):
        """탐지 이미지를 업데이트
        
        Args:
            image_data (bytes): 이미지 바이너리 데이터
        """
        try:
            # 이미지 수신 시간 기록 (한국 표준시, KST - MySQL DATETIME 형식)
            current_time_dt = datetime.now(KOREA_TIMEZONE)
            current_time = current_time_dt.strftime('%Y-%m-%d %H:%M:%S')
            if DEBUG:
                print(f"[이미지 수신] 탐지 이미지 {current_time} (KST)")
                
            if not image_data:
                if DEBUG:
                    print("탐지 이미지 업데이트 실패: 이미지 데이터 없음")
                return
                
            pixmap = QPixmap()
            if pixmap.loadFromData(image_data):
                # 이미지를 라벨 크기에 맞게 조정하되 원본 비율 유지
                scaled_pixmap = pixmap.scaled(
                    self.detection_image.width(), 
                    self.detection_image.height(),
                    Qt.KeepAspectRatio, 
                    Qt.SmoothTransformation
                )
                self.detection_image.setPixmap(scaled_pixmap)
                self.detection_image.setAlignment(Qt.AlignCenter)
                
                if DEBUG:
                    print(f"탐지 이미지 업데이트 성공 (원본: {pixmap.width()}x{pixmap.height()}, " \
                          f"조정: {scaled_pixmap.width()}x{scaled_pixmap.height()})")
            else:
                if DEBUG:
                    print("탐지 이미지 로드 실패")
                
        except Exception as e:
            if DEBUG:
                print(f"탐지 이미지 업데이트 실패: {e}")
                import traceback
                print(traceback.format_exc())

    def update_status(self, status_type: str, message: str):
        """상태 정보를 업데이트"""
        try:
            if status_type == "robot_status":
                # 로봇 상태 업데이트 - 항상 표시
                formatted_msg = f"로봇 상태: {message}"
                self.robot_status_label.setText(formatted_msg)
                
                # 로봇의 움직임 상태를 업데이트 (이동 버튼 활성화/비활성화 처리 등에 사용됨)
                self.update_robot_status(message)
                
                # detected 상태면 녹화중 표시
                if message.lower() == 'detected':
                    self.show_recording_indicator(True)
                else:
                    self.show_recording_indicator(False)
                
            elif status_type == "robot_location":
                # 로봇 위치 업데이트 - 항상 표시
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
                        # 서버에서 위치 확인을 기다리는 중인 경우
                        if self.is_moving and self.waiting_server_confirm:
                            # 서버로부터 받은 위치가 목표 위치와 일치하면 최종 이동 시작
                            if actual_location == self.target_location:
                                if DEBUG:
                                    print(f"서버 위치 확인 완료: {actual_location}, 최종 이동 시작")
                                
                                # 로그 추가
                                self.append_log(f"서버에서 위치 확인 완료: {actual_location}, 목적지로 이동")
                                
                                # 최종 목적지로 이동 애니메이션 시작
                                self.waiting_server_confirm = False  # 대기 상태 해제
                                self.complete_movement_to_target()
                            else:
                                if DEBUG:
                                    print(f"서버 위치({actual_location})가 목표({self.target_location})와 다름, 계속 대기")
                        # 단순히 현재 위치 업데이트 (이동중이 아니고, 서버 응답 대기중도 아닌 경우)
                        else:
                            if actual_location != self.current_location:
                                self.current_location = actual_location
                                self.enable_movement_buttons()
                                if DEBUG:
                                    print(f"새 위치 수신: {actual_location}, 버튼 업데이트")
            
            elif status_type == "detections":
                # 현재 진행 중인 이벤트 상황 업데이트
                # 피드백 메시지가 표시 중이면 원본 텍스트만 업데이트
                if self.feedback_timer.isActive():
                    self.original_detections_text = f"탐지 상태: {message}"
                else:
                    self.detections_label.setText(f"탐지 상태: {message}")
                    
                if DEBUG:
                    print(f"탐지 상태 업데이트: {message}")
                    
            elif status_type == "system":
                # 시스템은 항상 준비된 상태로 간주하고 메시지에서 상태와 위치만 처리
                
                # 메시지에서 상태와 위치 분리
                if "상태:" in message and "위치:" in message:
                    location_raw = message.split("위치:")[1].split(",")[0].strip()
                    status = message.split("상태:")[1].strip()
                    
                    # 각 상태별 업데이트 메서드 호출
                    self.update_status("robot_location", location_raw)
                    self.update_status("robot_status", status)
                    
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
        """중간 지점 도착 후 서버 응답 대기"""
        if DEBUG:
            print(f"중간 지점 도착. 서버 위치 응답 대기 중... (목표: {self.target_location})")
            
        # 서버 응답 대기 상태로 설정
        self.waiting_server_confirm = True
            
        # 로그 추가
        self.append_log(f"중간 지점 도착, {self.target_location} 위치 응답 대기 중")
    
    # 서버 응답 대기 로직 제거됨

    # 서버 응답 대기 로직 제거됨
            
    def complete_movement_to_target(self):
        """최종 목적지로 이동"""
        if DEBUG:
            print(f"최종 목적지로 이동 시작: {self.target_location}")
            
        # 서버 확인 완료로 설정
        self.waiting_server_confirm = False
        
        # 목적지 위치 가져오기
        target_pos = self.LOCATIONS[self.target_location]
        
        # 최종 목적지로 이동 시작
        self.robot_animation.setStartValue(self.robot_label.pos())
        self.robot_animation.setEndValue(QPoint(target_pos.x() - 15, target_pos.y() - 15))
        self.robot_animation.setDuration(1000)
        
        # 이전 연결 해제 및 새 연결 설정
        try:
            # 모든 연결 해제
            self.robot_animation.finished.disconnect()
        except:
            # 연결이 없는 경우 예외 발생하므로 무시
            pass
            
        # 새 연결 설정 
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
            self.btn_illegal.setEnabled(enabled)
            self.btn_danger.setEnabled(enabled)
            self.btn_emergency.setEnabled(enabled)
            self.btn_case_closed.setEnabled(enabled)
            
            if DEBUG:
                print(f"응답 버튼 상태 변경: {'활성화' if enabled else '비활성화'}")
                
        except Exception as e:
            if DEBUG:
                print(f"응답 버튼 상태 변경 실패: {e}")
                import traceback
                print(traceback.format_exc())

    def handle_case_closed(self):
        """사건 종료 버튼 클릭 핸들러"""
        # 기본 명령 전송 처리
        self.handle_command_button("CASE_CLOSED")
        
        # 모든 응답 명령 버튼 스타일 초기화
        self.btn_fire_report.setStyleSheet("")
        self.btn_police_report.setStyleSheet("")
        self.btn_illegal.setStyleSheet("")
        self.btn_danger.setStyleSheet("")
        self.btn_emergency.setStyleSheet("")
        self.btn_case_closed.setStyleSheet("")
        
        # 명령 버튼 상태 초기화
        self.command_buttons_state = None
        
        # 버튼 비활성화
        self.set_response_buttons_enabled(False)
        
        # 이동 버튼 활성화
        self.enable_movement_buttons()
        
        # 녹화중 표시 비활성화
        self.show_recording_indicator(False)
        
        if DEBUG:
            print("사건 종료: 모든 버튼 상태 초기화")
    
    def show_feedback_message(self, message_type, action_info=None, is_error=False):
        """사용자 액션 피드백 메시지 표시 (1.5초 후 사라짐)
        
        Args:
            message_type (str): 'command' 또는 'dialog' 등 메시지 유형, 또는 직접 표시할 메시지
            action_info (dict, optional): 액션 정보 (객체/상황/호출/클릭 정보 등)
            is_error (bool, optional): 오류 메시지 여부
        """
        try:
            # 원래 텍스트 저장 (처음 호출시 한 번만)
            if not self.original_detections_text and self.detections_label:
                self.original_detections_text = self.detections_label.text()
            
            # 메시지 구성
            if isinstance(message_type, str) and action_info is None:
                # 직접 메시지를 전달한 경우
                message = message_type
            elif message_type == 'command':
                command = action_info.get('command', 'UNKNOWN')
                message = f"명령 실행: {command}"
                
                # 명령별 세부 메시지 구성
                if command == "FIRE_REPORT":
                    message = "🔥 소방서 신고 명령이 전송되었습니다"
                elif command == "POLICE_REPORT":
                    message = "🚨 경찰서 신고 명령이 전송되었습니다" 
                elif command == "ILLEGAL_WARNING":
                    message = "⚠️ 위법행위 경고 방송을 시작합니다"
                elif command == "DANGER_WARNING":
                    message = "⚠️ 위험상황 경고 방송을 시작합니다"
                elif command == "EMERGENCY_WARNING":
                    message = "🚑 긴급상황 경고 방송을 시작합니다"
                elif command == "CASE_CLOSED":
                    message = "✅ 상황 종료 - 기록을 저장합니다"
            
            elif message_type == 'dialog':
                response = action_info.get('response', 'UNKNOWN')
                case = action_info.get('case', 'unknown')
                label = action_info.get('label', 'unknown')
                
                # 객체/상황 정보 변환
                case_str = {
                    'danger': '위험',
                    'illegal': '위법',
                    'emergency': '응급',
                    'unknown': '알 수 없음'
                }.get(case, case)
                
                label_str = {
                    'knife': '칼',
                    'gun': '총',
                    'fallen': '쓰러짐',
                    'smoking': '흡연',
                    'unknown': '알 수 없음'
                }.get(label, label)
                
                if response == "PROCEED":
                    message = f"✅ [{case_str}] {label_str} 상황 대응 진행합니다"
                else:  # "IGNORE"
                    message = f"❌ [{case_str}] {label_str} 상황 무시 처리되었습니다"
            
            else:
                message = f"알림: {action_info.get('message', '작업이 완료되었습니다')}"
                
            # 메시지 표시
            if self.detections_label:
                # 에러 메시지인지에 따라 다른 접두사 사용
                prefix = "경고: " if is_error else "알림: "
                self.detections_label.setText(f"{prefix}{message}")
                
                # 에러면 빨간색, 일반 메시지는 주황색으로 표시
                color = "#FF0000" if is_error else "#FF6600"
                self.detections_label.setStyleSheet(f"QLabel {{ color: {color}; font-weight: bold; }}")
                
                # 타이머 시작 (에러면 3초, 일반 메시지면 1.5초 후 메시지 사라짐)
                timeout = 3000 if is_error else 1500
                self.feedback_timer.start(timeout)
                
            if DEBUG:
                print(f"피드백 메시지 표시: {message}" + (" (오류)" if is_error else ""))
                
        except Exception as e:
            if DEBUG:
                print(f"피드백 메시지 표시 실패: {e}")
                import traceback
                print(traceback.format_exc())

    def clear_feedback_message(self):
        """피드백 메시지 지우기"""
        try:
            if self.detections_label:
                # 원래 스타일로 복원
                self.detections_label.setStyleSheet("")
                
                # 원래 텍스트로 복원 또는 기본값
                if self.original_detections_text:
                    self.detections_label.setText(self.original_detections_text)
                else:
                    self.detections_label.setText("탐지 상태: 탐지된 객체 없음")
                    
            # 타이머 중지
            self.feedback_timer.stop()
            
        except Exception as e:
            if DEBUG:
                print(f"피드백 메시지 지우기 실패: {e}")
                import traceback
                print(traceback.format_exc())

    def handle_command_button(self, command):
        """명령 버튼 클릭 핸들러 (피드백 메시지 표시 + 명령 전송)
        
        Args:
            command (str): 명령어 문자열
        """
        # 명령 시그널 발생
        self.robot_command.emit(command)
        
        # 명령에 따른 로그 메시지 생성
        message = {
            "DANGER_WARNING": "위험 경고를 발령했습니다.",
            "EMERGENCY_WARNING": "응급 상황 경고를 발령했습니다.",
            "ILLEGAL_WARNING": "위법 행위 경고를 발령했습니다.",
            "FIRE_REPORT": "119(소방서)에 신고를 접수했습니다.",
            "POLICE_REPORT": "112(경찰서)에 신고를 접수했습니다.",
            "CASE_CLOSED": "사건 종료 처리되었습니다."
        }.get(command, f"명령을 전송했습니다: {command}")
        
        # 로그 추가
        self.append_log(message)
        
        # 피드백 메시지 표시
        self.show_feedback_message('command', {'command': command})
        
        # 버튼 색상 변경
        sender_button = self.sender()
        if sender_button:
            # 원래 스타일시트 저장 (없으면 빈 문자열)
            original_style = sender_button.styleSheet() or ""
            
            # 버튼 색상 변경
            sender_button.setStyleSheet("background-color: #FFC107; font-weight: bold;")
            
            # 알림 팝업 표시
            from PyQt5.QtWidgets import QMessageBox
            popup = QMessageBox(self)
            popup.setWindowTitle("명령 전송 완료")
            
            # 명령어별 메시지
            msg_map = {
                "FIRE_REPORT": "119 신고가 접수되었습니다.",
                "POLICE_REPORT": "112 신고가 접수되었습니다.",
                "ILLEGAL_WARNING": "위법 행위 경고가 전송되었습니다.",
                "DANGER_WARNING": "위험 상황 경고가 전송되었습니다.",
                "EMERGENCY_WARNING": "응급 상황 경고가 전송되었습니다.",
                "CASE_CLOSED": "사건이 종료되었습니다."
            }
            
            popup.setText(msg_map.get(command, f"{command} 명령이 전송되었습니다."))
            popup.setStandardButtons(QMessageBox.Ok)
            popup.setWindowModality(Qt.NonModal)  # 모달리스 팝업
            popup.show()
            
            # 2초 후 자동으로 닫히도록 설정
            QTimer.singleShot(2000, popup.accept)
            
            # 버튼 상태 저장 (case closed 시 초기화하기 위함)
            self.command_buttons_state = {
                "button": sender_button,
                "command": command,
                "original_style": original_style
            }
        
        if DEBUG:
            print(f"명령 버튼 클릭됨: {command}")

    def blink_recording_indicator(self):
        """녹화중 표시 깜빡임 처리"""
        try:
            if self.recording_indicator:
                # 현재 상태 반전
                self.recording_visible = not self.recording_visible
                # 상태에 따라 표시/숨김
                self.recording_indicator.setVisible(self.recording_visible)
                
        except Exception as e:
            if DEBUG:
                print(f"녹화중 깜빡임 처리 실패: {e}")
                import traceback
                print(traceback.format_exc())
                
    def show_recording_indicator(self, show=False):
        """녹화중 표시 (빨간 점)
        
        Args:
            show (bool): 표시 여부
        """
        try:
            # Live 그룹박스 찾기
            live_group = self.findChild(QGroupBox, "live")
            if not live_group:
                if DEBUG:
                    print("녹화중 표시 실패: 'live' 그룹박스를 찾을 수 없음")
                return
            
            # 녹화중 표시 라벨이 없으면 생성
            if not self.recording_indicator:
                self.recording_indicator = QLabel(live_group)
                self.recording_indicator.setObjectName("recording_indicator")
                
                # Live 그룹박스 제목 오른쪽에 위치
                title_rect = live_group.contentsRect()
                title_height = 20  # 대략적인 제목 높이
                
                # 위치 계산: 제목의 오른쪽 부분
                x = 50  # Live 텍스트 길이 + 여백
                y = 0  # 제목 높이의 중앙
                
                # 넓이 증가 (80 -> 120)
                self.recording_indicator.setGeometry(x, y, 120, title_height)
                
                # 텍스트 스타일 설정 - 글씨 크기 약간 축소하고 볼드체 유지
                self.recording_indicator.setStyleSheet("color: red; font-weight: bold; font-size: 10pt;")
                self.recording_indicator.setText("● Recording")
                self.recording_indicator.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                self.recording_indicator.setToolTip("녹화중")
                
                # 위젯이 겹치지 않게 레이아웃 설정
                live_group.setContentsMargins(10, 25, 10, 10)  # 상단 여백 증가

            # 표시 여부 설정 및 깜빡임 처리
            if show:
                # 일단 표시하고 타이머 시작
                self.recording_indicator.show()
                self.recording_visible = True
                
                # 깜빡임 타이머 시작 (1.5초 간격)
                if not self.recording_blink_timer.isActive():
                    self.recording_blink_timer.start(1500)
            else:
                # 표시 숨기고 타이머 중지
                self.recording_indicator.hide()
                self.recording_visible = False
                if self.recording_blink_timer.isActive():
                    self.recording_blink_timer.stop()
                
            if DEBUG:
                print(f"녹화중 표시 {'활성화' if show else '비활성화'}")
                
        except Exception as e:
            if DEBUG:
                print(f"녹화중 표시 처리 실패: {e}")
                import traceback
                print(traceback.format_exc())
    
    def append_log(self, message):
        """로그 메시지 추가"""
        try:
            # 현재 시간 가져오기
            now = datetime.now(KOREA_TIMEZONE)
            timestamp = now.strftime("%H:%M:%S")
            
            # 로그 메시지 형식화
            log_message = f"[{timestamp}] {message}"
            
            # QTextEdit에 메시지 추가
            if hasattr(self, 'textEdit_log_box'):
                self.textEdit_log_box.append(log_message)
                
                # 스크롤을 항상 최하단으로 이동
                scrollbar = self.textEdit_log_box.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
            else:
                if DEBUG:
                    print(f"로그 위젯이 존재하지 않습니다: {log_message}")
                    
        except Exception as e:
            if DEBUG:
                print(f"로그 추가 오류: {e}")

    def _movement_complete_callback(self):
        """로봇 이동 애니메이션 완료 콜백 함수"""
        if DEBUG:
            print(f"로봇 이동 애니메이션 완료 (_movement_complete_callback)")
        
        # 경로선 제거 (먼저 수행)
        if hasattr(self, 'path_line') and self.path_line:
            self.path_line.setParent(None)
            self.path_line = None
            if DEBUG:
                print("경로선 제거 완료")
            
        # 중간 지점 도착 후 서버 응답을 기다리는 상태가 아닌 경우에만 완전 도착 처리
        if not self.waiting_server_confirm:
            # 기존 순찰 애니메이션 정지 (있다면)
            self.stop_patrol_animation()
            
            # 현재 위치 업데이트
            if self.target_location:
                self.current_location = self.target_location
                
                # 로그 추가
                self.append_log(f"{self.target_location} 위치에 도착했습니다.")
                
                # 상태 업데이트
                self.robot_status_label.setText(f"로봇 위치: {self.current_location}")
                
                # 이동 완료 상태로 변경
                self.is_moving = False
                saved_target = self.target_location
                self.target_location = None
                
                # 버튼 활성화
                self.enable_movement_buttons()
                
                # 도착 애니메이션 시작 (BASE가 아닌 경우만)
                if saved_target != 'BASE':
                    self.start_arrival_animation()
                else:
                    # BASE 위치에서는 즉시 상태 업데이트
                    self.update_robot_status('idle')
            else:
                # 이동 완료 상태로 변경
                self.is_moving = False
                self.target_location = None
                
                # 버튼 활성화
                self.enable_movement_buttons()
        else:
            if DEBUG:
                print(f"중간 지점 도착, 서버 응답 대기 중... (목표: {self.target_location})")

    def midpoint_reached_with_path(self, from_point, to_point):
        """중간 지점 도착 후 경로선 그리고 바로 최종 목적지로 이동"""
        # 경로선 그리기
        self.draw_path_line(from_point, to_point)
        
        # 중간 지점 도착 후 바로 최종 목적지로 이동
        self.midpoint_reached()

    def start_patrol_animation(self):
        """목적지에 도착 후 순찰 애니메이션 시작
        - BASE 위치에서는 순찰하지 않음
        - 지역별 순찰 반경과 시작 위치는 PATROL_CONFIG 딕셔너리로 관리
        - A 구역에서는 특정 시작점(7시 30분 방향)에서 순찰 시작
        """
        # BASE 위치에서는 순찰 애니메이션 비활성화
        if self.current_location == 'BASE':
            if DEBUG:
                print("BASE 위치입니다. 순찰 애니메이션을 시작하지 않습니다.")
            return
            
        # 순찰 중심점 설정 (현재 로봇 위치)
        center_pos = self.LOCATIONS[self.current_location]
        self.patrol_center = center_pos
        
        # 현재 위치에 대한 구역별 순찰 설정 가져오기
        patrol_config = self.PATROL_CONFIG.get(self.current_location, {
            'radius': 60,       # 기본 반경
            'start_angle': 0,   # 기본 시작 각도 (3시 방향)
            'speed': 5          # 기본 속도 (도/초)
        })
        
        # 설정 적용
        self.patrol_radius = patrol_config['radius']
        self.patrol_angle = patrol_config['start_angle']
        self.patrol_speed = patrol_config['speed']
        
        if DEBUG:
            print(f"순찰 시작 - 위치: {self.current_location}, 반경: {self.patrol_radius}, 시작각도: {self.patrol_angle}")
        
        # 경로선 제거 재확인
        if hasattr(self, 'path_line') and self.path_line:
            self.path_line.setParent(None)
            self.path_line = None
            if DEBUG:
                print("경로선 제거 (순찰 시작 전)")
        
        # 먼저 순찰 시작 위치로 이동
        self.move_to_patrol_start_position()
        
        # 로그 추가
        self.append_log(f"{self.current_location} 위치에서 순찰 시작")
        
        # 순찰 상태 설정 및 UI 업데이트는 실제 순찰 시작 시에만 진행
        self.is_patrolling = True
        self.update_robot_status('patrolling')
        
        # 순찰 애니메이션 타이머 시작 (50ms마다 갱신, 초당 20프레임)
        self.patrol_timer.start(50)
        
        if DEBUG:
            print(f"{self.current_location} 위치에서 순찰 애니메이션 시작 (반경: {self.patrol_radius}px, 속도: {self.patrol_speed}도/초, 시작각도: {self.patrol_angle}도)")

    def stop_patrol_animation(self):
        """순찰 애니메이션 정지"""
        if not self.is_patrolling:
            return
            
        # 타이머 중지
        self.patrol_timer.stop()
        
        # 순찰 상태 해제
        self.is_patrolling = False
        
        if DEBUG:
            print("순찰 애니메이션 정지")

    def update_patrol_animation(self):
        """순찰 애니메이션 프레임 업데이트 (타이머에서 호출)"""
        if not self.is_patrolling or not self.patrol_center:
            return
            
        # 각도 업데이트 (50ms마다 호출되므로 속도 조정)
        # 5도/초 = 0.25도/50ms
        angle_increment = self.patrol_speed * 50 / 1000
        self.patrol_angle = (self.patrol_angle + angle_increment) % 360
        
        # 새 위치 계산 (원 둘레)
        rad_angle = math.radians(self.patrol_angle)
        
        # 시계 방향 회전을 위해 각도 조정 (삼각함수 반대로)
        new_x = self.patrol_center.x() + self.patrol_radius * math.cos(rad_angle)
        new_y = self.patrol_center.y() - self.patrol_radius * math.sin(rad_angle)  # 부호 변경
        
        # 로봇 이동 (중앙 맞춤 위해 15픽셀 조정)
        self.robot_label.move(int(new_x) - 15, int(new_y) - 15)
        
        # 디버깅 - 90도 간격으로 로그 출력 (너무 많은 로그 방지)
        if DEBUG and (abs(self.patrol_angle - angle_increment - 0) < angle_increment * 0.5 or 
                      abs(self.patrol_angle - angle_increment - 90) < angle_increment * 0.5 or
                      abs(self.patrol_angle - angle_increment - 180) < angle_increment * 0.5 or
                      abs(self.patrol_angle - angle_increment - 270) < angle_increment * 0.5):
            print(f"순찰 애니메이션 각도: {self.patrol_angle:.1f}도, 위치: ({int(new_x)}, {int(new_y)})")
    
    def cleanup_resources(self):
        """리소스 정리 (애니메이션, 타이머 등)"""
        try:
            # 순찰 애니메이션 정지
            if hasattr(self, 'patrol_timer') and self.patrol_timer.isActive():
                self.patrol_timer.stop()
                
            # 도착 애니메이션 정리
            if hasattr(self, 'arrival_animation') and self.arrival_animation:
                self.arrival_animation.stop()
                self.arrival_animation.deleteLater()
                self.arrival_animation = None
                
            # 피드백 타이머 정지
            if hasattr(self, 'feedback_timer') and self.feedback_timer.isActive():
                self.feedback_timer.stop()
                
            # 녹화 표시 타이머 정지
            if hasattr(self, 'recording_blink_timer') and self.recording_blink_timer.isActive():
                self.recording_blink_timer.stop()
                
            if DEBUG:
                print("MonitoringTab 리소스 정리 완료")
        except Exception as e:
            if DEBUG:
                print(f"리소스 정리 실패: {e}")
                
    def closeEvent(self, event):
        """위젯 종료 시 리소스 정리"""
        self.cleanup_resources()
        super().closeEvent(event)
    
    def start_arrival_animation(self):
        """
        목적지 도착 시 부드러운 도착 애니메이션을 시작하고
        완료되면 자동으로 순찰 애니메이션을 시작합니다.
        - 목적지에 도착하면, 중심점으로 부드럽게 이동
        - A 구역 도착시, 추가 준비 설정 (특정 시작점으로 이동)
        """
        if DEBUG:
            print(f"도착 애니메이션 시작 (위치: {self.current_location})")
        
        # 현재 로봇 위치 얻기
        current_pos = self.robot_label.pos()
        target_pos = self.LOCATIONS[self.current_location]
        center_x = target_pos.x() - 15  # 중앙 정렬을 위해 조정
        center_y = target_pos.y() - 15
        
        # 도착 애니메이션 생성 (애니메이션 곡선은 지역별로 조정)
        self.arrival_animation = QPropertyAnimation(self.robot_label, b"pos")
        self.arrival_animation.setStartValue(current_pos)
        self.arrival_animation.setEndValue(QPoint(center_x, center_y))
        
        # 지역별 특성에 맞게 애니메이션 조정
        if self.current_location == 'A':
            # A 구역은 부드럽게 도착 (OutQuad)
            self.arrival_animation.setDuration(700)  # 0.7초 (약간 느리게)
            self.arrival_animation.setEasingCurve(QEasingCurve.OutQuad)
        elif self.current_location == 'B':
            # B 구역도 A와 같이 부드럽게 도착 (OutQuad)
            self.arrival_animation.setDuration(700)  # 0.7초 
            self.arrival_animation.setEasingCurve(QEasingCurve.OutQuad)
        else:
            # 다른 구역은 약간 튕기는 효과 (OutBack)
            self.arrival_animation.setDuration(500)  # 0.5초
            self.arrival_animation.setEasingCurve(QEasingCurve.OutBack)
        
        # 애니메이션 완료 시 순찰 시작
        self.arrival_animation.finished.connect(self.on_arrival_animation_finished)
        
        # 애니메이션 시작
        self.arrival_animation.start()
        
    def on_arrival_animation_finished(self):
        """도착 애니메이션 완료 후 순찰 시작"""
        if DEBUG:
            print(f"도착 애니메이션 완료 (위치: {self.current_location})")
        
        # 도착 애니메이션 객체 정리
        if self.arrival_animation:
            self.arrival_animation.deleteLater()
            self.arrival_animation = None
        
        # 이동 완료 처리
        self.is_moving = False
        
        # 경로선 제거 (중복 확인)
        if hasattr(self, 'path_line') and self.path_line:
            self.path_line.setParent(None)
            self.path_line = None
            if DEBUG:
                print("경로선 제거 (도착 애니메이션 완료 시)")
        
        # 이동 버튼 활성화
        self.enable_movement_buttons()
        
        # 잠시 대기 후 순찰 애니메이션 시작 (BASE가 아닌 위치인 경우)
        # 약간의 딜레이를 주어 애니메이션 사이의 자연스러운 전환 확보
        if self.current_location != 'BASE':
            delay = 200  # 200ms (0.2초) 딜레이로 증가
            QTimer.singleShot(delay, self.start_patrol_animation)
            
            if DEBUG:
                print(f"{delay}ms 후 순찰 애니메이션 시작 예정")

    def move_to_patrol_start_position(self):
        """
        목적지의 특정 패트롤 시작 위치로 로봇을 이동시킵니다.
        A 구역에서는 특별한 시작 위치를 사용하고, 다른 위치에서는 중심점을 사용합니다.
        이 함수는 start_patrol_animation에서 호출됩니다.
        """
        if not self.patrol_center:
            if DEBUG:
                print("순찰 중심점이 설정되지 않았습니다.")
            return
        
        # 각도에 따른 원주 위의 좌표 계산
        rad_angle = math.radians(self.patrol_angle)
        
        # 새 위치 계산 (시계방향 회전을 위해 y 좌표 부호 반전)
        new_x = self.patrol_center.x() + self.patrol_radius * math.cos(rad_angle)
        new_y = self.patrol_center.y() - self.patrol_radius * math.sin(rad_angle)  # 부호 변경
        
        # 목표 위치 계산 (중앙 정렬을 위해 로봇 크기 고려)
        target_x = int(new_x) - 15  # 로봇 이미지 중심 맞춤 (가로)
        target_y = int(new_y) - 15  # 로봇 이미지 중심 맞춤 (세로)
        end_pos = QPoint(target_x, target_y)
        
        # 경로선이 남아있으면 제거 (안전 확인)
        if hasattr(self, 'path_line') and self.path_line:
            self.path_line.setParent(None)
            self.path_line = None
            if DEBUG:
                print("경로선 제거 (패트롤 시작 위치 이동 전)")
        
        # A 또는 B 구역의 경우 부드러운 애니메이션으로 시작 위치로 이동
        if self.current_location == 'A' or self.current_location == 'B':
            # 현재 위치
            start_pos = self.robot_label.pos()
            
            # 위치가 크게 다를 경우에만 애니메이션 적용 (이미 적절한 위치에 있으면 스킵)
            distance = math.sqrt((start_pos.x() - target_x)**2 + (start_pos.y() - target_y)**2)
            if distance > 10:  # 10픽셀 이상 차이가 있을 때만 이동
                # 패트롤 시작 위치로 이동하는 애니메이션
                patrol_start_anim = QPropertyAnimation(self.robot_label, b"pos")
                patrol_start_anim.setStartValue(start_pos)
                patrol_start_anim.setEndValue(end_pos)
                patrol_start_anim.setDuration(500)  # 0.5초
                patrol_start_anim.setEasingCurve(QEasingCurve.InOutQuad)
                
                # 애니메이션 실행 (동기 처리 - 애니메이션이 끝날 때까지 기다림)
                patrol_start_anim.start()
                
                # 이벤트 루프에서 애니메이션 완료까지 기다림
                from PyQt5.QtCore import QEventLoop
                loop = QEventLoop()
                patrol_start_anim.finished.connect(loop.quit)
                loop.exec_()
                
                if DEBUG:
                    print(f"{self.current_location} 구역 순찰 시작 위치로 이동 완료: ({target_x}, {target_y}), 각도: {self.patrol_angle}도")
            else:
                if DEBUG:
                    print(f"{self.current_location} 구역: 로봇이 이미 패트롤 시작 위치와 충분히 가까움. 이동 건너뜀.")
                # 정확한 위치로 조정
                self.robot_label.move(target_x, target_y)
        else:
            # 다른 구역은 즉시 시작 위치로 설정
            self.robot_label.move(target_x, target_y)
            
            if DEBUG:
                print(f"{self.current_location} 구역 순찰 시작 위치로 설정: ({target_x}, {target_y}), 각도: {self.patrol_angle}도")

