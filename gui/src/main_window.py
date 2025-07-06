# gui/src/main_window.py
"""
메인 윈도우 모듈
- 메인 애플리케이션 윈도우 구현
- 탐지 데이터 수신 및 처리
- 모니터링 및 로그 탭 관리
- 사용자 응답 처리
"""

# 표준 라이브러리 임포트
import json
import socket
import traceback
from datetime import datetime, timedelta, timezone

# PyQt5 관련 임포트
from PyQt5.QtWidgets import QMainWindow, QMessageBox
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt5.uic import loadUi

# 애플리케이션 모듈 임포트
from gui.tabs.monitoring_tab import MonitoringTab
from gui.tabs.case_logs_tab import CaseLogsTab
from shared.protocols import CMD_MAP, GET_LOGS
from gui.src.detection_dialog import DetectionDialog

# 디버그 설정
DEBUG = True  # True: 디버그 로그 출력, False: 로그 출력 안함

# 디버그 태그 (로그 분류용)
DEBUG_TAG = {
    'INIT': '[초기화]',  # 초기화 관련 로그
    'CONN': '[연결]',    # 네트워크 연결 로그
    'RECV': '[수신]',    # 데이터 수신 로그
    'SEND': '[전송]',    # 데이터 전송 로그
    'DET': '[탐지]',     # 객체 탐지 로그
    'IMG': '[이미지]',   # 이미지 처리 로그
    'ERR': '[오류]'      # 오류 로그
}

# 시간대 설정
KOREA_TIMEZONE = timezone(timedelta(hours=9))  # UTC+9 (한국 표준시, KST)

# 네트워크 설정
SERVER_IP = "127.0.0.1"       # 서버 IP (localhost)
GUI_MERGER_PORT = 9004        # 데이터 병합기 통신 포트
ROBOT_COMMANDER_PORT = 9006   # 로봇 명령 포트
DB_MANAGER_HOST = "127.0.0.1" # DB 매니저 호스트
DB_MANAGER_PORT = 9005        # DB 매니저 포트

# 로봇 이동 명령 목록
MOVEMENT_COMMANDS = [
    CMD_MAP['MOVE_TO_A'],     # A 구역으로 이동
    CMD_MAP['MOVE_TO_B'],     # B 구역으로 이동
    CMD_MAP['RETURN_TO_BASE'] # 기지로 복귀
]

