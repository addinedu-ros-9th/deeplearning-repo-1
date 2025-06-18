# gui/src/main_window.py (수정된 최종 버전)

import json
import socket
import time # ✨ 추가됨
import traceback
from PyQt5.QtWidgets import QMainWindow
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.uic import loadUi
from gui.tabs.monitoring_tab import MonitoringTab
from shared.protocols import CMD_MAP

# 디버그 모드
DEBUG = True

# 디버그 태그
DEBUG_TAG = {
    'INIT': '[초기화]',
    'CONN': '[연결]',
    'RECV': '[수신]',
    'SEND': '[전송]',
    'DET': '[탐지]',
    'IMG': '[이미지]',
    'ERR': '[오류]'
}

# 서버 설정
SERVER_IP = "127.0.0.1"
SERVER_PORT = 9004       # DataMerger가 데이터를 보내는 포트 (GUI가 수신 대기)
COMMAND_SERVER_PORT = 9006   # ✨ 추가: RobotCommander에게 명령을 보내는 포트

class DataReceiverThread(QThread):
    """서버로부터 데이터를 수신하는 스레드"""
    detection_received = pyqtSignal(dict, bytes)
    connection_status = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self._running = True
        self.socket = None
        self.server_socket = None # ✨ 추가됨

    def stop(self):
        """스레드 정지"""
        self._running = False
        # 소켓을 닫아 accept() 또는 recv() 대기 상태에서 빠져나오게 함
        if self.socket:
            try: self.socket.close()
            except: pass
        if self.server_socket:
            try: self.server_socket.close()
            except: pass
        
    # ✨ 수정됨: 전체 run 메소드를 서버 역할로 변경
    def run(self):
        """메인 수신 루프 (서버 역할)"""
        if DEBUG:
            print(f"{DEBUG_TAG['INIT']} 데이터 수신 스레드 시작")
            print(f"{DEBUG_TAG['CONN']} 서버 소켓 생성 및 대기 시작: {SERVER_IP}:{SERVER_PORT}")

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.server_socket.bind((SERVER_IP, SERVER_PORT))
            self.server_socket.listen(1)

            while self._running:
                try:
                    if DEBUG: print(f"{DEBUG_TAG['CONN']} DataMerger의 연결을 기다립니다...")
                    self.socket, addr = self.server_socket.accept()
                    self.connection_status.emit(True)
                    if DEBUG: print(f"{DEBUG_TAG['CONN']} DataMerger 연결 성공: {addr}")

                    # 연결된 클라이언트로부터 데이터를 계속 수신
                    while self._running:
                        header = self._receive_exact(4)
                        if not header: break
                        
                        total_length = int.from_bytes(header, 'big')
                        if DEBUG:
                            print(f"\n{DEBUG_TAG['RECV']} 메시지 수신 시작 (길이: {total_length})")

                        payload = self._receive_exact(total_length)
                        if not payload: break

                        json_data, image_data = self._process_payload(payload)
                        self.detection_received.emit(json_data, image_data)
                    
                    self.connection_status.emit(False)
                    if DEBUG: print(f"{DEBUG_TAG['CONN']} DataMerger 연결 종료됨.")
                
                except (ConnectionError, OSError) as e:
                    if not self._running: break
                    if DEBUG: print(f"{DEBUG_TAG['ERR']} 연결 처리 중 오류: {e}")
                    self.connection_status.emit(False)
                    time.sleep(1)
        
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 데이터 수신 스레드 실행 오류: {e}")
                traceback.print_exc()
        finally:
            if self.socket: self.socket.close()
            if self.server_socket: self.server_socket.close()
            self.connection_status.emit(False)
            if DEBUG: print(f"{DEBUG_TAG['CONN']} 데이터 수신 서버 종료")

    def _receive_exact(self, size: int) -> bytes:
        """정확한 크기만큼 데이터 수신"""
        try:
            data = b''
            remaining = size
            while remaining > 0 and self._running:
                chunk = self.socket.recv(min(remaining, 8192))
                if not chunk: return None
                data += chunk
                remaining -= len(chunk)
            return data
        except (ConnectionError, OSError) as e:
            if self._running:
                print(f"{DEBUG_TAG['ERR']} 데이터 수신 오류: {e}")
            return None

    def _process_payload(self, payload: bytes) -> tuple:
        """페이로드를 JSON과 이미지로 분리"""
        try:
            parts = payload.split(b'|', 1)
            if len(parts) != 2:
                raise ValueError("잘못된 페이로드 형식")

            json_str = parts[0].decode('utf-8').strip()
            json_data = json.loads(json_str)
            image_data = parts[1]

            return json_data, image_data
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 페이로드 처리 실패: {e}")
            raise

