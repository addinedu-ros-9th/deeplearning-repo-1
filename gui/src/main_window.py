# gui/src/main_window.py

import json
import socket
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
SERVER_IP = "127.0.0.1"  # localhost
SERVER_PORT = 9004       # 메인 통신 포트
ROBOT_COMMANDER_PORT = 9006  # 로봇 커맨더 포트

# 지역 이동 명령 목록
MOVEMENT_COMMANDS = [CMD_MAP['MOVE_TO_A'], CMD_MAP['MOVE_TO_B'], CMD_MAP['RETURN_TO_BASE']]

class DataReceiverThread(QThread):
    """서버로부터 데이터를 수신하는 스레드"""
    detection_received = pyqtSignal(dict, bytes)  # (json_data, image_data)
    connection_status = pyqtSignal(bool)          # 연결 상태

    def __init__(self):
        super().__init__()
        self._running = True
        self.socket = None

    def stop(self):
        """스레드 정지"""
        self._running = False
        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
                self.socket.close()
            except:
                pass

    def run(self):
        """메인 수신 루프"""
        if DEBUG:
            print(f"{DEBUG_TAG['INIT']} 데이터 수신 스레드 시작")
            print(f"{DEBUG_TAG['CONN']} 서버 연결 시도: {SERVER_IP}:{SERVER_PORT}")

        # 소켓 생성 및 연결
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.socket.connect((SERVER_IP, SERVER_PORT))
            self.connection_status.emit(True)
            if DEBUG:
                print(f"{DEBUG_TAG['CONN']} 서버 연결 성공")

            # 메인 수신 루프
            while self._running:
                try:
                    # 1. 헤더(4바이트) 수신
                    header = self._receive_exact(4)
                    if not header:
                        if DEBUG:
                            print(f"{DEBUG_TAG['ERR']} 헤더 수신 실패")
                        break

                    # 2. 전체 길이 계산
                    total_length = int.from_bytes(header, 'big')
                    if DEBUG:
                        print(f"\n{DEBUG_TAG['RECV']} 메시지 수신 시작:")
                        print(f"  - 헤더: {header!r} (0x{header.hex()})")
                        print(f"  - 전체 길이: {total_length} 바이트")

                    # 3. 페이로드 수신
                    payload = self._receive_exact(total_length)
                    if not payload:
                        if DEBUG:
                            print(f"{DEBUG_TAG['ERR']} 페이로드 수신 실패")
                        break

                    # 4. JSON과 이미지 분리
                    try:
                        json_data, image_data = self._process_payload(payload)
                        self.detection_received.emit(json_data, image_data)
                        if DEBUG:
                            print(f"{DEBUG_TAG['RECV']} 메시지 처리 완료:")
                            print(f"  - JSON 크기: {len(json_data)} 바이트")
                            print(f"  - 이미지 크기: {len(image_data)} 바이트")
                    except Exception as e:
                        if DEBUG:
                            print(f"{DEBUG_TAG['ERR']} 메시지 처리 실패: {e}")
                            print(traceback.format_exc())
                        continue

                except ConnectionError as e:
                    if DEBUG:
                        print(f"{DEBUG_TAG['ERR']} 연결 오류: {e}")
                    break
                except Exception as e:
                    if DEBUG:
                        print(f"{DEBUG_TAG['ERR']} 예외 발생: {e}")
                        print(traceback.format_exc())
                    continue

        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 스레드 실행 오류: {e}")
                print(traceback.format_exc())
        finally:
            if self.socket:
                self.socket.close()
            self.connection_status.emit(False)
            if DEBUG:
                print(f"{DEBUG_TAG['CONN']} 연결 종료")

    def _receive_exact(self, size: int) -> bytes:
        """정확한 크기만큼 데이터 수신"""
        try:
            data = b''
            remaining = size
            while remaining > 0:
                chunk = self.socket.recv(min(remaining, 8192))
                if not chunk:
                    return None
                data += chunk
                remaining -= len(chunk)
                if DEBUG and size > 8192:
                    print(f"  - 수신 진행: {((size-remaining)/size*100):.1f}%")
            return data
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 데이터 수신 오류: {e}")
            return None

    def _process_payload(self, payload: bytes) -> tuple:
        """페이로드를 JSON과 이미지로 분리"""
        try:
            # 구분자('|')로 분리
            parts = payload.split(b'|', 1)
            if len(parts) != 2:
                raise ValueError("잘못된 페이로드 형식")

            # JSON 파싱
            json_str = parts[0].decode('utf-8').strip()
            json_data = json.loads(json_str)

            # 이미지 바이너리 (마지막 개행 제거)
            image_data = parts[1].rstrip(b'\n')

            return json_data, image_data

        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 페이로드 처리 실패: {e}")
                print(f"  - 페이로드 크기: {len(payload)} 바이트")
                print(f"  - 시작 부분: {payload[:100]!r}")
            raise

