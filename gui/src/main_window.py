# gui/src/main_window.py

import json
import socket
import traceback
from datetime import datetime
from PyQt5.QtWidgets import QMainWindow
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.uic import loadUi
from gui.tabs.monitoring_tab import MonitoringTab
from shared.protocols import CMD_MAP
from gui.src.detection_dialog import DetectionDialog

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
GUI_MERGER_PORT = 9004       # data_merger 통신 포트
ROBOT_COMMANDER_PORT = 9006  # 로봇 커맨더 포트
DB_MANAGER_HOST = "127.0.0.1" # 로컬호스트
DB_MANAGER_PORT = 9005      # GUI가 db 관련해서 접속할 포트

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
            print(f"{DEBUG_TAG['CONN']} GUI MERGER 서버 연결 시도: {SERVER_IP}:{GUI_MERGER_PORT}")

        # 소켓 생성 및 연결
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.socket.connect((SERVER_IP, GUI_MERGER_PORT))
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
                        print("-----------------------------------------------------------")
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
                            print(f"  - JSON 크기: {len(str(json_data))} 바이트")
                            print(f"  - 이미지 크기: {len(image_data)} 바이트")
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
            
            if DEBUG:
                print(f"{DEBUG_TAG['RECV']} 수신된 JSON 문자열:")
                print(f"  {json_str}")
                
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
    def __init__(self, user_name=None):
        super().__init__()
        if DEBUG:
            print(f"\n{DEBUG_TAG['INIT']} MainWindow 초기화 시작")

        # 사용자 이름 저장
        self.user_name = user_name
        
        # 탐지 및 대응 추적용 변수들
        self.current_detection = None   # 현재 처리 중인 탐지 정보 
        self.current_detection_image = None  # 현재 처리 중인 탐지 이미지
        self.detection_start_time = None  # 탐지 시작 시간
        self.popup_active = False  # 팝업창이 활성화 되어있는지
        self.status_frozen = False  # 상태 표시가 고정되었는지 여부
        self.frozen_status = {  # 고정된 상태 정보
            "frame_id": None,
            "robot_status": None,
            "robot_location": None,
            "detections": None
        }
        self.response_actions = {  # 사용자가 취한 대응 액션 (DB 저장용)
            "is_ignored": 0,
            "is_119_reported": 0,
            "is_112_reported": 0, 
            "is_illeal_warned": 0,
            "is_danger_warned": 0,
            "is_emergency_warned": 0,
            "is_case_closed": 0
        }
        
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
            
            # 윈도우 크기 설정
            # self.setMinimumSize(1024, 768)  # 최소 크기 설정
            self.resize(1200, 850)  # 초기 윈도우 크기 설정
            self.setWindowTitle("NeighBot Monitoring System")

            # 모니터링 탭 설정
            self.monitoring_tab = MonitoringTab(user_name=self.user_name)
            self.tabWidget.removeTab(0)
            self.tabWidget.insertTab(0, self.monitoring_tab, 'Main Monitoring')
            self.tabWidget.setCurrentIndex(0)
            
            # 탭 변경 시 이벤트 연결 (탭 변경 후 돌아와도 고정된 상태 유지)
            self.tabWidget.currentChanged.connect(self.handle_tab_changed)

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
                
            # 탐지 응답 관련 명령인 경우 사용자 대응 액션 업데이트
            response_commands = [
                "FIRE_REPORT", "POLICE_REPORT", "ILLEGAL_WARNING",
                "DANGER_WARNING", "EMERGENCY_WARNING", "CASE_CLOSED"
            ]
            
            if command in response_commands:
                # 대응 액션 업데이트
                self.update_response_action(command)

            # 로봇 제어 명령들은 로봇 커맨더로 전송 
            # (이동 명령 + 사건 대응 명령만 포함, PROCEED/IGNORE는 제외)
            important_commands = [
                "MOVE_TO_A", "MOVE_TO_B", "RETURN_TO_BASE",
                "FIRE_REPORT", "POLICE_REPORT", "ILLEGAL_WARNING",
                "DANGER_WARNING", "EMERGENCY_WARNING", "CASE_CLOSED"
            ]
            
            if command in important_commands:
                if not hasattr(self, 'commander_socket'):
                    if DEBUG:
                        print(f"{DEBUG_TAG['CONN']} 새 로봇 커맨더 소켓 생성")
                    self.commander_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.commander_socket.connect((SERVER_IP, ROBOT_COMMANDER_PORT))
                
                # 로봇 커맨더로 전송
                if DEBUG:
                    print(f"{DEBUG_TAG['SEND']} 명령 '{command}'을(를) 로봇 커맨더로 전송 (포트: {ROBOT_COMMANDER_PORT})")
                self.commander_socket.sendall(packet)
                
                # 특별 명령 로그
                if command in response_commands:
                    if DEBUG:
                        print(f"{DEBUG_TAG['SEND']} 사건 대응 명령 '{command}'을(를) 로봇 커맨더로 전송 완료")
                
            # 그 외 명령은 기존 서버로 전송 (ex: GET_LOGS)
            else:
                if not hasattr(self, 'command_socket'):
                    if DEBUG:
                        print(f"{DEBUG_TAG['CONN']} 새 명령 소켓 생성")
                    self.command_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.command_socket.connect((SERVER_IP, GUI_MERGER_PORT))

                # 메인 서버로 전송
                if DEBUG:
                    print(f"{DEBUG_TAG['SEND']} 명령 '{command}'을(를) 메인 서버로 전송 (포트: {GUI_MERGER_PORT})")
                self.command_socket.sendall(packet)

            if DEBUG:
                print(f"{DEBUG_TAG['SEND']} 명령 전송 완료")

        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 명령 전송 실패: {e}")
                print(traceback.format_exc())
            
            # 소켓 재설정
            if command in important_commands and hasattr(self, 'commander_socket'):
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
        """스트리밍 시스템 활성화 여부 제어
        첫 시작 시에만 사용되며, 이후로는 영상 수신은 계속됨
        """
        if DEBUG:
            print(f"{DEBUG_TAG['IMG']} 시스템 초기 활성화: {start}")
            
        # 첫 시작 시 시스템 활성화를 위한 코드를 추가할 수 있음 (필요한 경우)
        # 현재는 구현 필요 없음 - 항상 백그라운드에서 수신 중

    def handle_detection(self, json_data: dict, image_data: bytes):
        """탐지 데이터 처리"""
        try:
            if DEBUG:
                print(f"\n{DEBUG_TAG['DET']} 탐지 데이터 수신:")
                print(f"  [헤더 정보]")
                print(f"  - Frame ID: {json_data.get('frame_id')}")
                print(f"  - 로봇 위치: {json_data.get('location', 'unknown')}")
                print(f"  - 로봇 상태: {json_data.get('robot_status', 'unknown')}")
                
                # 탐지 결과가 있는 경우만 출력
                detections = json_data.get('detections', [])
                if detections:
                    print("  [탐지 정보]")
                    for det in detections:
                        print(f"  - 탐지된 종류: {det.get('label', 'unknown')}")
                        print(f"    상황 종류: {det.get('case', 'unknown')}")
                        print(f"    전체 탐지 정보: {det}")

            # 이미지 업데이트 - 실시간 영상은 항상 업데이트
            if image_data:
                self.monitoring_tab.update_camera_feed(image_data)

            # 상태 및 위치 정보 추출
            status = json_data.get('robot_status', 'unknown')
            location = json_data.get('location', 'unknown')
            frame_id = json_data.get('frame_id', 'unknown')
            
            # 상태가 고정되지 않은 경우에만 업데이트
            if not self.status_frozen:
                # 개별 라벨에 각각 정보 업데이트
                self.monitoring_tab.update_status("frame_id", str(frame_id))
                self.monitoring_tab.update_status("robot_location", location)
                self.monitoring_tab.update_status("robot_status", status)

                # 탐지 결과 업데이트
                detections = json_data.get('detections', [])
                if detections:
                    # 디버깅용 - 각 탐지 결과의 키 확인
                    if DEBUG:
                        print(f"  [탐지 결과 키 확인]")
                        for i, det in enumerate(detections):
                            print(f"  - 탐지 {i+1} 키: {list(det.keys())}")
                    
                    detection_text = "\n".join(
                        f"- {det.get('label', 'unknown')} ({det.get('case', 'unknown')})" 
                        for det in detections
                    )
                    self.monitoring_tab.update_status("detections", detection_text)
                else:
                    self.monitoring_tab.update_status("detections", "탐지된 객체 없음")
            
            # robot_status가 "detected"이고 탐지 결과가 있으면 팝업창 표시
            if status == "detected" and json_data.get('detections'):
                # 첫 번째 탐지 정보
                detection = json_data['detections'][0]
                
                # 팝업이 이미 활성화 되어있지 않은 경우에만 표시
                if not self.popup_active:
                    self.popup_active = True
                    self.status_frozen = True  # 상태 디스플레이 고정
                    self.current_detection = detection
                    self.current_detection_image = image_data
                    
                    # 고정할 상태 정보 저장
                    self.frozen_status["frame_id"] = str(frame_id)
                    self.frozen_status["robot_status"] = status
                    self.frozen_status["robot_location"] = location
                    
                    # 탐지 정보 저장
                    detection_text = "\n".join(
                        f"- {det.get('label', 'unknown')} ({det.get('case', 'unknown')})" 
                        for det in json_data.get('detections', [])
                    )
                    self.frozen_status["detections"] = detection_text
                    
                    # 탐지 시작 시간 저장 (UTC 표준시)
                    from datetime import datetime
                    self.detection_start_time = datetime.utcnow().isoformat() + "+00:00"
                    
                    if DEBUG:
                        print(f"{DEBUG_TAG['DET']} 탐지 시작 시간: {self.detection_start_time}")
                        print(f"{DEBUG_TAG['DET']} 새 팝업 생성")
                        print(f"{DEBUG_TAG['DET']} 상태 표시 고정됨")
                    
                    # 사용자 대응 액션 초기화
                    self.reset_response_actions()
                    
                    # 팝업 다이얼로그 생성 및 표시
                    dialog = DetectionDialog(self, detection, image_data)
                    dialog.response_signal.connect(self.handle_detection_response)
                    dialog.setWindowModality(Qt.ApplicationModal)  # 다이얼로그가 닫힐 때까지 다른 창 조작 불가
                    dialog.show()
                    
                    # 다이얼로그가 표시될 때 응답 명령 버튼들 비활성화 (기본 상태)
                    self.monitoring_tab.set_response_buttons_enabled(False)
                elif DEBUG:
                    print(f"{DEBUG_TAG['DET']} 팝업이 이미 활성화되어 있어 추가 팝업 생성 건너뜀")

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

    def handle_detection_response(self, response):
        """탐지 다이얼로그의 사용자 응답을 처리"""
        if DEBUG:
            print(f"{DEBUG_TAG['DET']} 사용자 응답: {response}")
        
        # 응답이 "PROCEED"(진행)인 경우 응답 명령 버튼들 활성화
        if response == "PROCEED":
            # 응답 버튼만 활성화하고, 서버에 명령을 보내지 않음
            self.monitoring_tab.set_response_buttons_enabled(True)
            
            # 탐지 이미지를 메인 윈도우에 출력
            if self.current_detection_image:
                self.monitoring_tab.update_detection_image(self.current_detection_image)
                if DEBUG:
                    print(f"{DEBUG_TAG['DET']} 탐지 이미지를 메인 윈도우에 표시함")
            
            # 고정된 상태 정보 복원 (팝업 뒤 화면에서 다른 상태값으로 업데이트 됐을 수 있음)
            self.restore_frozen_status_display()
                    
        else:  # "IGNORE"(무시)인 경우
            self.monitoring_tab.set_response_buttons_enabled(False)
            self.response_actions["is_ignored"] = 1
            self.response_actions["is_case_closed"] = 1  # 무시도 케이스 종료로 간주
            
            # DB 매니저에게 로그 전송
            self.send_log_to_db_manager()
            
            # 팝업 및 상태 고정 해제
            self.popup_active = False
            self.status_frozen = False
            
            if DEBUG:
                print(f"{DEBUG_TAG['DET']} 상태 표시 고정 해제됨")

    def update_response_action(self, action_type):
        """사용자 대응 액션 업데이트
        
        Args:
            action_type (str): 액션 유형 (FIRE_REPORT, POLICE_REPORT 등)
        """
        if action_type == "FIRE_REPORT":
            self.response_actions["is_119_reported"] = 1
        elif action_type == "POLICE_REPORT":
            self.response_actions["is_112_reported"] = 1
        elif action_type == "ILLEGAL_WARNING":
            self.response_actions["is_illeal_warned"] = 1
        elif action_type == "DANGER_WARNING":
            self.response_actions["is_danger_warned"] = 1
        elif action_type == "EMERGENCY_WARNING":
            self.response_actions["is_emergency_warned"] = 1
        elif action_type == "CASE_CLOSED":
            self.response_actions["is_case_closed"] = 1
            
            # 케이스 종료 시 DB에 로그 전송
            self.send_log_to_db_manager()
            
            # 팝업 및 상태 고정 해제
            self.popup_active = False
            self.status_frozen = False
            
            if DEBUG:
                print(f"{DEBUG_TAG['DET']} 상태 표시 고정 해제됨 (사건 종료)")
        
        if DEBUG:
            print(f"{DEBUG_TAG['DET']} 대응 액션 업데이트: {action_type}")
            print(f"{DEBUG_TAG['DET']} 현재 대응 상태: {self.response_actions}")

    def reset_response_actions(self):
        """사용자 대응 액션 초기화"""
        self.response_actions = {
            "is_ignored": 0,
            "is_119_reported": 0,
            "is_112_reported": 0, 
            "is_illeal_warned": 0,
            "is_danger_warned": 0,
            "is_emergency_warned": 0,
            "is_case_closed": 0
        }

    def send_log_to_db_manager(self):
        """DB 매니저에게 로그 전송"""
        try:
            # 현재 시간을 종료 시간으로 설정
            from datetime import datetime
            end_time = datetime.utcnow().isoformat() + "+00:00"
            
            if not self.current_detection or not self.detection_start_time:
                if DEBUG:
                    print(f"{DEBUG_TAG['ERR']} 로그 전송 실패: 탐지 정보 없음")
                return
                
            # 로그 데이터 구성
            log_data = {
                "logs": [
                    {
                        "case_id": self.current_detection.get("case_id", 6),  # 기본값 6 (예시에서 사용된 값)
                        "case_type": self.current_detection.get("case", "unknown"),
                        "detection_type": self.current_detection.get("label", "unknown"),
                        "robot_id": "ROBOT001",  # 로봇 ID
                        "location_id": self.current_detection.get("location", "unknown"),
                        "user_account": self.user_name if self.user_name else "user",
                        "is_ignored": self.response_actions["is_ignored"],
                        "is_119_reported": self.response_actions["is_119_reported"],
                        "is_112_reported": self.response_actions["is_112_reported"],
                        "is_illeal_warned": self.response_actions["is_illeal_warned"],
                        "is_danger_warned": self.response_actions["is_danger_warned"],
                        "is_emergency_warned": self.response_actions["is_emergency_warned"],
                        "is_case_closed": self.response_actions["is_case_closed"],
                        "start_time": self.detection_start_time,
                        "end_time": end_time
                    }
                ]
            }
            
            # JSON 직렬화
            import json
            body = json.dumps(log_data).encode('utf-8') + b'\n'
            
            # 헤더 생성 (4바이트 길이)
            header = len(body).to_bytes(4, 'big')
            
            # 패킷 조립
            packet = header + body
            
            if DEBUG:
                print(f"{DEBUG_TAG['SEND']} DB 매니저에 로그 전송:")
                print(f"  - 헤더 크기: {int.from_bytes(header, 'big')} 바이트")
                print(f"  - 로그 내용: {log_data}")
                
            # DB 매니저에 소켓 연결 및 데이터 전송
            db_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            db_socket.connect((DB_MANAGER_HOST, DB_MANAGER_PORT))
            db_socket.sendall(packet)
            
            if DEBUG:
                print(f"{DEBUG_TAG['SEND']} DB 매니저에 로그 전송 완료")
                
            # 연결 종료
            db_socket.close()
            
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} DB 로그 전송 실패: {e}")
                print(traceback.format_exc())

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

    def restore_frozen_status_display(self):
        """고정된 상태 정보를 화면에 복원"""
        if self.status_frozen and all(v is not None for v in self.frozen_status.values()):
            # 각 상태 값을 UI에 표시
            for status_type, value in self.frozen_status.items():
                self.monitoring_tab.update_status(status_type, value)
                
            if DEBUG:
                print(f"{DEBUG_TAG['DET']} 고정된 상태 정보 복원됨")
                for k, v in self.frozen_status.items():
                    print(f"  - {k}: {v}")
    
    def handle_tab_changed(self, index):
        """탭 변경 처리"""
        try:
            if DEBUG:
                print(f"{DEBUG_TAG['INIT']} 탭 변경됨: {index}")
            
            # 현재 탭이 모니터링 탭이 아닐 경우
            if index != 0:
                # 상태 표시 고정
                self.status_frozen = True
                if DEBUG:
                    print(f"{DEBUG_TAG['INIT']} 상태 표시 고정됨")
            else:
                # 모니터링 탭으로 돌아온 경우 - 고정된 상태 복원
                self.restore_frozen_status_display()
                if DEBUG:
                    print(f"{DEBUG_TAG['INIT']} 메인 모니터링 탭 활성화, 고정 상태 복원")
                
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 탭 변경 처리 실패: {e}")
                print(traceback.format_exc())