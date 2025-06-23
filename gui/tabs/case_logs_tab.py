#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Case Logs Tab Module
로그 조회 탭 UI 및 로직 구현
"""

import os
import traceback
from datetime import datetime
from PyQt5.QtWidgets import (QWidget, QTableWidgetItem, QHeaderView, QMessageBox)
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtCore import Qt, QDateTime
from PyQt5.uic import loadUi

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
            loadUi("gui/ui/case_logs_tap.ui", self)
            
            # 테이블 설정
            self.tableWidget.setColumnCount(15)
            self.tableWidget.setHorizontalHeaderLabels([
                "case_id", "start_time", "end_time", "case_type", "detection_type", 
                "robot_id", "location_id", "user_name", "is_ignored", "is_119_reported", 
                "is_112_reported", "is_illegal_warned", "is_danger_warned", 
                "is_emergency_warned", "is_case_closed"
            ])
            
            # 테이블 열 너비 자동 조정
            self.tableWidget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            self.tableWidget.horizontalHeader().setStretchLastSection(False)
            
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
            
        # 로그 데이터 저장
        self.logs = logs
        self.filtered_logs = logs.copy()  # 필터링 초기화
        
        # 콤보박스 업데이트
        self.populate_comboboxes()
        
        # 테이블 업데이트
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
            self.comboBox_case_type.addItem("모든 케이스 타입")
            case_types = sorted(set(log.get("case_type", "") for log in self.logs if log.get("case_type")))
            self.comboBox_case_type.addItems(case_types)
            
            # 탐지 타입 콤보박스
            self.comboBox_detection_type.clear()
            self.comboBox_detection_type.addItem("모든 탐지 타입")
            detection_types = sorted(set(log.get("detection_type", "") for log in self.logs if log.get("detection_type")))
            self.comboBox_detection_type.addItems(detection_types)
            
            # 로봇 ID 콤보박스 (ROBOT001 포함 보장)
            self.comboBox_robot_id.clear()
            self.comboBox_robot_id.addItem("모든 로봇")
            robot_ids = sorted(set(log.get("robot_id", "") for log in self.logs if log.get("robot_id")))
            if "ROBOT001" not in robot_ids:
                robot_ids.append("ROBOT001")
            robot_ids = sorted(robot_ids)
            self.comboBox_robot_id.addItems(robot_ids)
            
            # 위치 ID 콤보박스
            self.comboBox_location_id.clear()
            self.comboBox_location_id.addItem("모든 위치")
            location_ids = sorted(set(log.get("location_id", "") for log in self.logs if log.get("location_id")))
            self.comboBox_location_id.addItems(location_ids)
            
            # 사용자 계정 콤보박스 (김대인 포함 보장)
            self.comboBox_user_account.clear()
            self.comboBox_user_account.addItem("모든 사용자")
            user_names = sorted(set(log.get("user_name", "") for log in self.logs if log.get("user_name")))
            if "김대인" not in user_names:
                user_names.append("김대인")
            user_names = sorted(user_names)
            self.comboBox_user_account.addItems(user_names)
            
            # 액션 타입 콤보박스
            self.comboBox_action_type.clear()
            self.comboBox_action_type.addItem("모든 액션")
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
            # 테이블 행 수 설정
            self.tableWidget.setRowCount(0)  # 초기화
            self.tableWidget.setRowCount(len(self.filtered_logs))
            
            # 테이블에 데이터 추가
            for row, log in enumerate(self.filtered_logs):
                # 필수 필드 검사 (없을 경우 빈 문자열로 설정)
                case_id = str(log.get("case_id", ""))
                start_time = log.get("start_time", "")
                end_time = log.get("end_time", "")
                case_type = log.get("case_type", "")
                detection_type = log.get("detection_type", "")
                robot_id = log.get("robot_id", "")
                location_id = log.get("location_id", "")
                user_name = log.get("user_name", "")
                is_ignored = str(log.get("is_ignored", 0))
                is_119_reported = str(log.get("is_119_reported", 0))
                is_112_reported = str(log.get("is_112_reported", 0))
                is_illeal_warned = str(log.get("is_illeal_warned", 0))
                is_danger_warned = str(log.get("is_danger_warned", 0))
                is_emergency_warned = str(log.get("is_emergency_warned", 0))
                is_case_closed = str(log.get("is_case_closed", 0))
                
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
                self.tableWidget.setItem(row, 6, QTableWidgetItem(location_id))
                self.tableWidget.setItem(row, 7, QTableWidgetItem(user_name))
                self.tableWidget.setItem(row, 8, QTableWidgetItem(is_ignored))
                self.tableWidget.setItem(row, 9, QTableWidgetItem(is_119_reported))
                self.tableWidget.setItem(row, 10, QTableWidgetItem(is_112_reported))
                self.tableWidget.setItem(row, 11, QTableWidgetItem(is_illeal_warned))
                self.tableWidget.setItem(row, 12, QTableWidgetItem(is_danger_warned))
                self.tableWidget.setItem(row, 13, QTableWidgetItem(is_emergency_warned))
                self.tableWidget.setItem(row, 14, QTableWidgetItem(is_case_closed))
                
            # 로그 수 표시 업데이트
            self.label_number_of_log.setText(f"로그 수: {len(self.filtered_logs)}")
            
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
                filtered = [log for log in filtered if log.get("location_id") == selected_location_id]
            
            # 사용자 계정 필터링
            if selected_user_account:
                filtered = [log for log in filtered if log.get("user_name") == selected_user_account]
            
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
                    filtered = [log for log in filtered if log.get("is_illeal_warned") == 1]
            
            # 필터링된 결과 저장 및 테이블 업데이트
            self.filtered_logs = filtered
            self.update_table()
            
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
                
            # 이미지 표시
            image_path = self.selected_log.get("image_path", "")
            if image_path and os.path.exists(image_path):
                pixmap = QPixmap(image_path)
                self.label_case_detail_image.setPixmap(
                    pixmap.scaled(
                        self.label_case_detail_image.width(),
                        self.label_case_detail_image.height(),
                        Qt.KeepAspectRatio
                    )
                )
            else:
                self.label_case_detail_image.setText("이미지 없음")
            
            # 비디오 표시 (현재는 단순 경로 표시)
            video_path = self.selected_log.get("video_path", "")
            if video_path and os.path.exists(video_path):
                self.label_case_detail_video.setText(f"비디오 경로: {video_path}")
            else:
                self.label_case_detail_video.setText("비디오 없음")
                
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 상세 정보 표시 실패: {e}")
                print(traceback.format_exc())