class MainWindow(QMainWindow):
    """메인 윈도우"""
    def __init__(self):
        super().__init__()
        if DEBUG: print(f"\n{DEBUG_TAG['INIT']} MainWindow 초기화 시작")
        self.command_socket = None # ✨ 추가됨
        self.setup_ui()
        self.setup_receiver()
        if DEBUG: print(f"{DEBUG_TAG['INIT']} MainWindow 초기화 완료")

    def setup_ui(self):
        """UI 초기화"""
        try:
            loadUi('./gui/ui/main_window.ui', self)
            self.monitoring_tab = MonitoringTab()
            self.tabWidget.removeTab(0)
            self.tabWidget.insertTab(0, self.monitoring_tab, 'Main Monitoring')
            self.tabWidget.setCurrentIndex(0)
            self.monitoring_tab.robot_command.connect(self.send_robot_command)
            self.monitoring_tab.stream_command.connect(self.control_stream)
            if DEBUG: print(f"{DEBUG_TAG['INIT']} UI 초기화 완료")
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} UI 초기화 실패: {e}")
                traceback.print_exc()

    def setup_receiver(self):
        """데이터 수신 스레드 설정"""
        try:
            self.receiver = DataReceiverThread()
            self.receiver.detection_received.connect(self.handle_detection)
            self.receiver.connection_status.connect(self.handle_connection_status)
            self.receiver.start()
            if DEBUG: print(f"{DEBUG_TAG['INIT']} 수신 스레드 시작됨")
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 수신 스레드 설정 실패: {e}")
                traceback.print_exc()
    
    # ✨ 수정됨: 명령 소켓 연결 및 전송 로직
    def send_robot_command(self, command: str):
        """로봇 명령 전송"""
        try:
            if command not in CMD_MAP:
                if DEBUG: print(f"{DEBUG_TAG['ERR']} 알 수 없는 명령: {command}")
                return

            command_bytes = CMD_MAP[command]
            packet = b'CMD' + command_bytes

            if DEBUG:
                print(f"\n{DEBUG_TAG['SEND']} 명령 전송:")
                print(f"  - 명령: {command}, 패킷: {packet!r}")

            # 소켓이 없거나 닫혔으면 새로 연결
            if not self.command_socket or self.command_socket._closed:
                if DEBUG: print(f"{DEBUG_TAG['CONN']} 새 명령 소켓 생성 ({SERVER_IP}:{COMMAND_SERVER_PORT})")
                self.command_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.command_socket.connect((SERVER_IP, COMMAND_SERVER_PORT))

            self.command_socket.sendall(packet)
            if DEBUG: print(f"{DEBUG_TAG['SEND']} 명령 전송 완료")

        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 명령 전송 실패: {e}")
                traceback.print_exc()
            if self.command_socket:
                self.command_socket.close()

    def control_stream(self, start: bool):
        """스트리밍 제어"""
        if start:
            # 스트리밍 시작 명령은 RobotCommander가 아닌 다른 곳에서 처리해야 할 수 있음
            # 현재 아키텍처에서는 RobotCommander가 처리하므로 그대로 둠
            self.send_robot_command('START_STREAM')
            if DEBUG: print(f"{DEBUG_TAG['SEND']} 스트리밍 시작 요청")

    def handle_detection(self, json_data: dict, image_data: bytes):
        """탐지 데이터 처리"""
        try:
            if DEBUG: print(f"\n{DEBUG_TAG['DET']} 탐지 데이터 수신: Frame ID {json_data.get('frame_id')}")

            if image_data:
                self.monitoring_tab.update_camera_feed(image_data)

            status = json_data.get('robot_status', 'unknown')
            self.monitoring_tab.update_status("system", f"로봇 상태: {status}")

            detections = json_data.get('detections', [])
            if detections:
                detection_text = "\n".join([f"- {d.get('label', 'N/A')}" for d in detections])
                self.monitoring_tab.update_status("detections", detection_text)
            else:
                self.monitoring_tab.update_status("detections", "탐지된 객체 없음")

        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 탐지 데이터 처리 실패: {e}")
                traceback.print_exc()

    def handle_connection_status(self, connected: bool):
        """연결 상태 처리"""
        try:
            status = "데이터 서버 연결됨" if connected else "데이터 서버 연결 끊김"
            self.monitoring_tab.update_status("connectivity", status)
            if DEBUG: print(f"{DEBUG_TAG['CONN']} 연결 상태 변경: {status}")
        except Exception as e:
            if DEBUG: print(f"{DEBUG_TAG['ERR']} 상태 업데이트 실패: {e}")

    def closeEvent(self, event):
        """윈도우 종료 처리"""
        if hasattr(self, 'receiver'):
            self.receiver.stop()
            self.receiver.wait()
        if hasattr(self, 'command_socket'):
            try: self.command_socket.close()
            except: pass
        super().closeEvent(event)