class DataReceiverThread(QThread):
    """
    서버로부터 데이터를 수신하는 스레드
    
    주요 기능:
    - 서버와의 소켓 연결 관리
    - 탐지 데이터 및 이미지 수신
    - 연결 상태 모니터링
    
    Signals:
        detection_received (dict, bytes): 탐지 정보와 이미지 데이터
        connection_status (bool): 서버 연결 상태
    """
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
    """
    메인 윈도우 클래스
    
    주요 기능:
    - 모니터링 및 로그 탭 관리
    - 서버와 통신하여 탐지 데이터 수신
    - 탐지 이벤트 처리 및 대응 관리
    - 로봇 명령 전송 및 상태 모니터링
    """
    # :sparkles: __init__ 메서드 시그니처를 수정합니다.
    def __init__(self, user_id=None, user_name=None):
        super().__init__()
        if DEBUG:
            print(f"\n{DEBUG_TAG['INIT']} MainWindow 초기화 시작")

        # 사용자 ID와 이름 저장
        self.user_id = user_id
        self.user_name = user_name
        
        # 탐지 및 대응 추적용 변수들
        self.current_detection = None   # 현재 처리 중인 탐지 정보 
        self.current_detection_image = None  # 현재 처리 중인 탐지 이미지
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
            "is_illegal_warned": 0,
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
            loadUi('./gui/ui/main_window2.ui', self)
            
            # 윈도우 크기 설정
            # self.setMinimumSize(1024, 768)  # 최소 크기 설정
            self.resize(1200, 850)  # 초기 윈도우 크기 설정
            self.setWindowTitle("NeighBot Monitoring System")

            # 모니터링 탭 설정
            self.monitoring_tab = MonitoringTab(user_name=self.user_name)
            self.tabWidget.removeTab(0)
            self.tabWidget.insertTab(0, self.monitoring_tab, 'Main Monitoring')
            
            # Case Logs 탭 설정 - 기존 탭을 우리의 CaseLogsTab 객체로 대체
            # 기존 UI에 이미 Case Logs 탭이 있으므로 별도 추가하지 않고 대체만 함
            self.case_logs_tab = CaseLogsTab(parent=self, initial_logs=[])
            # 기존 Case Logs 탭 인덱스 찾기 (일반적으로 1번)
            case_logs_index = 1
            self.tabWidget.removeTab(case_logs_index)
            self.tabWidget.insertTab(case_logs_index, self.case_logs_tab, 'Case Logs')
            
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
                "DANGER_WARNING", "EMERGENCY_WARNING", "CASE_CLOSED", "IGNORE"
            ]
            
            if command in response_commands:
                # 대응 액션 업데이트
                self.update_response_action(command)

            # 로봇 제어 명령들은 로봇 커맨더로 전송 
            # (이동 명령 + 사건 대응 명령만 포함, PROCEED는 제외)
            important_commands = [
                "MOVE_TO_A", "MOVE_TO_B", "RETURN_TO_BASE",
                "FIRE_REPORT", "POLICE_REPORT", "ILLEGAL_WARNING",
                "DANGER_WARNING", "EMERGENCY_WARNING", "CASE_CLOSED", "IGNORE"
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
        
        # Start Video Stream 버튼이 처음 클릭되었을 때, 이동 버튼도 활성화 되도록 처리
        if start:
            # 현재 위치에 따른 이동 버튼 활성화
            current_location = self.monitoring_tab.current_location
            robot_status = 'patrolling'  # 기본값 설정
            
            if DEBUG:
                print(f"{DEBUG_TAG['IMG']} 스트리밍 시작: 이동 버튼 활성화 (위치: {current_location}, 상태: {robot_status})")
            
            # 이동 중이 아니면 현재 위치에 맞게 이동 버튼 활성화
            if robot_status != 'moving':
                self.monitoring_tab.enable_movement_buttons()
                
            # 상태 표시도 업데이트 
            if not self.status_frozen:
                self.monitoring_tab.update_status("robot_status", robot_status)
                self.monitoring_tab.update_status("robot_location", current_location)

    def handle_detection(self, json_data: dict, image_data: bytes):
        """탐지 데이터 처리"""
        try:
            # 이미지 데이터 수신 시간 기록 
            current_time = datetime.now(KOREA_TIMEZONE).isoformat()  # 한국 시간으로 현재 시각 기록
            if DEBUG:
                print(f"\n{DEBUG_TAG['DET']} 탐지 데이터 수신: {current_time}")
                print(f"  [헤더 정보]")
                print(f"  - Frame ID: {json_data.get('frame_id')}")
                print(f"  - 로봇 위치: {json_data.get('location', 'unknown')}")  # location으로 변경
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
            
            # 위치 정보 추출 - 서버에서 제공하는 여러 가능한 키들을 시도
            location = json_data.get('location')
            if location is None:
                location = json_data.get('location_id')  # 이전 버전 호환성 유지
            if location is None:
                location = 'A'  # 디폴트 값으로 'A' 설정 (DB에 저장 가능한 유효한 값)
                
            if DEBUG:
                print(f"{DEBUG_TAG['DET']} 추출된 로봇 위치: {location} (원본 데이터: {json_data})")
                
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
                    
                    # 탐지 객체와 케이스 정보 추출하여 자세한 정보 표시
                    objects_count = len(detections)
                    case_types = set(det.get('case', 'unknown') for det in detections)
                    
                    # 현재 상황 요약 텍스트 구성
                    if status == "detected":
                        situation = "⚠️ 사건 감지 중"
                        
                        # 케이스 타입별로 다른 아이콘 추가
                        if 'danger' in case_types:
                            situation = "🔴 위험 상황 감지"
                        elif 'illegal' in case_types:
                            situation = "🟠 위법 행위 감지"
                        elif 'emergency' in case_types:
                            situation = "🟡 응급 상황 감지"
                        
                        # 자세한 탐지 목록 추가
                        object_list = "\n".join(
                            f"- {det.get('label', 'unknown')} ({det.get('case', 'unknown')})" 
                            for det in detections
                        )
                        detection_text = f"{situation} ({objects_count})\n{object_list}"
                    else:
                        # 일반 대기 상태
                        object_list = "\n".join(
                            f"- {det.get('label', 'unknown')} ({det.get('case', 'unknown')})" 
                            for det in detections
                        )
                        detection_text = f"객체 감지됨 ({objects_count})\n{object_list}"
                        
                    self.monitoring_tab.update_status("detections", detection_text)
                else:
                    if status == "detected":
                        self.monitoring_tab.update_status("detections", "⚠️ 이벤트 감지 - 탐지 객체 정보 없음")
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
                    
                    # 탐지 정보에 서버에서 받은 location 추가
                    # 로봇 위치는 이미 위에서 추출한 location 변수에 저장되어 있음
                    self.current_detection['location'] = location
                    
                    if DEBUG:
                        print(f"{DEBUG_TAG['DET']} ❗ 탐지 시작")
                        print(f"{DEBUG_TAG['DET']} 탐지 정보에 위치 저장: {location}")
                        
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

                    # 탐지 시작 시간 설정 (한국 표준시, KST)
                    if 'timestamp' in json_data:
                        # 프레임에 타임스탬프 정보가 있으면 사용
                        self.detection_start_time = json_data['timestamp']
                    else:
                        # 없으면 현재 시간으로 설정
                        self.detection_start_time = datetime.now(KOREA_TIMEZONE).isoformat()
                    
                    if DEBUG:
                        print(f"{DEBUG_TAG['DET']} 탐지 위치 (location): {self.current_detection.get('location', 'unknown')}")
                        print(f"{DEBUG_TAG['DET']} 새 팝업 생성")
                        print(f"{DEBUG_TAG['DET']} 상태 표시 고정됨")
                        print(f"{DEBUG_TAG['DET']} 첫번째 탐지 정보:")
                        print(f"  - 레이블: {detection.get('label', 'unknown')}")
                        print(f"  - 케이스 유형: {detection.get('case', 'unknown')}")
                        print(f"  - 위치: {detection.get('location', 'unknown')}")
                        print(f"  - 객체 ID: {detection.get('id', 'unknown')}")
                        print(f"  - 신뢰도: {detection.get('confidence', 'unknown')}")
                        
                        # 탐지 정보의 모든 키와 값 출력
                        print(f"\n  [전체 탐지 정보 상세 출력]")
                        for key, value in detection.items():
                            print(f"  - {key}: {value}")
                            
                        # JSON 포맷으로도 출력
                        print(f"\n  [JSON 형식 탐지 정보]")
                        print(f"  {json.dumps(detection, indent=2, ensure_ascii=False)}")
                    
                    # 사용자 대응 액션 초기화
                    self.reset_response_actions()
                    
                    # 팝업 다이얼로그 생성 및 표시
                    dialog = DetectionDialog(self, detection, image_data, self.user_name)
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

    def handle_detection_response(self, response, detection_data):
        """탐지 다이얼로그의 사용자 응답을 처리"""
        if DEBUG:
            print(f"{DEBUG_TAG['DET']} 사용자 응답: {response}, 탐지정보: {detection_data}")
        
        # 피드백 메시지 표시
        action_info = {
            'response': response,
            'case': detection_data.get('case', 'unknown'),
            'label': detection_data.get('label', 'unknown')
        }
        self.monitoring_tab.show_feedback_message('dialog', action_info)
        
        # 팝업 알림 표시
        popup = QMessageBox(self)
        popup.setWindowTitle("응답 처리")
        if response == "PROCEED":
            popup.setText(f"상황을 진행합니다.\n적절한 대응 명령을 선택하세요.")
        else:  # "IGNORE"
            popup.setText(f"상황을 무시합니다.\n계속 모니터링을 진행합니다.")
        popup.setStandardButtons(QMessageBox.Ok)
        popup.setWindowModality(Qt.NonModal)  # 모달리스 팝업
        popup.show()
        
        # 2초 후 자동으로 닫히도록 설정
        QTimer.singleShot(2000, popup.accept)
        
        # 응답이 "PROCEED"(진행)인 경우 응답 명령 버튼들 활성화하고 이동 버튼 비활성화
        if response == "PROCEED":
            # 응답 버튼만 활성화하고, 서버에 명령을 보내지 않음
            self.monitoring_tab.set_response_buttons_enabled(True)
            
            # 로봇 이동 버튼 비활성화 (위험 상황이니 이동 금지)
            self.monitoring_tab.disable_movement_buttons()
            if DEBUG:
                print(f"{DEBUG_TAG['DET']} 위험 상황 대응 중: 로봇 이동 버튼 비활성화")
            
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
            # 무시는 case_closed=1로 설정하지 않음 (is_ignored만 1로 설정)
            
            if DEBUG:
                print(f"{DEBUG_TAG['DET']} ================ IGNORE 처리 시작 ===============")
                print(f"{DEBUG_TAG['DET']} 사용자가 탐지를 무시함 - DB에 로그 전송 시작")
                print(f"{DEBUG_TAG['DET']} 현재 대응 상태: {self.response_actions}")
                print(f"{DEBUG_TAG['DET']} IGNORE 처리: 케이스 종료(is_case_closed) 설정 안함, 무시(is_ignored)만 설정")
            
            # 로봇 커맨더에 IGNORE 명령 전송
            self.send_robot_command("IGNORE")
            
            # DB 매니저에게 로그 전송
            self.send_log_to_db_manager()
            
            # 팝업 및 상태 고정 해제
            self.popup_active = False
            self.status_frozen = False
            
            # 로봇 상태를 patrolling으로 명시적 변경 (CASE_CLOSED와 동일하게)
            self.frozen_status["robot_status"] = "patrolling"
            
            # 현재 위치가 BASE가 아니면 패트롤링 재개하되, 현재 각도에서 바로 시작
            if self.frozen_status.get("robot_location") != "BASE":
                # 현재 위치에서 즉시 패트롤링을 재개 (현재 각도에서 시작)
                if DEBUG:
                    print(f"{DEBUG_TAG['DET']} IGNORE 처리: 현재 위치({self.frozen_status.get('robot_location')})에서 패트롤링 재개")
                QTimer.singleShot(500, self.monitoring_tab.start_patrol_animation_from_current)
            
            # 로봇 이동 버튼 다시 활성화
            self.monitoring_tab.enable_movement_buttons()
            
            if DEBUG:
                print(f"{DEBUG_TAG['DET']} 상태 표시 고정 해제됨 (무시 처리)")
                print(f"{DEBUG_TAG['DET']} frozen_status 업데이트됨 (robot_status: patrolling)")
                print(f"{DEBUG_TAG['DET']} 로봇 이동 버튼 재활성화")
                print(f"{DEBUG_TAG['DET']} ================ IGNORE 처리 완료 ================")

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
            self.response_actions["is_illegal_warned"] = 1
        elif action_type == "DANGER_WARNING":
            self.response_actions["is_danger_warned"] = 1
        elif action_type == "EMERGENCY_WARNING":
            self.response_actions["is_emergency_warned"] = 1
        elif action_type == "CASE_CLOSED":
            # 사건 종료 시 DB에 로그 전송
            if DEBUG:
                print(f"{DEBUG_TAG['DET']} ================ 사건 종료 처리 시작 ===============")            

            self.response_actions["is_case_closed"] = 1
            self.send_log_to_db_manager()
            
            # 케이스 종료 시 이동 버튼 다시 활성화 (현재 위치에 맞게)
            self.monitoring_tab.enable_movement_buttons()
            
            # 순찰 재개 로직 추가: BASE가 아닌 경우에만 순찰 재개
            if self.frozen_status.get("robot_location") != "BASE":
                # 사건 위치가 BASE가 아닌 경우에만 순찰 재개 (약간의 지연을 두고)
                # 현재 위치에서 바로 패트롤링 시작 (사전 위치 이동 없이)
                QTimer.singleShot(500, self.monitoring_tab.start_patrol_animation_from_current)
                if DEBUG:
                    print(f"{DEBUG_TAG['DET']} 사건 종료: 현재 위치에서 바로 순찰 애니메이션 재개 예약됨 ({self.frozen_status.get('robot_location')} 위치에서)")
            
            if DEBUG:
                print(f"{DEBUG_TAG['DET']} 사건 종료: 로봇 이동 버튼 재활성화")
            
            # 팝업 및 상태 고정 해제
            self.popup_active = False
            self.status_frozen = False
            
            # 상태 변경 후 frozen_status 업데이트 - 이것이 핵심 수정 부분
            # 최신 정보를 frozen_status에 업데이트하여 탭 전환 시 이전 상태로 돌아가지 않도록 함
            self.frozen_status["robot_status"] = "patrolling"  # 사건 종료 후 상태는 patrolling으로 설정
            
            if DEBUG:
                print(f"{DEBUG_TAG['DET']} 상태 표시 고정 해제됨 (사건 종료)")
                print(f"{DEBUG_TAG['DET']} frozen_status 업데이트됨 (robot_status: patrolling)")
        
        if DEBUG:
            print(f"{DEBUG_TAG['DET']} 대응 액션 업데이트: {action_type}")
            print(f"{DEBUG_TAG['DET']} 현재 대응 상태: {self.response_actions}")

    def reset_response_actions(self):
        """사용자 대응 액션 초기화"""
        self.response_actions = {
            "is_ignored": 0,
            "is_119_reported": 0,
            "is_112_reported": 0, 
            "is_illegal_warned": 0,
            "is_danger_warned": 0,
            "is_emergency_warned": 0,
            "is_case_closed": 0
        }

    def send_log_to_db_manager(self):
        """DB 매니저에게 로그 전송"""
        try:
            # 현재 시간을 종료 시간으로 설정 (한국 표준시, KST)
            end_time_full = datetime.now(KOREA_TIMEZONE).isoformat()
            
            # 타임존 정보 제거 -> MySQL용 DATETIME 형식으로 변환 ('YYYY-MM-DD HH:MM:SS')
            end_time_dt = datetime.fromisoformat(end_time_full)
            end_time = end_time_dt.strftime('%Y-%m-%d %H:%M:%S')
            
            if not self.current_detection:
                if DEBUG:
                    print(f"{DEBUG_TAG['ERR']} 로그 전송 실패: 탐지 정보 없음")
                return
            
            # 시작 시간도 같은 방식으로 처리 (타임존 정보 제거)
            start_time_dt = datetime.fromisoformat(self.detection_start_time)
            start_time = start_time_dt.strftime('%Y-%m-%d %H:%M:%S')
                
            # 로그 데이터 구성 (타임존 정보가 제거된 시간 형식 사용)
            log_data = {
                "logs": [
                    {
                        # 'case_id'는 DB에서 auto_increment로 자동 생성됨
                        "case_id": 0,
                        "case_type": self.current_detection.get("case", "unknown"),
                        "detection_type": self.current_detection.get("label", "unknown"),
                        # 사용자 이름을 robot_id로 사용 (기본값: 김민수)
                        "robot_id": "ROBOT001",
                        "user_id": self.user_name if self.user_name else "user_name_unknown",  # 사용자 ID 저장
                        "location": self.frozen_status.get("robot_location") or self.current_detection.get("location") or "A",
                        "is_ignored": self.response_actions["is_ignored"],
                        "is_119_reported": self.response_actions["is_119_reported"],
                        "is_112_reported": self.response_actions["is_112_reported"],
                        "is_illegal_warned": self.response_actions["is_illegal_warned"],
                        "is_danger_warned": self.response_actions["is_danger_warned"],
                        "is_emergency_warned": self.response_actions["is_emergency_warned"],
                        "is_case_closed": self.response_actions["is_case_closed"],
                        # 타임존 정보가 제거된 시간 정보 (MySQL DATETIME 형식)
                        "start_time": start_time,  # 탐지 시작 시간 (타임존 정보 없음)
                        "end_time": end_time  # 사건 종료 시간 (타임존 정보 없음)
                    }
                ]
            }
            
            # JSON 직렬화
            import json
            body = json.dumps(log_data).encode('utf-8')
            
            # 헤더 생성 (4바이트 길이)
            header = len(body).to_bytes(4, 'big')
            
            # 패킷 조립
            packet = header + body
            
            if DEBUG:
                print(f"{DEBUG_TAG['SEND']} DB 매니저에 로그 전송:")
                print(f"  - 헤더 크기: {int.from_bytes(header, 'big')} 바이트")
                print(f"  - 로그 내용: {log_data}")
                print(f"  - 시간 형식 변환됨: KST 타임존 정보 제거")
                print(f"    - 원본 시작 시간: {self.detection_start_time}")
                print(f"    - 변환된 시작 시간: {start_time}")
                print(f"    - 원본 종료 시간: {end_time_full}")
                print(f"    - 변환된 종료 시간: {end_time}")
                
            # DB 매니저에 소켓 연결 및 데이터 전송
            db_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            db_socket.connect((DB_MANAGER_HOST, DB_MANAGER_PORT))
            db_socket.sendall(packet)
            
            if DEBUG:
                print(f"{DEBUG_TAG['SEND']} DB 매니저에 로그 전송 완료")
                
            # 연결 종료
            db_socket.close()
            
            # 로그 전송 후 현재 탐지 정보 초기화
            self.current_detection = None
            self.current_detection_image = None
            self.detection_start_time = None
            
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} DB 로그 전송 실패: {e}")
                print(traceback.format_exc())

    def fetch_logs(self):
        """DB 매니저로부터 로그 데이터 로드"""
        try:
            if DEBUG:
                print(f"{DEBUG_TAG['SEND']} DB 매니저에 로그 요청")
                
            # 요청 데이터 생성
            request = b'CMD' + GET_LOGS + b'\n'
            
            if DEBUG:
                print(f"{DEBUG_TAG['SEND']} 로그 요청 명령: {request.hex()}")
            
            # DB 매니저에 소켓 연결
            db_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            db_socket.connect((DB_MANAGER_HOST, DB_MANAGER_PORT))
            
            # 요청 전송
            db_socket.sendall(request)
            
            if DEBUG:
                print(f"{DEBUG_TAG['SEND']} 로그 요청 전송 완료")
            
            # 응답 수신 - 4바이트 헤더(길이) 먼저 수신
            header = b''
            while len(header) < 4:
                chunk = db_socket.recv(4 - len(header))
                if not chunk:
                    raise ConnectionError("DB 매니저와 연결이 종료되었습니다.")
                header += chunk
            
            # 헤더에서 본문 길이 추출
            body_length = int.from_bytes(header, 'big')
            
            if DEBUG:
                print(f"{DEBUG_TAG['RECV']} 헤더 수신 (길이: {body_length})")
            
            # 본문 수신
            body = b''
            while len(body) < body_length:
                chunk = db_socket.recv(min(4096, body_length - len(body)))
                if not chunk:
                    raise ConnectionError("DB 매니저로부터 응답 수신 중 연결이 끊겼습니다.")
                body += chunk
            
            # 소켓 종료
            db_socket.close()
            
            # JSON 파싱
            response_str = body.decode('utf-8')
            log_data = json.loads(response_str)
            
            if DEBUG:
                print(f"{DEBUG_TAG['RECV']} DB 매니저로부터 로그 데이터 수신")
                print(f"  - 로그 개수: {len(log_data.get('logs', []))}")
                print(f"  - 전체 응답 길이: {len(response_str)} 바이트")
                
                # 응답 구조 확인을 위해 첫 번째 로그만 샘플로 출력
                if log_data.get('logs') and len(log_data.get('logs')) > 0:
                    sample_log = log_data.get('logs')[0]
                    print(f"  - 로그 샘플 구조:")
                    for key, value in sample_log.items():
                        print(f"      {key}: {value} (타입: {type(value).__name__})")
                        
                # cmd 필드가 있는지도 확인
                if 'cmd' in log_data:
                    print(f"  - 응답 명령: {log_data.get('cmd')}")
            
            # 로그 데이터 반환
            return log_data.get('logs', [])
            
        except ConnectionRefusedError:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} DB 매니저 연결 실패")
            QMessageBox.warning(self, "연결 실패", "DB 매니저 서버에 연결할 수 없습니다.\n관리자에게 문의하세요.")
            return []  # 연결 실패시 빈 리스트 반환
            
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 로그 로드 실패: {e}")
                print(traceback.format_exc())
            QMessageBox.warning(self, "데이터 로드 실패", f"로그 데이터를 불러오는 중 오류가 발생했습니다.\n{str(e)}")
            return []  # 예외 발생시 빈 리스트 반환
    
    def create_sample_logs(self):
        """실제 DB 데이터를 사용하도록 변경 (샘플 데이터 사용 안함)"""
        if DEBUG:
            print(f"{DEBUG_TAG['INIT']} 로그 데이터 없음 (DB 연결 실패)")
        
        # 빈 로그 데이터 반환
        return []

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
            
            # 현재 탭 객체 획득 (어떤 탭인지 확인용)
            current_tab = self.tabWidget.widget(index)
            
            # 탭이 Case Logs 탭인지 확인
            is_case_logs_tab = (current_tab == self.case_logs_tab)
            
            if is_case_logs_tab:
                # Case Logs 탭으로 이동한 경우 - frozen_status와 무관하게 독립적으로 로그 데이터만 갱신
                if DEBUG:
                    print(f"{DEBUG_TAG['INIT']} Case Logs 탭 활성화, 로그 데이터 요청 (frozen_status 영향 없음)")
                logs = self.fetch_logs()
                self.case_logs_tab.update_logs(logs)  # 로그 업데이트 메소드 호출
                # 로그 업데이트 후 필터 초기화 (탭 진입 시마다 필터 초기화)
                self.case_logs_tab.reset_filter()
            elif index != 0:
                # 모니터링 탭이 아닌 다른 탭으로 이동(설정 탭 등)
                # 상태 표시 고정 (단, 사건이 진행 중인 경우만 - popup_active가 True인 경우)
                if self.popup_active:
                    self.status_frozen = True
                    if DEBUG:
                        print(f"{DEBUG_TAG['INIT']} 상태 표시 고정됨 (진행 중인 사건이 있음)")
                else:
                    # 진행 중인 사건이 없으면 frozen 상태가 되지 않도록 함
                    self.status_frozen = False
                    if DEBUG:
                        print(f"{DEBUG_TAG['INIT']} 상태 표시 유지됨 (진행 중인 사건 없음)")
            elif index == 0:  # 모니터링 탭으로 돌아온 경우
                # 사건이 진행 중(popup_active=True)이고 상태가 고정된 경우(status_frozen=True)에만
                # 고정된 상태 복원, 그렇지 않으면 서버에서 오는 최신 상태 표시
                if self.popup_active and self.status_frozen:
                    self.restore_frozen_status_display()
                    if DEBUG:
                        print(f"{DEBUG_TAG['INIT']} 메인 모니터링 탭 활성화, 고정 상태 복원")
                else:
                    if DEBUG:
                        print(f"{DEBUG_TAG['INIT']} 메인 모니터링 탭 활성화, 일반 상태 흐름")
                
        except Exception as e:
            if DEBUG:
                print(f"{DEBUG_TAG['ERR']} 탭 변경 처리 실패: {e}")
                print(traceback.format_exc())