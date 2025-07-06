#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Case Logs Tab Module
로그 조회 탭 UI 및 로직 구현
- 사건 로그 데이터 표시 및 필터링
- 상세 정보 및 영상 재생 기능
- 로그 액션 정보 시각화
"""

# 표준 라이브러리 임포트
import os
import sys
import time
import traceback
import subprocess
from datetime import datetime

# PyQt5 관련 임포트
from PyQt5.QtWidgets import QWidget, QTableWidgetItem, QHeaderView, QMessageBox, QLabel
from PyQt5.QtCore import Qt, QDateTime, QUrl, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.uic import loadUi

# 비디오 재생 관련 임포트
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
import vlc  # VLC 미디어 플레이어

# libva 메시지 표시 레벨 설정 (0: 없음 - 성능 향상 목적)
os.environ["LIBVA_MESSAGING_LEVEL"] = "0"

# 디버그 설정
DEBUG = True  # True: 디버그 로그 출력, False: 로그 출력 안함

# 디버그 태그 (로그 분류용)
DEBUG_TAG = {
    'INIT': '[초기화]',  # 초기화 관련 로그
    'CONN': '[연결]',    # 네트워크 연결 로그
    'RECV': '[수신]',    # 데이터 수신 로그
    'SEND': '[전송]',    # 데이터 전송 로그
    'FILTER': '[필터]',  # 데이터 필터링 로그
    'ERR': '[오류]'      # 오류 로그
}

# 탭 내부 상태 관리를 위한 상수들
# (서버 관련 상수는 메인윈도우로 이동함)

class CaseLogsTab(QWidget):
    """
    사건 로그 조회 탭 클래스
    
    주요 기능:
    - 사건 로그 데이터 표시 및 필터링
    - 로그 상세 정보 및 증거 영상 재생
    - 로그별 대응 액션 조회
    - 시간, 위치, 이벤트 타입별 필터링
    """
    
    def __init__(self, parent=None, initial_logs=None):
        """초기화"""
        super(CaseLogsTab, self).__init__(parent)
        self.parent = parent  # 메인 윈도우 참조 저장
        self.initUI()
        self.logs = initial_logs or []  # 로그 데이터 저장 (초기값 사용)
        self.filtered_logs = self.logs.copy()  # 필터링된 로그 데이터
        self.selected_log = None  # 현재 선택된 로그
        self.first_load = True  # 첫 로드 여부 플래그
        self.play_icon_visible = False  # 재생 아이콘 표시 상태
        self.last_icon_debug_log = 0  # 마지막 재생 아이콘 디버그 로그 시간
        
        # 콤보박스 초기화
        self.populate_comboboxes()
        
        # 테이블 업데이트
        self.update_table()
        
    def initUI(self):
        """UI 초기화"""
        try:
            # UI 파일 로드
            loadUi("gui/ui/case_logs_tap5.ui", self)
            
            # 테이블 설정 - Qt Designer에서 변경된 컬럼 순서에 맞게 헤더 라벨 변경
            self.tableWidget.setColumnCount(15)
            self.tableWidget.setHorizontalHeaderLabels([
                "Case ID", "Case Closed", "Ignored", "Case Type", "Detection Type", 
                "Start Time", "End Time", "Robot ID", "User Name", "Location", 
                "Reported to 119", "Reported to 112", "Illegal", "Danger", 
                "Emergency"
            ])
            
            # 테이블 열 너비를 내용에 맞게 조정 (자동 늘어나지 않도록 설정)
            self.tableWidget.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
            # 내용에 맞게 열 너비 초기 설정후 고정
            self.tableWidget.resizeColumnsToContents()
            
            # 특정 열의 너비 설정 (너비가 부족한 열만 추가로 조정)
            self.tableWidget.setColumnWidth(5, 150)  # Start Time 열 (6번째 인덱스=5)
            self.tableWidget.setColumnWidth(6, 150)  # End Time 열 (7번째 인덱스=6)
            
            self.tableWidget.horizontalHeader().setStretchLastSection(False)
            
            # 기본 인덱스(행번호) 숨기기
            self.tableWidget.verticalHeader().setVisible(False)
            
            # 헤더 텍스트 중앙 정렬 설정
            for i in range(self.tableWidget.columnCount()):
                self.tableWidget.horizontalHeaderItem(i).setTextAlignment(Qt.AlignCenter)
            
            # 비디오 위젯 준비 (VLC 사용 시에는 직접 위젯 설정이 필요 없음)
            # VLC는 widget_case_detail_video의 winId를 직접 사용함
            self.widget_case_detail_video.setObjectName("widget_case_detail_video")
            
            # 기존 QMediaPlayer는 유지 (필요시 fallback으로 사용)
            self.qmediaPlayer = QMediaPlayer(self)
            self.videoWidget = QVideoWidget(self.widget_case_detail_video)
            self.videoWidget.setGeometry(self.widget_case_detail_video.rect())
            self.videoWidget.setObjectName("videoWidget")
            self.videoWidget.hide()  # VLC 사용 시에는 숨김
            self.qmediaPlayer.setVideoOutput(self.videoWidget)
            
            # VLC 미디어 플레이어 초기화 (미디어 이벤트 처리를 위해 고급 옵션 추가)
            self.instance = vlc.Instance('--quiet', '--no-xlib')  # xlib 관련 경고 방지
            self.mediaPlayer = self.instance.media_player_new()
            
            # VLC 이벤트 매니저 설정
            self.event_manager = self.mediaPlayer.event_manager()
            
            # 이벤트 콜백 함수 등록
            self.event_manager.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_media_end_reached)
            self.event_manager.event_attach(vlc.EventType.MediaPlayerTimeChanged, self._on_time_changed)
            self.event_manager.event_attach(vlc.EventType.MediaPlayerLengthChanged, self._on_length_changed)
            self.event_manager.event_attach(vlc.EventType.MediaPlayerPositionChanged, self._on_position_changed)
            
            # VLC 미디어 플레이어를 위젯에 연결 (Linux)
            if sys.platform.startswith('linux'):
                self.mediaPlayer.set_xwindow(int(self.widget_case_detail_video.winId()))
            # Windows의 경우
            elif sys.platform == "win32":
                self.mediaPlayer.set_hwnd(int(self.widget_case_detail_video.winId()))
            # Mac OS X의 경우
            elif sys.platform == "darwin":
                self.mediaPlayer.set_nsobject(int(self.widget_case_detail_video.winId()))
                
            # 비디오 영역 클릭 이벤트 처리를 위한 이벤트 필터 설치
            self.widget_case_detail_video.installEventFilter(self)
            self.widget_case_detail_video.setCursor(Qt.PointingHandCursor)  # 커서 변경으로 클릭 가능함을 표시
                
            # 재생 상태 추적을 위한 변수
            self.is_playing = False
            self.base_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'main_server')
            
            # 미디어 컨트롤 버튼 연결
            self.pushButton_run.clicked.connect(self.toggle_playback)       # 재생/일시정지 토글 버튼
            self.pushButton_stop.clicked.connect(self.stop_media)           # ■ 정지 버튼
            self.pushButton_seek_forward.clicked.connect(self.seek_forward) # ▶▶ 앞으로 5초 이동
            self.pushButton_seek_backward.clicked.connect(self.seek_backward) # ◀◀ 뒤로 5초 이동
            
            # 슬라이더 설정
            self.horizontalSlider_running_time.setRange(0, 0)
            self.horizontalSlider_volume.setRange(0, 100)
            self.horizontalSlider_volume.setValue(50)  # 기본 볼륨 50%
            
            # VLC 볼륨 설정
            self.mediaPlayer.audio_set_volume(50)
            
            # 슬라이더 이벤트 연결
            self.horizontalSlider_running_time.sliderMoved.connect(self.set_position)
            self.horizontalSlider_volume.valueChanged.connect(self.set_volume)
            
            # 날짜 필터 초기화 (현재 날짜 기준 7일 전부터)
            current_datetime = QDateTime.currentDateTime()
            week_ago = current_datetime.addDays(-7)
            
            self.dateTimeEdit_start_date.setDateTime(week_ago)
            self.dateTimeEdit_end_date.setDateTime(current_datetime)

            # 필터 버튼 연결
            self.pushButton_filter_apply.clicked.connect(self.apply_filter)
            self.pushButton_filter_reset.clicked.connect(self.reset_filter)
            
            # 테이블 선택 이벤트 연결
            self.tableWidget.itemSelectionChanged.connect(self.handle_selection_changed)
            
            if DEBUG:
                print(f"{DEBUG_TAG['INIT']} Case Logs Tab UI 초기화 완료")
                
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} UI 초기화 실패: {e}")
                print(traceback.format_exc())
    
    def update_logs(self, logs):
        """로그 데이터 업데이트 (MainWindow에서 호출)"""
        if DEBUG:
            print(f"{DEBUG_TAG['RECV']} 로그 데이터 업데이트:")
            print(f"  - 로그 개수: {len(logs)}")
            
            # 데이터 형식 확인을 위한 추가 디버그 출력
            if logs and len(logs) > 0:
                first_log = logs[0]
                print(f"  - 첫 번째 로그 샘플:")
                for key, value in first_log.items():
                    print(f"    {key}: {value} (타입: {type(value).__name__})")
            
        # 로그 데이터 저장
        self.logs = logs
        self.filtered_logs = logs.copy()  # 필터링 초기화
        
        # 콤보박스 업데이트
        self.populate_comboboxes()
        
        # 테이블 업데이트 (정렬은 update_table 내부에서 수행)
        self.update_table()
        
        # 로그 데이터가 없으면 메시지 표시 (영어로)
        if not self.logs:
            QMessageBox.information(self, "No Data", "No log data available.\nPlease check if there is data in the actual DB.")
        
    def populate_comboboxes(self):
        """콤보박스 옵션 채우기"""
        try:
            if DEBUG:
                print(f"{DEBUG_TAG['INIT']} 콤보박스 옵션 설정")
                
            # 케이스 타입 콤보박스 (영어로 표시, 첫 글자 대문자)
            self.comboBox_case_type.clear()
            self.comboBox_case_type.addItem("All Case Types")
            case_types = sorted(set(log.get("case_type", "") for log in self.logs if log.get("case_type")))
            
            # 케이스 타입 사용자 친화적으로 표시 (영어로, 첫 글자 대문자)
            case_type_map = {
                "danger": "Danger",
                "emergency": "Emergency",
                "illegal": "Illegal"
            }
            
            for case_type in case_types:
                friendly_name = case_type_map.get(case_type, case_type.capitalize())
                # 저장 값을 소문자로 통일하여 비교 일관성 확보
                self.comboBox_case_type.addItem(friendly_name, case_type.lower())  # 표시 이름, 실제 값(소문자)
            
            # 탐지 타입 콤보박스 (영어로 표시, 첫 글자 대문자)
            self.comboBox_detection_type.clear()
            self.comboBox_detection_type.addItem("All Detection Types")
            detection_types = sorted(set(log.get("detection_type", "") for log in self.logs if log.get("detection_type")))
            
            # 탐지 타입 사용자 친화적으로 표시 (영어로, 첫 글자 대문자)
            detection_type_map = {
                "knife": "Knife",
                "gun": "Gun",
                "lying_down": "Lying_Down",
                "cigarette": "Cigarette"
            }
            
            for detection_type in detection_types:
                friendly_name = detection_type_map.get(detection_type, detection_type.capitalize())
                # 저장 값을 소문자로 통일하여 비교 일관성 확보
                self.comboBox_detection_type.addItem(friendly_name, detection_type.lower())  # 표시 이름, 실제 값(소문자)
            
            # 로봇 ID 콤보박스
            self.comboBox_robot_id.clear()
            self.comboBox_robot_id.addItem("All Robots")
            robot_ids = sorted(set(log.get("robot_id", "") for log in self.logs if log.get("robot_id")))
            robot_ids = sorted(robot_ids)
            self.comboBox_robot_id.addItems(robot_ids)
            
            # 로봇 ID 콤보박스 (영어로 표시)
            self.comboBox_robot_id.clear()
            self.comboBox_robot_id.addItem("All Robots")
            robot_ids = sorted(set(log.get("robot_id", "") for log in self.logs if log.get("robot_id")))
            self.comboBox_robot_id.addItems(robot_ids)
            
            # 위치 콤보박스 (영어로 표시)
            self.comboBox_location_id.clear()
            self.comboBox_location_id.addItem("All Locations")
            locations = sorted(set(str(log.get("location", "")) for log in self.logs if log.get("location") is not None))
            
            # 위치 매핑 (영어로 표시)
            location_map = {
                "A": "A",
                "B": "B",
                "BASE": "Base"
            }
            
            for location in locations:
                friendly_name = location_map.get(location, location)
                self.comboBox_location_id.addItem(friendly_name, location)
            
            # 사용자 계정 콤보박스 (영어로 표시)
            self.comboBox_user_account.clear()
            self.comboBox_user_account.addItem("All Users")
            user_ids = sorted(set(log.get("user_id", "") for log in self.logs if log.get("user_id")))
            self.comboBox_user_account.addItems(user_ids)
            
            # 액션 타입 콤보박스 (영어로 표시)
            self.comboBox_action_type.clear()
            self.comboBox_action_type.addItem("All Actions")
            action_types = [
                "Reported to 119", "Reported to 112", "Case Closed", 
                "Danger", "Emergency", "Illegal", "Ignored"
            ]
            
            # 액션 타입 매핑 (영어로만 표시, 매핑 필요 없음)
            action_type_map = {}  # 영어로만 표시하므로 매핑 필요 없음
            
            for action in action_types:
                friendly_name = action_type_map.get(action, action)
                self.comboBox_action_type.addItem(friendly_name, action)
            
            if DEBUG:
                print(f"{DEBUG_TAG['INIT']} 콤보박스 옵션 설정 완료")
                
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 콤보박스 설정 실패: {e}")
                print(traceback.format_exc())
    
    def update_table(self):
        """테이블 내용 업데이트"""
        try:
            # 비디오 재생 중지 (필터 변경 시에도 재생 중지)
            self.stop_video_playback()
            
            # 케이스 ID 기준 오름차순으로 로그 정렬
            try:
                # case_id를 정수로 변환하여 정렬 (정수 변환 실패 시 문자열로 정렬)
                sorted_logs = sorted(self.filtered_logs, key=lambda x: int(x.get("case_id", 0)) if str(x.get("case_id", "")).isdigit() else x.get("case_id", ""))
                self.filtered_logs = sorted_logs
            except Exception as e:
                if DEBUG:
                    print(f"{DEBUG_TAG['FILTER']} 케이스 ID 정렬 실패: {e}, 문자열 정렬로 시도합니다.")
                # 정수 변환 실패 시 문자열 기준 정렬
                self.filtered_logs = sorted(self.filtered_logs, key=lambda x: str(x.get("case_id", "")))
            
            # 테이블 행 수 설정
            self.tableWidget.setRowCount(0)  # 초기화
            self.tableWidget.setRowCount(len(self.filtered_logs))
            
            # 테이블에 데이터 추가
            for row, log in enumerate(self.filtered_logs):
                # 필수 필드 검사 (없을 경우 "Unknown"으로 설정)
                case_id = str(log.get("case_id", "Unknown"))
                start_time = log.get("start_time", "Unknown")
                end_time = log.get("end_time", "Unknown")
                
                # 사용자 친화적인 이름으로 표시 & 첫글자 대문자로 변환
                case_type_raw = log.get("case_type", "Unknown")
                case_type_map = {
                    "danger": "Danger",
                    "emergency": "Emergency",
                    "illegal": "Illegal",
                    # Unknown은 이미 대문자로 시작함
                }
                # 매핑된 값이 없을 경우 첫 글자만 대문자로 변환
                case_type = case_type_map.get(case_type_raw, case_type_raw.capitalize())
                
                detection_type_raw = log.get("detection_type", "Unknown")
                detection_type_map = {
                    "knife": "Knife",
                    "gun": "Gun",                    
                    "lying_down": "Lying_Down",
                    "cigarette": "Cigarette"
                }
                # 매핑된 값이 없을 경우 첫 글자만 대문자로 변환
                detection_type = detection_type_map.get(detection_type_raw, detection_type_raw.capitalize())
                
                robot_id = log.get("robot_id", "Unknown")
                user_id = log.get("user_id", "Unknown")
                location = log.get("location", "Unknown")
                is_ignored = str(log.get("is_ignored", "Unknown"))
                is_119_reported = str(log.get("is_119_reported", "Unknown"))
                is_112_reported = str(log.get("is_112_reported", "Unknown"))
                is_illegal_warned = str(log.get("is_illegal_warned", "Unknown"))
                is_danger_warned = str(log.get("is_danger_warned", "Unknown"))
                is_emergency_warned = str(log.get("is_emergency_warned", "Unknown"))
                is_case_closed = str(log.get("is_case_closed", "Unknown"))
                
                # ISO 형식 시간을 읽기 좋은 형태로 변환
                try:
                    start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                    formatted_start = start_dt.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    formatted_start = start_time
                    
                try:
                    end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                    formatted_end = end_dt.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    formatted_end = end_time
                
                # 테이블에 아이템 추가 - Qt Designer에서 변경한 컬럼 순서에 맞게 데이터 배치
                # Case ID는 그대로 첫번째 위치 (볼드체 및 중앙 정렬)
                item_case_id = QTableWidgetItem(case_id)
                from PyQt5.QtGui import QFont
                bold_font = QFont()
                bold_font.setBold(True)
                item_case_id.setFont(bold_font)
                item_case_id.setTextAlignment(Qt.AlignCenter)
                self.tableWidget.setItem(row, 0, item_case_id)
                
                # 이모지를 위한 특수 폰트 설정
                from PyQt5.QtGui import QFont
                emoji_font = QFont("Noto Color Emoji", 12)  # 이모지용 폰트 크기 설정
                
                # 이진 속성들은 0/1 대신 ✅/❌로 표시
                # 새 순서: 1=Case Closed, 2=Ignored, 3=Case Type, 4=Detection Type
                
                # Case Closed (1번 위치로 이동)
                item_closed = QTableWidgetItem("✅" if is_case_closed == "1" else "❌")
                item_closed.setFont(emoji_font)
                item_closed.setTextAlignment(Qt.AlignCenter)
                self.tableWidget.setItem(row, 1, item_closed)
                
                # Ignored (2번 위치로 이동)
                item_ignored = QTableWidgetItem("✅" if is_ignored == "1" else "❌")
                item_ignored.setFont(emoji_font)
                item_ignored.setTextAlignment(Qt.AlignCenter)
                self.tableWidget.setItem(row, 2, item_ignored)
                
                # Case Type과 Detection Type (3, 4번 위치) - 정렬 없음(기본 왼쪽 정렬)
                self.tableWidget.setItem(row, 3, QTableWidgetItem(case_type))
                self.tableWidget.setItem(row, 4, QTableWidgetItem(detection_type))
                
                # 시간 정보 (5, 6번 위치로 이동) - 가운데 정렬
                item_start = QTableWidgetItem(formatted_start)
                item_start.setTextAlignment(Qt.AlignCenter)
                self.tableWidget.setItem(row, 5, item_start)
                
                item_end = QTableWidgetItem(formatted_end)
                item_end.setTextAlignment(Qt.AlignCenter)
                self.tableWidget.setItem(row, 6, item_end)
                
                # 로봇 ID, 사용자, 위치 정보 (7~9번 위치) - 가운데 정렬
                item_robot = QTableWidgetItem(robot_id)
                item_robot.setTextAlignment(Qt.AlignCenter)
                self.tableWidget.setItem(row, 7, item_robot)
                
                item_user = QTableWidgetItem(user_id)
                item_user.setTextAlignment(Qt.AlignCenter)
                self.tableWidget.setItem(row, 8, item_user)
                
                item_location = QTableWidgetItem(location)
                item_location.setTextAlignment(Qt.AlignCenter)
                self.tableWidget.setItem(row, 9, item_location)
                
                # 나머지 이모지 표시 항목들 (10~14번 위치)
                for col_idx, value in [
                    (10, is_119_reported), (11, is_112_reported),
                    (12, is_illegal_warned), (13, is_danger_warned), 
                    (14, is_emergency_warned)
                ]:
                    item = QTableWidgetItem("✅" if value == "1" else "❌")
                    item.setFont(emoji_font)
                    item.setTextAlignment(Qt.AlignCenter)  # 가운데 정렬 추가
                    self.tableWidget.setItem(row, col_idx, item)
                
            # 로그 수 표시 업데이트
            self.label_number_of_log.setText(f"Number of Logs: {len(self.filtered_logs)}")
            
            if DEBUG:
                print(f"{DEBUG_TAG['FILTER']} 로그 테이블 업데이트 완료 (총 {len(self.filtered_logs)}개)")
                
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 테이블 업데이트 실패: {e}")
                print(traceback.format_exc())
    
    def apply_filter(self):
        """필터 적용"""
        try:
            if DEBUG:
                print(f"{DEBUG_TAG['FILTER']} 필터 적용 시작")
                
            filtered = self.logs.copy()
            
            # 시작 및 종료 날짜 필터
            start_date = self.dateTimeEdit_start_date.dateTime().toString(Qt.ISODate)
            end_date = self.dateTimeEdit_end_date.dateTime().toString(Qt.ISODate)
            
            # 선택된 필터 값 가져오기 - itemData가 있으면 사용, 없으면 텍스트 사용
            case_type_idx = self.comboBox_case_type.currentIndex()
            selected_case_type = self.comboBox_case_type.itemData(case_type_idx) if case_type_idx > 0 else None
            
            detection_type_idx = self.comboBox_detection_type.currentIndex()
            selected_detection_type = self.comboBox_detection_type.itemData(detection_type_idx) if detection_type_idx > 0 else None
            selected_robot_id = self.comboBox_robot_id.currentText() if self.comboBox_robot_id.currentIndex() > 0 else None
            selected_location_id = self.comboBox_location_id.currentText() if self.comboBox_location_id.currentIndex() > 0 else None
            selected_user_account = self.comboBox_user_account.currentText() if self.comboBox_user_account.currentIndex() > 0 else None
            selected_action_type = self.comboBox_action_type.currentText() if self.comboBox_action_type.currentIndex() > 0 else None
            
            # 날짜 필터링
            date_filtered = []
            for log in filtered:
                log_start_time = log.get("start_time", "")
                if not log_start_time:
                    continue
                    
                # ISO 형식을 비교 가능한 형식으로 변환
                try:
                    log_start_dt = datetime.fromisoformat(log_start_time.replace("Z", "+00:00"))
                    log_start_iso = log_start_dt.isoformat()
                    
                    if start_date <= log_start_iso and log_start_iso <= end_date:
                        date_filtered.append(log)
                except:
                    # 날짜 형식 오류시 그냥 추가
                    date_filtered.append(log)
            
            filtered = date_filtered
            
            # 케이스 타입 필터링
            if selected_case_type:
                # selected_case_type은 이미 소문자로 저장되어 있음
                filtered = [log for log in filtered if log.get("case_type", "").lower() == selected_case_type]
            
            # 탐지 타입 필터링
            if selected_detection_type:
                # selected_detection_type은 이미 소문자로 저장되어 있음
                filtered = [log for log in filtered if log.get("detection_type", "").lower() == selected_detection_type]
            
            # 로봇 ID 필터링
            if selected_robot_id:
                filtered = [log for log in filtered if log.get("robot_id") == selected_robot_id]
            
            # 위치 필터링
            if selected_location_id:
                filtered = [log for log in filtered if log.get("location") == selected_location_id]
            
            # 사용자 계정 필터링
            if selected_user_account:
                filtered = [log for log in filtered if log.get("user_id") == selected_user_account]
            
            # 액션 타입 필터링 (itemData와 표시 이름을 둘 다 체크)
            if selected_action_type:
                # 데이터 항목이 있는지 확인
                action_idx = self.comboBox_action_type.currentIndex()
                action_data = self.comboBox_action_type.itemData(action_idx)
                
                # 아이템 데이터가 있으면 그것을 사용, 없으면 표시 텍스트 사용
                action_type = action_data if action_data else selected_action_type
                
                # 액션 타입에 따른 필터링
                if "119" in action_type or "119 신고" == selected_action_type:
                    filtered = [log for log in filtered if log.get("is_119_reported") == 1]
                elif "112" in action_type or "112 신고" == selected_action_type:
                    filtered = [log for log in filtered if log.get("is_112_reported") == 1]
                elif "Case Closed" in action_type or "케이스 종료" == selected_action_type:
                    filtered = [log for log in filtered if log.get("is_case_closed") == 1]
                elif "Danger" in action_type or "위험 경고" == selected_action_type:
                    filtered = [log for log in filtered if log.get("is_danger_warned") == 1]
                elif "Emergency" in action_type or "응급 경고" == selected_action_type:
                    filtered = [log for log in filtered if log.get("is_emergency_warned") == 1]
                elif "Illegal" in action_type or "불법 행위 경고" == selected_action_type:
                    filtered = [log for log in filtered if log.get("is_illegal_warned") == 1]
                elif "Ignored" in action_type or "무시됨" == selected_action_type:
                    filtered = [log for log in filtered if log.get("is_ignored") == 1]
            
            # 필터링된 결과 저장 및 테이블 업데이트
            self.filtered_logs = filtered
            self.update_table()  # update_table 내부에서 케이스 ID 기준으로 정렬됨
            
            if DEBUG:
                print(f"{DEBUG_TAG['FILTER']} 필터 적용 완료: {len(self.filtered_logs)}개 로그 필터링됨")
                
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 필터 적용 실패: {e}")
                print(traceback.format_exc())
    
    def reset_filter(self):
        """필터 초기화"""
        try:
            if DEBUG:
                print(f"{DEBUG_TAG['FILTER']} 필터 초기화")
                
            # 날짜 필터 초기화 (현재 날짜 기준 7일 전부터)
            current_datetime = QDateTime.currentDateTime()
            week_ago = current_datetime.addDays(-7)
            
            self.dateTimeEdit_start_date.setDateTime(week_ago)
            self.dateTimeEdit_end_date.setDateTime(current_datetime)
            
            # 콤보박스 선택 초기화
            self.comboBox_case_type.setCurrentIndex(0)
            self.comboBox_detection_type.setCurrentIndex(0)
            self.comboBox_robot_id.setCurrentIndex(0)
            self.comboBox_location_id.setCurrentIndex(0)
            self.comboBox_user_account.setCurrentIndex(0)
            self.comboBox_action_type.setCurrentIndex(0)
            
            # 필터링 초기화
            self.filtered_logs = self.logs.copy()
            
            # 테이블 업데이트 (정렬은 update_table 내부에서 수행)
            self.update_table()
            
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 필터 초기화 실패: {e}")
                print(traceback.format_exc())
    
    def handle_selection_changed(self):
        """테이블 선택 변경 처리"""
        try:
            # 선택된 아이템 가져오기
            selected_items = self.tableWidget.selectedItems()
            if not selected_items:
                return
                
            # 선택된 행 인덱스
            row = selected_items[0].row()
            
            # 선택된 로그 가져오기
            if row >= 0 and row < len(self.filtered_logs):
                self.selected_log = self.filtered_logs[row]
                # 로그 선택 정보 디버깅 (중복 출력 방지)
                if DEBUG:
                    print(f"{DEBUG_TAG['RECV']} 로그 선택: case_id={self.selected_log.get('case_id')}")
                    
                self.display_log_details()
            
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 선택 변경 처리 실패: {e}")
                print(traceback.format_exc())
    
    def display_log_details(self):
        """선택된 로그의 상세 정보 표시"""
        try:
            if not self.selected_log:
                return
                
            if DEBUG:
                print(f"{DEBUG_TAG['RECV']} 로그 상세 정보 표시 시작")
            
            # 비디오 재생 중지 및 초기화 (새 로그 선택 시)
            self.stop_video_playback()
            
            # 이미지 경로를 사용하여 썸네일 표시
            image_path = self.selected_log.get("image_path", "")
            if image_path:
                full_image_path = os.path.join(self.base_path, image_path)
                if os.path.exists(full_image_path):
                    # 이미지를 위젯에 표시하기 위한 코드
                    pixmap = QPixmap(full_image_path)
                    if not pixmap.isNull():
                        # 위젯 크기에 맞게 이미지 조정
                        if DEBUG:
                            print(f"{DEBUG_TAG['RECV']} 썸네일 이미지 표시: {full_image_path}")
                            
                        # 썸네일 레이블 생성 또는 업데이트
                        if not hasattr(self, 'thumbnail_label'):
                            self.thumbnail_label = QLabel(self.widget_case_detail_video)
                            self.thumbnail_label.setGeometry(self.widget_case_detail_video.rect())
                            self.thumbnail_label.setAlignment(Qt.AlignCenter)
                        
                        self.thumbnail_label.setPixmap(pixmap.scaled(
                            self.widget_case_detail_video.width(),
                            self.widget_case_detail_video.height(),
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation
                        ))
                        self.thumbnail_label.show()
                        
                        # 재생 아이콘 상태 초기화 및 즉시 표시
                        self.play_icon_visible = False  # 상태 초기화
                        self._show_play_icon()
                        
                        # UI 업데이트 즉시 강제 적용
                        if hasattr(self, 'play_icon_label') and self.play_icon_label is not None:
                            self.play_icon_label.show()
                            self.play_icon_label.raise_()
                        self.widget_case_detail_video.update()
                    else:
                        if DEBUG:
                            print(f"{DEBUG_TAG['ERR']} 썸네일 이미지 로드 실패: {full_image_path}")
                else:
                    if DEBUG:
                        print(f"{DEBUG_TAG['ERR']} 썸네일 이미지 파일을 찾을 수 없음: {full_image_path}")
            
            # 비디오 경로 확인 및 준비 (재생은 안함, 재생 버튼 클릭 시에만 재생)
            video_path = self.selected_log.get("video_path", "")
            if video_path:
                full_video_path = os.path.join(self.base_path, video_path)
                if os.path.exists(full_video_path):
                    # 미디어 컨트롤 활성화
                    self.pushButton_run.setText("▶")  # 재생 버튼으로 설정
                    self.pushButton_run.setEnabled(True)
                    self.pushButton_stop.setEnabled(False)  # 아직 재생 시작 전이므로 정지 비활성화
                    # seek 버튼은 항상 활성화 (정지 상태에서도 프레임 업데이트 가능)
                    self.pushButton_seek_forward.setEnabled(True)
                    self.pushButton_seek_backward.setEnabled(True)
                    
                    # VLC 미디어 설정 (재생은 안함)
                    media = self.instance.media_new(full_video_path)
                    
                    # 미디어 파싱 방법 개선 (VLC 인터페이스 문제로 인한 메타데이터 추출 실패 우회)
                    try:
                        # 메타데이터 파싱 설정 (timeout 늘림)
                        media.parse_with_options(vlc.MediaParseFlag.local, 1000)
                        
                        # 파싱이 완료될 때까지 최대 1초 대기 (강제 동기화)
                        for _ in range(10):  # 최대 1초 (100ms * 10)
                            parse_status = media.get_parsed_status()
                            if parse_status == vlc.MediaParsedStatus.done:
                                if DEBUG:
                                    print(f"{DEBUG_TAG['RECV']} 미디어 파싱 성공")
                                break
                            # 짧은 대기 후 다시 확인
                            time.sleep(0.1)
                        
                        if parse_status != vlc.MediaParsedStatus.done and DEBUG:
                            print(f"{DEBUG_TAG['RECV']} 미디어 파싱 상태: {parse_status}")
                    except Exception as parse_err:
                        if DEBUG:
                            print(f"{DEBUG_TAG['ERR']} 미디어 파싱 중 오류: {parse_err}")
                    
                    # 미디어를 플레이어에 설정
                    self.mediaPlayer.set_media(media)
                    
                    # 볼륨 설정 초기화
                    volume = self.horizontalSlider_volume.value()
                    self.mediaPlayer.audio_set_volume(volume)
                    
                    # 메타데이터 로드 및 UI 업데이트
                    self._update_media_info()
                    
                    # VLC 미디어 플레이어 상태 관리 (Ready로 유지)
                    # 일시정지 상태로 전환되지 않도록 정지(stop) 상태로 명시적 설정
                    self.mediaPlayer.stop()
                    
                    # 상태 표시 명시적으로 "Ready"로 설정
                    self.label_media_status.setText("Ready")
                    self.is_playing = False
                    
                    # 썸네일 표시 상태 유지 (첫 프레임 표시하지 않고 썸네일만 표시)
                    # 재생 버튼을 눌렀을 때만 비디오 프레임이 표시되도록 함
                    
                    # 타이머가 활성화되어 있다면 중지
                    # Ready 상태에서는 타이머를 실행하지 않음 (사용자가 재생 버튼을 누를 때만 시작)
                    if hasattr(self, 'timer') and self.timer.isActive():
                        self.timer.stop()
                    
                    # Ready 상태에서 플래그 설정
                    # 이 플래그들은 재생 버튼을 누를 때까지 유지되며, update_time_labels에서 상태가 Paused로 변경되는 것을 방지
                    self.initial_state = True  # 초기 Ready 상태 표시
                    self.ready_state_active = True  # Ready 상태 활성화 - 이 플래그가 True면 항상 Ready 상태 유지
                    
                    # 비디오 영역 및 재생 아이콘 상태 최종 확인
                    if hasattr(self, 'thumbnail_label') and self.thumbnail_label.isVisible():
                        # 썸네일이 표시된 경우 확실히 보이도록 함
                        self.thumbnail_label.raise_()
                    else:
                        # 재생 상태를 확실히 표시하기 위해 재생 아이콘 리셋 및 표시
                        if hasattr(self, 'play_icon_label'):
                            self.play_icon_label.hide()
                            self.play_icon_label = None
                        self._show_play_icon()
                    
                    if DEBUG:
                        print(f"{DEBUG_TAG['RECV']} 비디오 재생 준비 완료: {full_video_path}")
                else:                    # 상태 표시 초기화 (영어로 표시)
                    self.label_media_status.setText("No Video File")
                    self.label_running_time.setText("00:00:00 / 00:00:00")
                    
                    # 미디어 컨트롤 비활성화
                    self.pushButton_run.setEnabled(False)
                    self.pushButton_stop.setEnabled(False)
                    self.pushButton_seek_forward.setEnabled(False)
                    self.pushButton_seek_backward.setEnabled(False)
                    
                    if DEBUG:
                        print(f"{DEBUG_TAG['ERR']} 비디오 파일을 찾을 수 없음: {full_video_path}")
            else:
                # 상태 표시 초기화 (영어로 표시)
                self.label_media_status.setText("No Video Info")
                self.label_running_time.setText("00:00:00 / 00:00:00")
                
                # 미디어 컨트롤 비활성화
                self.pushButton_run.setEnabled(False)
                self.pushButton_stop.setEnabled(False)
                self.pushButton_seek_forward.setEnabled(False)
                self.pushButton_seek_backward.setEnabled(False)       

                if DEBUG:
                    print(f"{DEBUG_TAG['ERR']} 비디오 경로가 없습니다: {video_path}")            
                
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 상세 정보 표시 실패: {e}")
                print(traceback.format_exc())
    
    def play_video(self, video_path):
        """비디오 파일 재생"""
        try:
            if not os.path.exists(video_path):
                if DEBUG:
                    print(f"{DEBUG_TAG['ERR']} 비디오 파일을 찾을 수 없음: {video_path}")
                QMessageBox.warning(self, "파일 없음", f"비디오 파일을 찾을 수 없습니다.\n{video_path}")
                return
                
            if DEBUG:
                print(f"{DEBUG_TAG['SEND']} 비디오 파일 재생 시도: {video_path}")
            
            # QMediaPlayer를 사용하여 내부적으로 비디오 재생
            media_content = QMediaContent(QUrl.fromLocalFile(video_path))
            self.mediaPlayer.setMedia(media_content)
            self.mediaPlayer.play()
            
            if DEBUG:
                print(f"{DEBUG_TAG['SEND']} 비디오 재생 시작")
                
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 비디오 재생 처리 실패: {e}")
                print(traceback.format_exc())
            QMessageBox.warning(self, "오류", f"비디오 재생 처리 중 오류가 발생했습니다.\n{str(e)}")
    
    def stop_video_playback(self):
        """비디오 재생 중지"""
        # VLC 미디어 플레이어 중지
        if hasattr(self, 'mediaPlayer'):
            # 현재 미디어가 있는지 확인
            media = self.mediaPlayer.get_media()
            
            # 재생 중지
            self.mediaPlayer.stop()
            
            # 타이머가 실행 중이면 중지
            if hasattr(self, 'timer') and self.timer.isActive():
                self.timer.stop()
            
            # 재생 상태 업데이트
            self.is_playing = False
            
            # 재생 아이콘 가시성 상태도 업데이트
            self.play_icon_visible = False
            
            # 미디어 컨트롤 상태 업데이트
            self.pushButton_run.setText("▶")  # 재생 버튼으로 설정
            self.pushButton_run.setEnabled(True)
            self.pushButton_stop.setEnabled(False)
            self.pushButton_seek_forward.setEnabled(False)
            self.pushButton_seek_backward.setEnabled(False)
            
            # 상태 표시 초기화
            if hasattr(self, 'label_media_status'):
                self.label_media_status.setText("Stopped")
            if hasattr(self, 'label_running_time'):
                self.label_running_time.setText("00:00:00 / 00:00:00")
            
            # 슬라이더 초기화
            self.horizontalSlider_running_time.setValue(0)
            
            if DEBUG:
                print(f"{DEBUG_TAG['SEND']} 비디오 재생 중지")
    
    def resizeEvent(self, event):
        """위젯 크기 변경 이벤트 처리"""
        super().resizeEvent(event)
        
        # 비디오 위젯 크기 조정
        if hasattr(self, 'videoWidget') and hasattr(self, 'widget_case_detail_video'):
            self.videoWidget.setGeometry(self.widget_case_detail_video.rect())
            
        # 썸네일 크기 조정
        if hasattr(self, 'thumbnail_label') and hasattr(self, 'widget_case_detail_video'):
            self.thumbnail_label.setGeometry(self.widget_case_detail_video.rect())
            if hasattr(self, 'thumbnail_label') and self.thumbnail_label.pixmap():
                self.thumbnail_label.setPixmap(self.thumbnail_label.pixmap().scaled(
                    self.widget_case_detail_video.width(),
                    self.widget_case_detail_video.height(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                ))
                
        # 플레이 아이콘 크기 및 위치 조정
        if hasattr(self, 'play_icon_label') and hasattr(self, 'widget_case_detail_video'):
            play_icon_size = min(self.widget_case_detail_video.width(), self.widget_case_detail_video.height()) // 2
            self.play_icon_label.setFixedSize(play_icon_size, play_icon_size)
            self.play_icon_label.move(
                (self.widget_case_detail_video.width() - play_icon_size) // 2,
                (self.widget_case_detail_video.height() - play_icon_size) // 2
            )
            # 아이콘이 보이게 설정 - 크기 조정 후에도 보이게
            if hasattr(self, 'play_icon_visible') and self.play_icon_visible:
                self.play_icon_label.show()
                self.play_icon_label.raise_()
            
    def closeEvent(self, event):
        """위젯 종료 시 비디오 재생 중지 및 리소스 정리"""
        try:
            # 이벤트 핸들러 분리
            if hasattr(self, 'event_manager'):
                self.event_manager.event_detach(vlc.EventType.MediaPlayerEndReached)
                self.event_manager.event_detach(vlc.EventType.MediaPlayerTimeChanged)
                self.event_manager.event_detach(vlc.EventType.MediaPlayerLengthChanged)
                self.event_manager.event_detach(vlc.EventType.MediaPlayerPositionChanged)
                
            # 비디오 재생 중지
            self.stop_video_playback()
            
            # 타이머 정리
            if hasattr(self, 'timer') and self.timer.isActive():
                self.timer.stop()
                
            # 미디어 플레이어 릴리즈
            if hasattr(self, 'mediaPlayer'):
                self.mediaPlayer.release()
                
            # 인스턴스 릴리즈
            if hasattr(self, 'instance'):
                self.instance.release()
                
            if DEBUG:
                print(f"{DEBUG_TAG['INIT']} 미디어 플레이어 리소스 정리 완료")
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 리소스 정리 중 오류 발생: {e}")
                
        super().closeEvent(event)
        self.stop_video_playback()
        
        # 타이머 정리
        if hasattr(self, 'timer') and self.timer.isActive():
            self.timer.stop()
            
        super().closeEvent(event)
    
    def play_media(self):
        """미디어 재생 또는 재개 (현재는 toggle_playback으로 리다이렉트)"""
        # 호환성을 위해 유지하되 toggle_playback으로 리다이렉트
        self.toggle_playback()
    
    def pause_media(self):
        """미디어 일시 정지 (현재는 재생 중일 때만 toggle_playback으로 리다이렉트)"""

        if hasattr(self, 'mediaPlayer') and self.is_playing:
            self.toggle_playback()
    
    def stop_media(self):
        """미디어 정지 - 현재 프레임을 유지"""
        if hasattr(self, 'mediaPlayer'):
            # 비디오 정지
            self.mediaPlayer.stop()
            self.is_playing = False
            
            # 컨트롤 버튼 상태 업데이트
            self.pushButton_run.setText("▶")  # 재생 버튼으로 설정
            self.pushButton_run.setEnabled(True)
            self.pushButton_stop.setEnabled(False)

            # 탐색 버튼은 활성화 상태로 유지
            self.pushButton_seek_forward.setEnabled(True)
            self.pushButton_seek_backward.setEnabled(True)
            
            # 슬라이더 및 시간 표시 즉시 초기화
            self.horizontalSlider_running_time.setValue(0)
            self.label_running_time.setText("00:00:00 / 00:00:00")
            
            # 정지 상태 표시 (영어로 표시)
            self.label_media_status.setText("Stopped")
            
            # 현재 선택된 로그가 있으면 해당 이미지를 다시 가져와 썸네일로 표시 (초기 상태용)
            if self.selected_log:
                image_path = self.selected_log.get("image_path", "")
                if image_path:
                    full_image_path = os.path.join(self.base_path, image_path)
                    if os.path.exists(full_image_path):
                        # 이미지를 다시 로드
                        pixmap = QPixmap(full_image_path)
                        if not pixmap.isNull() and hasattr(self, 'thumbnail_label'):
                            self.thumbnail_label.setPixmap(pixmap.scaled(
                                self.widget_case_detail_video.width(),
                                self.widget_case_detail_video.height(),
                                Qt.KeepAspectRatio,
                                Qt.SmoothTransformation
                            ))
                            self.thumbnail_label.show()
                            
                            if DEBUG:
                                print(f"{DEBUG_TAG['RECV']} 정지 후 썸네일 이미지 재로드: {full_image_path}")
                        else:
                            if hasattr(self, 'thumbnail_label'):
                                self.thumbnail_label.clear()
                                self.thumbnail_label.hide()
            
            # 썸네일이 보이면 재생 아이콘도 표시
            if hasattr(self, 'thumbnail_label') and self.thumbnail_label.isVisible():
                self._show_play_icon()
            else:
                if hasattr(self, 'play_icon_label'):
                    self.play_icon_label.hide()
            
            # VLC marquee 재생 아이콘 비활성화
            self.mediaPlayer.video_set_marquee_int(vlc.VideoMarqueeOption.Enable, 0)
            
            if DEBUG:
                print(f"{DEBUG_TAG['SEND']} 미디어 정지")

    def restart_media(self):
        """미디어 처음부터 재생"""
        if hasattr(self, 'mediaPlayer'):
            self.mediaPlayer.stop()
            self.mediaPlayer.set_time(0)
            self.mediaPlayer.play()
            self.is_playing = True
            self.pushButton_run.setText("❚❚")  # 일시정지 버튼으로 변경
            
            # 타이머 시작 또는 재시작
            if not hasattr(self, 'timer') or not self.timer.isActive():
                self.timer = QTimer(self)
                self.timer.setInterval(1000)
                self.timer.timeout.connect(self.update_time_labels)
                self.timer.start()
                
            if DEBUG:
                print(f"{DEBUG_TAG['SEND']} 미디어 처음부터 재생")
    
    def set_volume(self, volume):
        """볼륨 설정"""
        if hasattr(self, 'mediaPlayer'):
            self.mediaPlayer.audio_set_volume(volume)
            if DEBUG:
                print(f"{DEBUG_TAG['SEND']} 볼륨 설정: {volume}%")
    
    def set_position(self, position):
        """재생 위치 설정 (슬라이더 이동 시 호출)"""
        if hasattr(self, 'mediaPlayer'):
            # 썸네일이 표시되어 있다면 숨김 (실제 비디오 프레임이 보이도록)
            if hasattr(self, 'thumbnail_label') and self.thumbnail_label.isVisible():
                self.thumbnail_label.hide()
                
            # 위치 설정
            self.mediaPlayer.set_time(position)
            
            # 일시정지 상태에서는 프레임 업데이트를 위해 강제로 프레임 이동 처리
            if not self.is_playing:
                self.mediaPlayer.pause()  # 프레임 업데이트를 위한 일시정지 갱신
                # 일시정지 상태에서는 즉시 재생 아이콘 표시 (슬라이더 조작 후)
                self._show_play_icon()
                self._show_play_icon()
            
            # 위치 설정 후 즉시 시간 표시 업데이트 (타이머 대기 없이)
            try:
                # 전체 길이
                total_duration = self.mediaPlayer.get_length()
                if total_duration <= 0:
                    total_duration = 0
                    
                # 시간 문자열 포맷팅
                position_sec = position // 1000
                duration_sec = total_duration // 1000
                
                pos_h = position_sec // 3600
                pos_m = (position_sec % 3600) // 60
                pos_s = position_sec % 60
                
                dur_h = duration_sec // 3600
                dur_m = (duration_sec % 3600) // 60
                dur_s = duration_sec % 60
                
                time_str = f"{pos_h:02d}:{pos_m:02d}:{pos_s:02d} / {dur_h:02d}:{dur_m:02d}:{dur_s:02d}"
                self.label_running_time.setText(time_str)
            except Exception as e:
                if DEBUG:
                    print(f"{DEBUG_TAG['ERR']} 시간 즉시 업데이트 오류: {e}")
            
            if DEBUG:
                print(f"{DEBUG_TAG['SEND']} 재생 위치 설정: {position}ms")
    
    def seek_forward(self):
        """현재 위치에서 5초 앞으로 이동"""
        if not hasattr(self, 'mediaPlayer'):
            return
            
        # 썸네일이 표시되어 있다면 숨김 (실제 비디오 프레임이 보이도록)
        if hasattr(self, 'thumbnail_label') and self.thumbnail_label.isVisible():
            self.thumbnail_label.hide()
            
        # 재생 중에서만 재생 아이콘 숨김 (일시정지 상태에서는 계속 표시)
        if self.is_playing:
            if hasattr(self, 'play_icon_label') and self.play_icon_label.isVisible():
                self.play_icon_label.hide()
                
            # VLC marquee 재생 아이콘 비활성화
            self.mediaPlayer.video_set_marquee_int(vlc.VideoMarqueeOption.Enable, 0)
            
        # 현재 위치 가져오기 (밀리초)
        current_position = self.mediaPlayer.get_time()
        if current_position < 0:
            current_position = 0
            
        new_position = current_position + 5000  # 5초(5000밀리초) 앞으로
        
        # 전체 길이보다 크면 영상 끝으로 이동
        total_duration = self.mediaPlayer.get_length()
        if total_duration > 0 and new_position > total_duration:
            new_position = total_duration
        
        # 정지 또는 일시정지 상태일 때 처리 방식 개선
        if not self.is_playing:
            # 재생 중이 아닐 때는 프레임 단위로 이동 (use_frame 옵션)
            # 1. 현재 위치에서 프레임을 가져오도록 설정 (frame-by-frame)
            media = self.mediaPlayer.get_media()
            
            # 2. 재생하지 않고 프레임 추출 - VLC의 frame-by-frame 기능 활용
            self.mediaPlayer.set_time(new_position)
            # VLC 플레이어에서 프레임 표시 강제 업데이트
            self.mediaPlayer.pause() 
            
            # 일시정지 상태에서 재생 아이콘 즉시 표시
            self._show_play_icon()
            
            # UI 업데이트 즉시 강제 적용
            if hasattr(self, 'play_icon_label') and self.play_icon_label is not None:
                self.play_icon_label.show()
                self.play_icon_label.raise_()
            self.widget_case_detail_video.update()
            
            self.mediaPlayer.next_frame()
        else:
            # 재생 중일 때는 일반적인 seek
            self.mediaPlayer.set_time(new_position)
            
        # 위치 설정 후 즉시 시간 표시 업데이트 (타이머 대기 없이)
        try:
            # 시간 문자열 포맷팅
            position_sec = new_position // 1000
            duration_sec = total_duration // 1000
            
            pos_h = position_sec // 3600
            pos_m = (position_sec % 3600) // 60
            pos_s = position_sec % 60
            
            dur_h = duration_sec // 3600
            dur_m = (duration_sec % 3600) // 60
            dur_s = duration_sec % 60
            
            time_str = f"{pos_h:02d}:{pos_m:02d}:{pos_s:02d} / {dur_h:02d}:{dur_m:02d}:{dur_s:02d}"
            self.label_running_time.setText(time_str)
            
            # 슬라이더 값도 즉시 업데이트
            self.horizontalSlider_running_time.setValue(new_position)
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 시간 즉시 업데이트 오류: {e}")
        
        if DEBUG:
            print(f"{DEBUG_TAG['SEND']} 5초 앞으로 이동: {current_position}ms → {new_position}ms")
    
    def seek_backward(self):
        """현재 위치에서 5초 뒤로 이동"""
        if not hasattr(self, 'mediaPlayer'):
            return
            
        # 썸네일이 표시되어 있다면 숨김 (실제 비디오 프레임이 보이도록)
        if hasattr(self, 'thumbnail_label') and self.thumbnail_label.isVisible():
            self.thumbnail_label.hide()
            
        # 재생 중에서만 재생 아이콘 숨김 (일시정지 상태에서는 계속 표시)
        if self.is_playing:
            if hasattr(self, 'play_icon_label') and self.play_icon_label.isVisible():
                self.play_icon_label.hide()
                
            # VLC marquee 재생 아이콘 비활성화
            self.mediaPlayer.video_set_marquee_int(vlc.VideoMarqueeOption.Enable, 0)
            
        # 현재 위치 가져오기 (밀리초)
        current_position = self.mediaPlayer.get_time()
        if current_position < 0:
            current_position = 0
            
        new_position = current_position - 5000  # 5초(5000밀리초) 뒤로
        
        # 0보다 작으면 영상 처음으로 이동
        if new_position < 0:
            new_position = 0
            
        # 정지 또는 일시정지 상태일 때 처리 방식 개선
        if not self.is_playing:
            # 재생 중이 아닐 때는 프레임 단위로 이동 (use_frame 옵션)
            # 1. 현재 위치에서 프레임을 가져오도록 설정 (frame-by-frame)
            media = self.mediaPlayer.get_media()
            
            # 2. 재생하지 않고 프레임 추출 - VLC의 frame-by-frame 기능 활용
            self.mediaPlayer.set_time(new_position)
            # VLC 플레이어에서 프레임 표시 강제 업데이트
            self.mediaPlayer.pause()
            
            # 일시정지 상태에서 재생 아이콘 즉시 표시
            self._show_play_icon()
            
            # UI 업데이트 즉시 강제 적용
            if hasattr(self, 'play_icon_label') and self.play_icon_label is not None:
                self.play_icon_label.show()
                self.play_icon_label.raise_()
            self.widget_case_detail_video.update()
            
            self.mediaPlayer.next_frame()
        else:
            # 재생 중일 때는 일반적인 seek
            self.mediaPlayer.set_time(new_position)
        
        # 위치 설정 후 즉시 시간 표시 업데이트 (타이머 대기 없이)
        try:
            # 전체 길이
            total_duration = self.mediaPlayer.get_length()
            if total_duration <= 0:
                total_duration = 0
                
            # 시간 문자열 포맷팅
            position_sec = new_position // 1000
            duration_sec = total_duration // 1000
            
            pos_h = position_sec // 3600
            pos_m = (position_sec % 3600) // 60
            pos_s = position_sec % 60
            
            dur_h = duration_sec // 3600
            dur_m = (duration_sec % 3600) // 60
            dur_s = duration_sec % 60
            
            time_str = f"{pos_h:02d}:{pos_m:02d}:{pos_s:02d} / {dur_h:02d}:{dur_m:02d}:{dur_s:02d}"
            self.label_running_time.setText(time_str)
            
            # 슬라이더 값도 즉시 업데이트
            self.horizontalSlider_running_time.setValue(new_position)
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 시간 즉시 업데이트 오류: {e}")
        
        if DEBUG:
            print(f"{DEBUG_TAG['SEND']} 5초 뒤로 이동: {current_position}ms → {new_position}ms")
    
    def toggle_playback(self):
        """재생/일시정지 토글 기능"""
        if not hasattr(self, 'mediaPlayer'):
            return
            
        if self.is_playing:
            # 재생 중이면 일시정지
            self.mediaPlayer.pause()
            self.is_playing = False
            self.pushButton_run.setText("▶")  # 재생 버튼으로 변경
            self.label_media_status.setText("Paused")  # 일시정지 상태로 표시
            
            # 썸네일 제거 (비디오 프레임 유지를 위해)
            if hasattr(self, 'thumbnail_label') and self.thumbnail_label.isVisible():
                self.thumbnail_label.hide()
            
            # 강제로 재생 아이콘 상태 리셋 (항상 제거 후 다시 생성)
            if hasattr(self, 'play_icon_label'):
                self.play_icon_label.hide()
                # 메모리 해제를 위해 삭제
                self.play_icon_label.deleteLater()
                self.play_icon_label = None
            
            # 재생 아이콘 상태 초기화
            self.play_icon_visible = False
            
            # 재생 아이콘 즉시 표시 (딜레이 없이 바로 적용)
            self._show_play_icon()
            
            # UI 업데이트 강제 적용
            self.widget_case_detail_video.update()
                
            # VLC marquee 재생 아이콘 비활성화
            self.mediaPlayer.video_set_marquee_int(vlc.VideoMarqueeOption.Enable, 0)
            
            # 일시정지 상태에서도 seek 버튼 활성화 유지
            self.pushButton_seek_forward.setEnabled(True)
            self.pushButton_seek_backward.setEnabled(True)
            
            if DEBUG:
                print(f"{DEBUG_TAG['SEND']} 미디어 일시 정지 (현재 프레임 유지)")
        else:
            # 정지 또는 일시정지 상태면 재생
            if not self.mediaPlayer.get_media():
                if DEBUG:
                    print(f"{DEBUG_TAG['SEND']} 재생할 미디어가 없음")
                return
            
            # 썸네일 이미지가 있다면 숨김
            if hasattr(self, 'thumbnail_label') and self.thumbnail_label.isVisible():
                self.thumbnail_label.hide()
            
            # 재생 아이콘 숨김
            if hasattr(self, 'play_icon_label') and self.play_icon_label.isVisible():
                self.play_icon_label.hide()
                self.play_icon_visible = False
                
            # 재생 아이콘 마커퀴 제거
            self.mediaPlayer.video_set_marquee_int(vlc.VideoMarqueeOption.Enable, 0)
            
            # 비디오 재생 시작
            self.mediaPlayer.play()
            self.is_playing = True
            
            # Ready 상태에서 벗어나므로 관련 플래그들 모두 해제
            if hasattr(self, 'initial_state'):
                self.initial_state = False
            if hasattr(self, 'ready_state_active'):
                self.ready_state_active = False  # Ready 상태 비활성화 (이제 재생 중이므로)
                
            self.pushButton_run.setText("❚❚")  # 일시정지 버튼으로 변경
            
            # 컨트롤 버튼 활성화
            self.pushButton_stop.setEnabled(True)
            self.pushButton_seek_forward.setEnabled(True)
            self.pushButton_seek_backward.setEnabled(True)
            
            # 타이머 시작
            if not hasattr(self, 'timer') or not self.timer.isActive():
                self.timer = QTimer(self)
                self.timer.setInterval(500)  # 0.5초 간격으로 업데이트
                self.timer.timeout.connect(self.update_time_labels)
                self.timer.start()
                
            if DEBUG:
                print(f"{DEBUG_TAG['SEND']} 미디어 재생 시작 (썸네일 숨김)")
    
    def update_time_labels(self):
        """VLC 미디어 재생 시간 업데이트"""
        if not hasattr(self, 'mediaPlayer'):
            return
            
        try:
            # 현재 위치(밀리초) - 재생 중이 아니어도 현재 위치 표시 (즉시 반영)
            position = self.mediaPlayer.get_time()
            if position < 0:
                position = 0
                
            # 전체 길이(밀리초)
            duration = self.mediaPlayer.get_length()
            if duration <= 0:
                duration = 0
                
            # 슬라이더 범위 업데이트
            if self.horizontalSlider_running_time.maximum() != duration:
                self.horizontalSlider_running_time.setRange(0, duration)
                
            # 슬라이더 업데이트 (중복 이벤트 방지를 위해 값이 변경된 경우만)
            current_slider_value = self.horizontalSlider_running_time.value()
            if abs(current_slider_value - position) > 500:  # 0.5초 이상 차이가 날 때만 업데이트
                self.horizontalSlider_running_time.setValue(position)
            
            # 시간 문자열 포맷팅
            position_sec = position // 1000
            duration_sec = duration // 1000
            
            pos_h = position_sec // 3600
            pos_m = (position_sec % 3600) // 60
            pos_s = position_sec % 60
            
            dur_h = duration_sec // 3600
            dur_m = (duration_sec % 3600) // 60
            dur_s = duration_sec % 60
            
            time_str = f"{pos_h:02d}:{pos_m:02d}:{pos_s:02d} / {dur_h:02d}:{dur_m:02d}:{dur_s:02d}"
            self.label_running_time.setText(time_str)
            
            # 미디어 상태 표시 (영어로 표시)
            if self.mediaPlayer.is_playing():
                self.label_media_status.setText("Playing")
                self.pushButton_run.setText("❚❚")  # 일시정지 버튼으로 표시
                self.pushButton_stop.setEnabled(True)
                self.pushButton_seek_forward.setEnabled(True)
                self.pushButton_seek_backward.setEnabled(True)
                
                # 재생 중에는 썸네일과 아이콘 모두 숨김
                if hasattr(self, 'thumbnail_label') and self.thumbnail_label.isVisible():
                    self.thumbnail_label.hide()
                
                if hasattr(self, 'play_icon_label') and self.play_icon_label.isVisible():
                    self.play_icon_label.hide()
                
                # 재생 중일 때는 재생 마커퀴 숨기기
                self.mediaPlayer.video_set_marquee_int(vlc.VideoMarqueeOption.Enable, 0)
            else:
                if position >= duration - 500 and duration > 0: # 거의 끝까지 재생됨
                    self.label_media_status.setText("Finished")
                    self.pushButton_run.setText("▶")  # 재생 버튼으로 표시
                    self.is_playing = False
                    
                    # 컨트롤 버튼 상태 업데이트 (정지 시에도 seek 버튼은 활성화)
                    self.pushButton_seek_forward.setEnabled(True)
                    self.pushButton_seek_backward.setEnabled(True)
                    
                    # 영상이 끝났을 때는 마지막 프레임 유지 (썸네일 표시 X)
                    if hasattr(self, 'thumbnail_label') and self.thumbnail_label.isVisible():
                        self.thumbnail_label.hide()
                        
                    # 영상이 끝났을 때 재생 아이콘 표시 (재생 준비됨을 알림)
                    self._show_play_icon()
                        
                    # 마커퀴 재생 아이콘도 표시하지 않음
                    self.mediaPlayer.video_set_marquee_int(vlc.VideoMarqueeOption.Enable, 0)
                    
                elif not self.is_playing:
                    # 초기 Ready 상태인 경우는 상태를 변경하지 않음
                    if hasattr(self, 'initial_state') and self.initial_state:
                        # Ready 상태 유지 - 절대 변경하지 않음
                        self.label_media_status.setText("Ready")
                    elif hasattr(self, 'ready_state_active') and self.ready_state_active:
                        # ready_state_active가 True인 경우도 Ready 상태 유지
                        self.label_media_status.setText("Ready")
                    else:
                        # 그 외에는 Paused 상태로 설정 (일시정지 버튼을 누른 경우만)
                        self.label_media_status.setText("Paused")
                    
                    # 일시정지 상태에서는 현재 프레임 유지 (썸네일 표시 X)
                    if hasattr(self, 'thumbnail_label') and self.thumbnail_label.isVisible():
                        self.thumbnail_label.hide()
                        
                    # 일시정지 상태에서도 재생 아이콘 표시
                    self._show_play_icon()
                        
                    # 일시정지 상태에서는 마커퀴 재생 아이콘도 표시하지 않음
                    self.mediaPlayer.video_set_marquee_int(vlc.VideoMarqueeOption.Enable, 0)
                    
                    # 컨트롤 버튼 상태 업데이트 (일시정지 시에도 seek 버튼은 활성화)
                    self.pushButton_seek_forward.setEnabled(True)
                    self.pushButton_seek_backward.setEnabled(True)
                    
            # 타이머는 항상 활성 상태 유지 (위치 정보 계속 업데이트)
            
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 시간 업데이트 오류: {e}")
                print(traceback.format_exc())
    
    def _update_media_info(self):
        """미디어 정보 즉시 업데이트 (로그 선택 시 호출됨) - parse_with_options 활용"""
        if not hasattr(self, 'mediaPlayer') or not self.mediaPlayer.get_media():
            return
            
        media = self.mediaPlayer.get_media()
        
        # 미디어 정보 가져오기 시도 (여러 번 시도)
        duration = 0
        try:
            # 파싱 상태 확인
            parse_status = media.get_parsed_status()
            if parse_status != vlc.MediaParsedStatus.done:
                if DEBUG:
                    print(f"{DEBUG_TAG['RECV']} 미디어 파싱 상태 불완전: {parse_status}, 재파싱 시도")
                
                # 여러 번 파싱 시도 (최대 3회)
                for attempt in range(3):
                    parse_result = media.parse_with_options(vlc.MediaParseFlag.local, 800)
                    time.sleep(0.3)  # 파싱 시간 부여
                    
                    # 파싱 후 결과 확인
                    new_status = media.get_parsed_status()
                    if new_status == vlc.MediaParsedStatus.done:
                        if DEBUG:
                            print(f"{DEBUG_TAG['RECV']} {attempt+1}회 시도에 미디어 파싱 성공")
                        break
                    
                    if parse_result != 0 and DEBUG:
                        print(f"{DEBUG_TAG['ERR']} {attempt+1}회 미디어 파싱 시도 실패: {parse_result}")
            
            # 파싱 성공 후 길이 가져오기
            duration = media.get_duration()
            
            # 미디어가 준비된 상태에서 VLC가 자동으로 일시정지하는 문제 방지
            # 플레이어를 명시적으로 정지 상태로 만들고 상태를 Ready로 설정
            self.mediaPlayer.stop()
            
            # is_playing 상태를 확실히 False로 설정
            self.is_playing = False
            
            # 상태를 명확하게 "Ready"로 설정 (타이머가 이 값을 덮어쓰지 않도록 내부 변수 추가)
            self.label_media_status.setText("Ready")
            self.initial_state = True  # 초기 Ready 상태임을 표시하는 플래그
            
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 미디어 정보 가져오기 실패: {e}")
        
        # 길이가 없는 경우 기본값 사용
        if duration <= 0:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 미디어 길이를 가져올 수 없음, 재생 시 업데이트됨")
            duration = 0
            
        # 슬라이더 범위 설정
        self.horizontalSlider_running_time.setRange(0, duration)
        self.horizontalSlider_running_time.setValue(0)
        
        # 시간 문자열 포맷팅
        duration_sec = duration // 1000
        dur_h = duration_sec // 3600
        dur_m = (duration_sec % 3600) // 60
        dur_s = duration_sec % 60
        
        time_str = f"00:00:00 / {dur_h:02d}:{dur_m:02d}:{dur_s:02d}"
        self.label_running_time.setText(time_str)
        
        # 미디어 상태 업데이트
        self.label_media_status.setText("Ready")
            
        # 컨트롤 버튼 상태 업데이트
        self.pushButton_seek_forward.setEnabled(True)
        self.pushButton_seek_backward.setEnabled(True)
            
        # 썸네일이 보이는 상태에서는 재생 아이콘도 표시
        if hasattr(self, 'thumbnail_label') and self.thumbnail_label.isVisible():
            self._show_play_icon()
        
        # 디버그 정보 출력
        if DEBUG:
            print(f"{DEBUG_TAG['RECV']} 미디어 메타데이터 로드 완료: 길이={duration}ms")
            # FPS, 트랙 수 등은 get_fps() 대신 생략 또는 다른 방법 필요 (여기선 생략)

    def eventFilter(self, obj, event):
        """이벤트 필터 - 비디오 영역 클릭 처리"""
        from PyQt5.QtCore import QEvent
        
        if obj == self.widget_case_detail_video and event.type() == QEvent.MouseButtonPress:
            # 비디오 위젯 클릭 시 재생/일시정지 토글
            if DEBUG:
                print(f"{DEBUG_TAG['SEND']} 비디오 영역 클릭 - 재생/일시정지 토글")
            
            # 비디오가 준비되어 있을 때만 재생 토글 처리
            if hasattr(self, 'mediaPlayer') and self.mediaPlayer.get_media():
                # 토글 전에 현재 상태 저장
                was_playing = self.is_playing
                
                # 토글 실행
                self.toggle_playback()
                
                # 재생->일시정지로 변경된 경우, 아이콘이 즉시 표시되도록 강제 처리
                if was_playing and not self.is_playing:
                    # 확실하게 재생 아이콘 표시
                    self._show_play_icon()
                
                return True  # 이벤트 처리됨
                
        return super().eventFilter(obj, event)  # 기본 이벤트 처리
    
    def _on_media_end_reached(self, event):
        """미디어 재생 종료 이벤트 처리"""
        if DEBUG:
            print(f"{DEBUG_TAG['RECV']} 미디어 재생 종료됨")
            
        # 메인 스레드에서 UI 업데이트하기 위한 QTimer 사용
        QTimer.singleShot(0, self._handle_media_end_in_main_thread)
    
    def _handle_media_end_in_main_thread(self):
        """미디어 종료 이벤트를 메인 스레드에서 처리"""
        # 재생 상태 업데이트
        self.is_playing = False
        
        # UI 업데이트
        self.pushButton_run.setText("▶")  # 재생 버튼으로 변경
        self.label_media_status.setText("Finished")  # 상태 표시
        
        # 컨트롤 버튼 상태 업데이트 (seek 버튼 활성 유지)
        self.pushButton_seek_forward.setEnabled(True)
        self.pushButton_seek_backward.setEnabled(True)
        
        # 재생이 종료되어도 마지막 프레임 유지 (썸네일 표시 X)
        if hasattr(self, 'thumbnail_label') and self.thumbnail_label.isVisible():
            self.thumbnail_label.hide()
            
        # 비디오 프레임을 표시하기 위해 미디어 플레이어를 처음으로 되돌리고 재생 후 즉시 중지
        self.mediaPlayer.set_time(0)
        self.mediaPlayer.play()
        time.sleep(0.1)  # 첫 프레임이 로드될 시간 부여
        self.mediaPlayer.pause()
            
        # 재생 아이콘을 표시하여 재생 가능함을 알림 (완전히 새로 생성)
        if hasattr(self, 'play_icon_label') and self.play_icon_label is not None:
            self.play_icon_label.hide()
            self.play_icon_label.deleteLater()
            self.play_icon_label = None
        
        self._show_play_icon()
            
        # 마커퀴도 비활성화
        self.mediaPlayer.video_set_marquee_int(vlc.VideoMarqueeOption.Enable, 0)
    
    def _on_time_changed(self, event):
        """미디어 재생 시간이 변경되었을 때의 이벤트 처리"""
        # 슬라이더와 시간 표시는 타이머로 처리하므로 여기서는 추가 작업 없음
        pass
    
    def _on_length_changed(self, event):
        """미디어 총 길이 정보가 변경되었을 때 이벤트 처리"""
        # 미디어 파싱이 완료되어 길이 정보가 업데이트됨
        length = self.mediaPlayer.get_length()
        if length > 0 and DEBUG:
            print(f"{DEBUG_TAG['RECV']} 미디어 길이 업데이트됨: {length}ms")
            
        # 메인 스레드에서 UI 업데이트
        QTimer.singleShot(0, lambda: self.horizontalSlider_running_time.setRange(0, length))
    
    def _on_position_changed(self, event):
        """미디어 재생 위치가 변경되었을 때의 이벤트 처리"""
        # 슬라이더와 시간 표시는 타이머로 처리하므로 여기서는 추가 작업 없음
        pass
    
    def _show_play_icon(self):
        """일시정지/정지 상태에서 재생 아이콘 표시"""
        # 플레이어가 재생 중이면 아이콘을 표시하지 않음
        if self.is_playing:
            if hasattr(self, 'play_icon_label') and self.play_icon_label is not None:
                self.play_icon_label.hide()
            self.play_icon_visible = False
            return
            
        # 이미 표시된 아이콘이 있으면 보이게 하고 앞으로 가져오기만 함
        if hasattr(self, 'play_icon_visible') and self.play_icon_visible:
            if hasattr(self, 'play_icon_label') and self.play_icon_label is not None:
                self.play_icon_label.show()
                self.play_icon_label.raise_()
                return
                
        # 기존 아이콘이 있으면 완전히 제거 (새로 생성)
        if hasattr(self, 'play_icon_label') and self.play_icon_label is not None:
            try:
                self.play_icon_label.hide()
                self.play_icon_label.deleteLater()
            except:
                pass
            self.play_icon_label = None
            
        # 새로운 아이콘 생성 - 배경 어둡게 설정 (검정색 + 높은 투명도)
        self.play_icon_label = QLabel(self.widget_case_detail_video)
        self.play_icon_label.setStyleSheet("""
            background-color: rgba(0, 0, 0, 0.7); 
            color: white; 
            font-size: 60px; 
            padding: 10px;
            border-radius: 50%;
        """)
        self.play_icon_label.setAlignment(Qt.AlignCenter)
        self.play_icon_label.setText("▶")
            
        # 영상 영역에 맞게 크기 조정 (더 크게 설정)
        play_icon_size = min(self.widget_case_detail_video.width(), self.widget_case_detail_video.height()) // 2
        self.play_icon_label.setFixedSize(play_icon_size, play_icon_size)
        self.play_icon_label.move(
            (self.widget_case_detail_video.width() - play_icon_size) // 2,
            (self.widget_case_detail_video.height() - play_icon_size) // 2
        )
        
        # 반드시 맨 앞으로 표시 (다른 위젯보다 위에 표시)
        self.play_icon_label.raise_()
        self.play_icon_label.show()
        self.play_icon_visible = True
        
        # Qt 이벤트 루프에 업데이트 요청을 전달하여 즉시 화면에 표시되도록 함
        self.widget_case_detail_video.update()
        
        # 강제로 즉시 처리하도록 이벤트를 처리
        from PyQt5.QtWidgets import QApplication
        QApplication.processEvents()
        
        if DEBUG and not hasattr(self, 'last_icon_debug_log') or time.time() - self.last_icon_debug_log > 1:
            print(f"{DEBUG_TAG['SEND']} 재생 아이콘 표시")
            self.last_icon_debug_log = time.time()
