# gui/src/main_window.py

import json
import socket
from PyQt5.QtWidgets import QMainWindow, QTableWidgetItem
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.uic import loadUi
from gui.tabs.monitoring_tab import MonitoringTab

# 디버그 토글: True일 때만 print 출력
DEBUG = True

# 서버 연결 설정
# SERVER_IP = "192.168.0.23" # data_merger 서버 IP
SERVER_IP = "127.0.0.1"      # local host
SERVER_PORT = 9999           # data_merger 서버 포트

class DataMergerReceiverThread(QThread):
    # 디버그 태그 정의
    DEBUG_TAG = {
        'CONN': '[연결]',
        'RECV': '[수신]',
        'PARSE': '[파싱]',
        'ERR': '[오류]'
    }

    # 시그널: JSON 데이터(dict)와 이미지 바이트(bytes)를 전달
    detection_received = pyqtSignal(dict, bytes)

    def run(self):
        if DEBUG:
            print(f"{self.DEBUG_TAG['CONN']} 서버 연결 시도: {SERVER_IP}:{SERVER_PORT}")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.connect((SERVER_IP, SERVER_PORT))
                if DEBUG:
                    print(f"{self.DEBUG_TAG['CONN']} 서버 연결 성공")
            except Exception as e:
                if DEBUG:
                    print(f"{self.DEBUG_TAG['ERR']} 연결 실패: {e}")
                return

            while True:
                try:
                    header = sock.recv(4)
                    if not header:
                        if DEBUG:
                            print(f"{self.DEBUG_TAG['ERR']} 헤더 수신 실패, 연결 종료")
                        break
                    
                    total_length = int.from_bytes(header, 'big')
                    if DEBUG:
                        print(f"{self.DEBUG_TAG['RECV']} 패킷 길이: {total_length} 바이트")

                    full_data = b''
                    while len(full_data) < total_length:
                        chunk = sock.recv(min(total_length - len(full_data), 4096))
                        if not chunk:
                            raise ConnectionError("데이터 수신 중 연결 종료")
                        full_data += chunk

                    parts = full_data.split(b'|', 1)
                    if len(parts) != 2:
                        raise ValueError("잘못된 데이터 형식: 구분자 없음")
                    
                    json_data, jpeg_data = parts
                    data = json.loads(json_data.decode())
                    
                    if jpeg_data.endswith(b'\n'):
                        jpeg_data = jpeg_data[:-1]

                    if DEBUG:
                        print(f"{self.DEBUG_TAG['PARSE']} JSON {len(json_data)}바이트, JPEG {len(jpeg_data)}바이트 처리 완료")

                    self.detection_received.emit(data, jpeg_data)

                except Exception as e:
                    if DEBUG:
                        print(f"{self.DEBUG_TAG['ERR']} 처리 실패: {e}")
                    break

class MainWindow(QMainWindow):
    # 디버그 태그 정의
    DEBUG_TAG = {
        'INIT': '[초기화]',
        'CONN': '[연결상태]',
        'IMG': '[이미지처리]',
        'DET': '[객체탐지]',
        'UI': '[화면갱신]'
    }

    def __init__(self):
        super().__init__()
        # main_window UI 로드
        loadUi('./gui/ui/main_window.ui', self)

        if DEBUG:
            print(f"{self.DEBUG_TAG['INIT']} MainWindow 초기화 시작")

        # MonitoringTab 설정
        self.monitor_tab = MonitoringTab()
        self.tabWidget.removeTab(0)
        self.tabWidget.insertTab(0, self.monitor_tab, 'Main Monitoring')

        # TCP 수신 스레드 시작
        if DEBUG:
            print(f"{self.DEBUG_TAG['INIT']} DataMergerReceiverThread 시작")
        self.receiver_thread = DataMergerReceiverThread()
        self.receiver_thread.detection_received.connect(self.display_detection_result)
        self.receiver_thread.start()

        # 초기 상태 설정
        self.monitor_tab.connectivity_label.setText('Disconnected')
        self.monitor_tab.system_status_label.setText('Idle')
        if DEBUG:
            print(f"{self.DEBUG_TAG['INIT']} 초기화 완료")

    def display_detection_result(self, data: dict, image_bytes: bytes):
        if DEBUG:
            print(f"{self.DEBUG_TAG['DET']} 탐지 결과 수신, 데이터: {data}")
            print(f"{self.DEBUG_TAG['IMG']} 수신된 이미지 크기: {len(image_bytes)} 바이트")

        # 이미지 처리
        pixmap = QPixmap()
        pixmap.loadFromData(image_bytes)
        FIXED_WIDTH = 640
        FIXED_HEIGHT = 480
        scaled_pixmap = pixmap.scaled(
            FIXED_WIDTH, 
            FIXED_HEIGHT,
            aspectRatioMode=Qt.KeepAspectRatio,
            transformMode=Qt.SmoothTransformation
        )
        self.monitor_tab.live_feed_label.setPixmap(scaled_pixmap)
        if DEBUG:
            print(f"{self.DEBUG_TAG['IMG']} 이미지 리사이징 완료: {FIXED_WIDTH}x{FIXED_HEIGHT}")

        # 탐지 결과 테이블 갱신
        detections = data.get('detections', [])
        table = self.monitor_tab.detections_table
        table.setRowCount(len(detections))
        for row, det in enumerate(detections):
            if DEBUG:
                print(f"{self.DEBUG_TAG['DET']} 탐지 항목 {row}: {det}")
            table.setItem(row, 0, QTableWidgetItem(det.get('case', '-')))
            table.setItem(row, 1, QTableWidgetItem(data.get('timestamp', '-')))
            table.setItem(row, 2, QTableWidgetItem(data.get('location', '-')))
            table.setItem(row, 3, QTableWidgetItem(det.get('label', '-')))

        # UI 상태 갱신
        status = data.get('robot_status', 'Idle')
        self.monitor_tab.system_status_label.setText(status)
        self.monitor_tab.connectivity_label.setText('Connected')
        if DEBUG:
            print(f"{self.DEBUG_TAG['UI']} 시스템 상태 갱신: {status}")