class MainWindow(QMainWindow):
    """메인 윈도우"""
    def __init__(self):
        super().__init__()
        if DEBUG:
            print(f"\n{DEBUG_TAG['INIT']} MainWindow 초기화 시작")

        # UI 설정
        self.setup_ui()
        
        # 수신 스레드 설정
        self.setup_receiver()
        
        if DEBUG:
            print(f"{DEBUG_TAG['INIT']} MainWindow 초기화 완료")

    def setup_ui(self):
        """UI 초기화"""
        try:
            # 기본 UI 로드
            loadUi('./gui/ui/main_window.ui', self)

            # 모니터링 탭 설정
            self.monitoring_tab = MonitoringTab()
            self.tabWidget.removeTab(0)
            self.tabWidget.insertTab(0, self.monitoring_tab, 'Main Monitoring')
            self.tabWidget.setCurrentIndex(0)

            # 명령 시그널 연결
            self.monitoring_tab.robot_command.connect(self.send_robot_command)
            self.monitoring_tab.stream_command.connect(self.control_stream)

            if DEBUG:
                print(f"{DEBUG_TAG['INIT']} UI 초기화 완료")

        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} UI 초기화 실패: {e}")
                print(traceback.format_exc())

    def setup_receiver(self):
        """데이터 수신 스레드 설정"""
        try:
            self.receiver = DataReceiverThread()
            self.receiver.detection_received.connect(self.handle_detection)
            self.receiver.connection_status.connect(self.handle_connection_status)
            self.receiver.start()
            
            if DEBUG:
                print(f"{DEBUG_TAG['INIT']} 수신 스레드 시작됨")

        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 수신 스레드 설정 실패: {e}")
                print(traceback.format_exc())

    def send_robot_command(self, command: str):
        """로봇 명령 전송"""
        try:
            if command not in CMD_MAP:
                if DEBUG:
                    print(f"{DEBUG_TAG['ERR']} 알 수 없는 명령: {command}")
                return

            # 명령 패킷 구성
            command_bytes = CMD_MAP[command]
            packet = b'CMD' + command_bytes + b'\n'

            if DEBUG:
                print(f"\n{DEBUG_TAG['SEND']} 명령 전송:")
                print(f"  - 명령: {command}")
                print(f"  - 패킷: {packet!r}")
                print(f"  - 바이트: {' '.join(hex(b)[2:] for b in packet)}")

            # 지역 이동 명령인 경우 로봇 커맨더로 전송
            if command in ["MOVE_TO_A", "MOVE_TO_B", "RETURN_TO_BASE"]:
                if not hasattr(self, 'commander_socket'):
                    if DEBUG:
                        print(f"{DEBUG_TAG['CONN']} 새 로봇 커맨더 소켓 생성")
                    self.commander_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.commander_socket.connect((SERVER_IP, ROBOT_COMMANDER_PORT))
                
                # 로봇 커맨더로 전송
                if DEBUG:
                    print(f"{DEBUG_TAG['SEND']} 로봇 커맨더로 전송 (포트: {ROBOT_COMMANDER_PORT})")
                self.commander_socket.sendall(packet)
                
            # 일반 명령은 기존 서버로 전송
            else:
                if not hasattr(self, 'command_socket'):
                    if DEBUG:
                        print(f"{DEBUG_TAG['CONN']} 새 명령 소켓 생성")
                    self.command_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.command_socket.connect((SERVER_IP, SERVER_PORT))

                # 메인 서버로 전송
                self.command_socket.sendall(packet)

            if DEBUG:
                print(f"{DEBUG_TAG['SEND']} 명령 전송 완료")

        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 명령 전송 실패: {e}")
                print(traceback.format_exc())
            
            # 소켓 재설정
            if command in ["MOVE_TO_A", "MOVE_TO_B", "RETURN_TO_BASE"] and hasattr(self, 'commander_socket'):
                try:
                    self.commander_socket.close()
                except:
                    pass
                delattr(self, 'commander_socket')
            elif hasattr(self, 'command_socket'):
                try:
                    self.command_socket.close()
                except:
                    pass
                delattr(self, 'command_socket')

    def control_stream(self, start: bool):
        """스트리밍 제어"""
        if start:
            self.send_robot_command('START_STREAM')
            if DEBUG:
                print(f"{DEBUG_TAG['SEND']} 스트리밍 시작 요청")

    def handle_detection(self, json_data: dict, image_data: bytes):
        """탐지 데이터 처리"""
        try:
            if DEBUG:
                print(f"\n{DEBUG_TAG['DET']} 탐지 데이터 수신:")
                print(f"  - Frame ID: {json_data.get('frame_id')}")

            # 이미지 업데이트
            if image_data:
                self.monitoring_tab.update_camera_feed(image_data)

            # 상태 및 위치 업데이트
            status = json_data.get('robot_status', 'unknown')
            location = json_data.get('location', 'unknown')
            self.monitoring_tab.update_status(
                "system", 
                f"위치: {location}, 상태: {status}"
            )

            # 탐지 결과 업데이트
            detections = json_data.get('detections', [])
            if detections:
                detection_text = "\n".join(
                    f"- {det['label']} ({det['case']})" 
                    for det in detections
                )
                self.monitoring_tab.update_status("detections", detection_text)
            else:
                self.monitoring_tab.update_status("detections", "탐지된 객체 없음")

        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 탐지 데이터 처리 실패: {e}")
                print(traceback.format_exc())

    def handle_connection_status(self, connected: bool):
        """연결 상태 처리"""
        try:
            status = "연결됨" if connected else "연결 끊김"
            self.monitoring_tab.update_status("connectivity", status)
            if DEBUG:
                print(f"{DEBUG_TAG['CONN']} 연결 상태 변경: {status}")
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 상태 업데이트 실패: {e}")

    def closeEvent(self, event):
        """윈도우 종료 처리"""
        if hasattr(self, 'receiver'):
            self.receiver.stop()
            self.receiver.wait()
        if hasattr(self, 'command_socket'):
            self.command_socket.close()
        if hasattr(self, 'commander_socket'):
            self.commander_socket.close()
        super().closeEvent(event)