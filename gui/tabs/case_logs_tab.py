#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Case Logs Tab Module
로그 조회 탭 UI 및 로직 구현
"""

import os
import traceback
import subprocess
from datetime import datetime
from PyQt5.QtWidgets import (QWidget, QTableWidgetItem, QHeaderView, QMessageBox)
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtCore import Qt, QDateTime, QUrl
from PyQt5.uic import loadUi
# 비디오 재생을 위한 추가 imports
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget

# 디버그 모드
DEBUG = True

# 디버그 태그
DEBUG_TAG = {
    'INIT': '[초기화]',
    'CONN': '[연결]',
    'RECV': '[수신]',
    'SEND': '[전송]',
    'FILTER': '[필터]',
    'ERR': '[오류]'
}

# 탭 내부 상태 관리를 위한 상수들
# (서버 관련 상수는 메인윈도우로 이동함)

class CaseLogsTab(QWidget):
    """
    사건 로그 조회 탭 클래스
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
        
        # 콤보박스 초기화
        self.populate_comboboxes()
        
        # 테이블 업데이트
        self.update_table()
        
    def initUI(self):
        """UI 초기화"""
        try:
            # UI 파일 로드
            loadUi("gui/ui/case_logs_tap4.ui", self)
            
            # 테이블 설정
            self.tableWidget.setColumnCount(15)
            self.tableWidget.setHorizontalHeaderLabels([
                "case_id", "start_time", "end_time", "case_type", "detection_type", 
                "robot_id", "location", "user_id", "is_ignored", "is_119_reported", 
                "is_112_reported", "is_illegal_warned", "is_danger_warned", 
                "is_emergency_warned", "is_case_closed"
            ])
            
            # 테이블 열 너비 자동 조정
            self.tableWidget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            self.tableWidget.horizontalHeader().setStretchLastSection(False)
            
            # 기본 인덱스(행번호) 숨기기
            self.tableWidget.verticalHeader().setVisible(False)
            
            # 비디오 위젯 설정 - QWidget을 QVideoWidget으로 대체
            self.videoWidget = QVideoWidget(self.widget_case_detail_video)
            self.videoWidget.setGeometry(self.widget_case_detail_video.rect())
            self.videoWidget.setObjectName("videoWidget")
            self.videoWidget.show()
            
            # 미디어 플레이어 초기화
            self.mediaPlayer = QMediaPlayer(self)
            self.mediaPlayer.setVideoOutput(self.videoWidget)
            
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
        
        # 로그 데이터가 없으면 메시지 표시
        if not self.logs:
            QMessageBox.information(self, "데이터 없음", "로그 데이터가 없습니다.\n실제 DB에 데이터가 있는지 확인하세요.")
        
    def populate_comboboxes(self):
        """콤보박스 옵션 채우기"""
        try:
            if DEBUG:
                print(f"{DEBUG_TAG['INIT']} 콤보박스 옵션 설정")
                
            # 케이스 타입 콤보박스
            self.comboBox_case_type.clear()
            self.comboBox_case_type.addItem("All Case Types")
            case_types = sorted(set(log.get("case_type", "") for log in self.logs if log.get("case_type")))
            self.comboBox_case_type.addItems(case_types)
            
            # 탐지 타입 콤보박스
            self.comboBox_detection_type.clear()
            self.comboBox_detection_type.addItem("All Detection Types")
            detection_types = sorted(set(log.get("detection_type", "") for log in self.logs if log.get("detection_type")))
            self.comboBox_detection_type.addItems(detection_types)
            
            # 로봇 ID 콤보박스
            self.comboBox_robot_id.clear()
            self.comboBox_robot_id.addItem("All Robots")
            robot_ids = sorted(set(log.get("robot_id", "") for log in self.logs if log.get("robot_id")))
            robot_ids = sorted(robot_ids)
            self.comboBox_robot_id.addItems(robot_ids)
            
            # 위치 콤보박스
            self.comboBox_location_id.clear()
            self.comboBox_location_id.addItem("All Locations")
            locations = sorted(set(str(log.get("location", "")) for log in self.logs if log.get("location") is not None))
            self.comboBox_location_id.addItems(locations)
            
            # 사용자 계정 콤보박스
            self.comboBox_user_account.clear()
            self.comboBox_user_account.addItem("All Users")
            user_ids = sorted(set(log.get("user_id", "") for log in self.logs if log.get("user_id")))
            self.comboBox_user_account.addItems(user_ids)
            
            # 액션 타입 콤보박스
            self.comboBox_action_type.clear()
            self.comboBox_action_type.addItem("All Actions")
            action_types = [
                "119_report", "112_report", "case_closed", 
                "danger_warning", "emergency_warning", "illegal_warning"
            ]
            self.comboBox_action_type.addItems(action_types)
            
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
                case_type = log.get("case_type", "Unknown")
                detection_type = log.get("detection_type", "Unknown")
                robot_id = log.get("robot_id", "Unknown")
                location = log.get("location", "Unknown")
                user_id = log.get("user_id", "Unknown")
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
                
                # 테이블에 아이템 추가
                self.tableWidget.setItem(row, 0, QTableWidgetItem(case_id))
                self.tableWidget.setItem(row, 1, QTableWidgetItem(formatted_start))
                self.tableWidget.setItem(row, 2, QTableWidgetItem(formatted_end))
                self.tableWidget.setItem(row, 3, QTableWidgetItem(case_type))
                self.tableWidget.setItem(row, 4, QTableWidgetItem(detection_type))
                self.tableWidget.setItem(row, 5, QTableWidgetItem(robot_id))
                self.tableWidget.setItem(row, 6, QTableWidgetItem(location))
                self.tableWidget.setItem(row, 7, QTableWidgetItem(user_id))
                self.tableWidget.setItem(row, 8, QTableWidgetItem(is_ignored))
                self.tableWidget.setItem(row, 9, QTableWidgetItem(is_119_reported))
                self.tableWidget.setItem(row, 10, QTableWidgetItem(is_112_reported))
                self.tableWidget.setItem(row, 11, QTableWidgetItem(is_illegal_warned))
                self.tableWidget.setItem(row, 12, QTableWidgetItem(is_danger_warned))
                self.tableWidget.setItem(row, 13, QTableWidgetItem(is_emergency_warned))
                self.tableWidget.setItem(row, 14, QTableWidgetItem(is_case_closed))
                
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
            
            # 선택된 필터 값 가져오기
            selected_case_type = self.comboBox_case_type.currentText() if self.comboBox_case_type.currentIndex() > 0 else None
            selected_detection_type = self.comboBox_detection_type.currentText() if self.comboBox_detection_type.currentIndex() > 0 else None
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
                filtered = [log for log in filtered if log.get("case_type") == selected_case_type]
            
            # 탐지 타입 필터링
            if selected_detection_type:
                filtered = [log for log in filtered if log.get("detection_type") == selected_detection_type]
            
            # 로봇 ID 필터링
            if selected_robot_id:
                filtered = [log for log in filtered if log.get("robot_id") == selected_robot_id]
            
            # 위치 필터링
            if selected_location_id:
                filtered = [log for log in filtered if log.get("location") == selected_location_id]
            
            # 사용자 계정 필터링
            if selected_user_account:
                filtered = [log for log in filtered if log.get("user_id") == selected_user_account]
            
            # 액션 타입 필터링
            if selected_action_type:
                if selected_action_type == "119_report":
                    filtered = [log for log in filtered if log.get("is_119_reported") == 1]
                elif selected_action_type == "112_report":
                    filtered = [log for log in filtered if log.get("is_112_reported") == 1]
                elif selected_action_type == "case_closed":
                    filtered = [log for log in filtered if log.get("is_case_closed") == 1]
                elif selected_action_type == "danger_warning":
                    filtered = [log for log in filtered if log.get("is_danger_warned") == 1]
                elif selected_action_type == "emergency_warning":
                    filtered = [log for log in filtered if log.get("is_emergency_warned") == 1]
                elif selected_action_type == "illegal_warning":
                    filtered = [log for log in filtered if log.get("is_illegal_warned") == 1]
            
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
                self.display_log_details()
                
                if DEBUG:
                    print(f"{DEBUG_TAG['RECV']} 로그 선택: case_id={self.selected_log.get('case_id')}")
            
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 선택 변경 처리 실패: {e}")
                print(traceback.format_exc())
    
    def display_log_details(self):
        """선택된 로그의 상세 정보 표시"""
        try:
            if not self.selected_log:
                return
            
            # 기본 경로 설정 (main_server 폴더 기준)
            base_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'main_server')
            
            # 이미지 표시 (images 폴더 내 이미지 파일)
            image_path = self.selected_log.get("image_path", "")
            if image_path:
                full_image_path = os.path.join(base_path, image_path)
                if os.path.exists(full_image_path):
                    pixmap = QPixmap(full_image_path)
                    scaled_pixmap = pixmap.scaled(
                        self.label_case_detail_image.width(),
                        self.label_case_detail_image.height(),
                        Qt.KeepAspectRatio
                    )
                    self.label_case_detail_image.setPixmap(scaled_pixmap)
                    self.label_case_detail_image.setAlignment(Qt.AlignCenter)
                    
                    if DEBUG:
                        print(f"{DEBUG_TAG['RECV']} 이미지 로드: {full_image_path}")
                else:
                    self.label_case_detail_image.setText(f"이미지 없음\n({image_path})")
                    self.label_case_detail_image.setAlignment(Qt.AlignCenter)
                    
                    if DEBUG:
                        print(f"{DEBUG_TAG['ERR']} 이미지 파일을 찾을 수 없음: {full_image_path}")
            else:
                self.label_case_detail_image.setText("이미지 정보 없음")
                self.label_case_detail_image.setAlignment(Qt.AlignCenter)
            
            # 비디오 재생 (QVideoWidget 사용)
            video_path = self.selected_log.get("video_path", "")
            if video_path:
                full_video_path = os.path.join(base_path, video_path)
                if os.path.exists(full_video_path):
                    # 미디어 플레이어 설정
                    media_content = QMediaContent(QUrl.fromLocalFile(full_video_path))
                    self.mediaPlayer.setMedia(media_content)
                    
                    # 비디오 자동 재생
                    self.mediaPlayer.play()
                    
                    if DEBUG:
                        print(f"{DEBUG_TAG['RECV']} 비디오 재생 시작: {full_video_path}")
                else:
                    # 미디어 플레이어 초기화
                    self.mediaPlayer.setMedia(QMediaContent())
                    
                    if DEBUG:
                        print(f"{DEBUG_TAG['ERR']} 비디오 파일을 찾을 수 없음: {full_video_path}")
            else:
                # 미디어 플레이어 초기화
                self.mediaPlayer.setMedia(QMediaContent())
                
            # 추가 이벤트 상세 정보 표시
            case_info = f"케이스 ID: {self.selected_log.get('id', 'Unknown')}\n"
            case_info += f"케이스 유형: {self.selected_log.get('case_type', 'Unknown')}\n"
            case_info += f"탐지 유형: {self.selected_log.get('detection_type', 'Unknown')}\n"
            case_info += f"로봇 ID: {self.selected_log.get('robot_id', 'Unknown')}\n"
            case_info += f"위치: {self.selected_log.get('location', 'Unknown')}\n"
            case_info += f"사용자: {self.selected_log.get('user_id', 'Unknown')}\n"
            case_info += f"시작 시간: {self.selected_log.get('start_time', 'Unknown')}\n"
            case_info += f"종료 시간: {self.selected_log.get('end_time', 'Unknown')}\n"
            
            # 선택한 행에 대한 상세 정보를 표시할 라벨이 있다면 활용
            if hasattr(self, 'label_case_details'):
                self.label_case_details.setText(case_info)
                
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
        if hasattr(self, 'mediaPlayer'):
            self.mediaPlayer.stop()
            
            if DEBUG:
                print(f"{DEBUG_TAG['SEND']} 비디오 재생 중지")
    
    def closeEvent(self, event):
        """위젯 종료 시 비디오 재생 중지"""
        self.stop_video_playback()
        super().closeEvent(event)
