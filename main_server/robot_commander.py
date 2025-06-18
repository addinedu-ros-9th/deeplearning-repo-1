# =====================================================================================
# FILE: main_server/robot_commander.py
#
# PURPOSE:
#   - GUI로부터 사용자의 제어 명령(지역 이동, 긴급 대응 등)을 수신하는 사령탑(Commander) 역할.
#   - 시스템의 핵심 두뇌로, 로봇의 전반적인 상태('idle', 'moving', 'patrolling')를 직접 변경.
#   - '지역 이동' 명령 수신 시, 로봇 상태를 'moving'으로 전환하고 ImageManager로부터
#     ArUco 마커 탐지 결과를 수신하여 목표 지점 도착 여부를 판단.
#   - 목표 지점 도착 시, 로봇 상태를 'patrolling'으로 전환하여 시스템 전체에 전파.
#   - 지역 이동 외의 일반 명령은 로봇 컨트롤러(robot_controller)로 전달하는 역할 수행.
#
# 주요 로직:
#   1. 전역 상수:
#      - A, B 지역에 해당하는 ArUco 마커 ID와 도착으로 판단할 임계 거리를 정의.
#   2. RobotCommander 클래스:
#      - __init__(): SystemManager로부터 로봇 상태 공유 객체(robot_status)와 ArUco 결과 수신용
#        큐(aruco_result_queue)를 전달받음.
#      - run(): GUI의 연결을 기다리는 TCP 서버를 실행. 연결 시 _handle_gui_connection 호출.
#      - _handle_gui_connection(): GUI로부터 명령을 지속적으로 수신하고 파싱.
#        - 이동 명령(MOVE_TO_A, MOVE_TO_B)인 경우, 상태를 'moving'으로 변경하고
#          _wait_for_arrival()을 호출하여 도착할 때까지 대기. 도착 후 상태를 'patrolling'으로 변경.
#        - 그 외 명령인 경우, _send_command_to_robot()을 통해 로봇에 직접 전달.
#      - _wait_for_arrival(): aruco_result_queue를 감시하며, 목표 ID의 마커가
#        임계 거리 내로 탐지되면 루프를 종료.
#      - _send_command_to_robot(): 수신한 명령을 로봇 컨트롤러에 TCP로 전송.
#      - stop(): 스레드를 안전하게 종료하기 위한 메서드.
# =====================================================================================

# -------------------------------------------------------------------------------------
# [섹션 1] 모듈 임포트
# -------------------------------------------------------------------------------------
import socket # 네트워크 통신을 위한 소켓 모듈 임포트
import threading # 스레드 기능을 사용하기 위한 모듈 임포트
import queue # 큐 자료구조를 사용하기 위한 모듈 임포트
# shared 폴더의 프로토콜 모듈에서 명령어 코드들을 임포트
from shared.protocols import MOVE_TO_A, MOVE_TO_B

# -------------------------------------------------------------------------------------
# [섹션 2] 전역 상수 정의
# -------------------------------------------------------------------------------------
ARUCO_ID_A = 10         # A 지역을 나타내는 ArUco 마커의 ID
ARUCO_ID_B = 20         # B 지역을 나타내는 ArUco 마커의 ID
ARRIVAL_DISTANCE = 0.5  # 로봇이 지역에 도착했다고 판단할 거리 (단위: m)

# -------------------------------------------------------------------------------------
# [섹션 3] RobotCommander 클래스 정의
# -------------------------------------------------------------------------------------
class RobotCommander(threading.Thread):
    """
    GUI 명령을 수신하여 로봇의 상태를 제어하고, 실제 로봇에 명령을 전달하는 클래스.
    """
    def __init__(self, gui_listen_port, robot_controller_addr, robot_status, aruco_result_queue):
        super().__init__()
        self.name = "RobotCommanderThread" # 스레드 이름 설정
        self.running = True # 스레드 실행 상태를 제어하는 플래그

        # SystemManager로부터 공유 객체 및 큐를 전달받음
        self.robot_status = robot_status # 로봇 상태 공유 딕셔너리
        self.aruco_result_queue = aruco_result_queue # ArUco 탐지 결과 수신용 큐

        # 네트워크 설정
        self.gui_listen_port = gui_listen_port # GUI의 명령을 수신할 포트
        self.robot_controller_addr = robot_controller_addr # 명령을 전달할 로봇 컨트롤러 주소
        self.gui_server_socket = None # GUI와 통신할 서버 소켓

    def run(self): # 스레드가 시작될 때 호출되는 메인 루프
        self.gui_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.gui_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.gui_server_socket.bind(('0.0.0.0', self.gui_listen_port))
        self.gui_server_socket.listen(1)
        print(f"[{self.name}] GUI의 제어 명령 대기 중... (Port: {self.gui_listen_port})")

        while self.running:
            try:
                # GUI 클라이언트의 연결을 기다림
                conn, addr = self.gui_server_socket.accept()
                print(f"[{self.name}] GUI 클라이언트 연결됨: {addr}")
                # 연결된 클라이언트로부터 명령을 처리하는 메서드 호출
                self._handle_gui_connection(conn)
            except socket.error as e:
                # self.running이 False가 되어 소켓이 닫힐 때 발생하는 예외는 무시
                if not self.running:
                    break
                print(f"[{self.name}] 소켓 오류: {e}")
        
        print(f"[{self.name}] 스레드 종료.")

    def _handle_gui_connection(self, conn):
        """GUI로부터 받은 명령을 처리하고, 상태를 변경하거나 로봇에 전달합니다."""
        try:
            while self.running:
                # GUI로부터 최대 1024바이트의 데이터를 수신
                data = conn.recv(1024)
                # 데이터가 없거나, 'CMD'로 시작하지 않으면 연결 종료로 간주
                if not data or not data.startswith(b'CMD'):
                    print(f"[{self.name}] GUI 클라이언트 연결 종료됨.")
                    break
                
                # 수신된 데이터에서 명령어 코드(1바이트)를 추출
                command_code = data[3:4]
                print(f"[✅ TCP 수신] 8. GUI -> RobotCommander : Command {command_code.hex()}")

                target_id = None
                # 명령어 코드가 'A지역 이동'인지 확인
                if command_code == MOVE_TO_A:
                    target_id = ARUCO_ID_A
                    print(f"[{self.name}] A지역 이동 명령 수신 (Target ID: {target_id})")
                # 명령어 코드가 'B지역 이동'인지 확인
                elif command_code == MOVE_TO_B:
                    target_id = ARUCO_ID_B
                    print(f"[{self.name}] B지역 이동 명령 수신 (Target ID: {target_id})")

                # target_id가 설정되었다면 (즉, 이동 명령이라면)
                if target_id is not None:
                    
                    # 1. 로봇의 상태를 'moving'으로 변경하고 목표 마커 ID를 설정
                    print(f"[🚦 시스템 상태] RobotCommander: 상태 변경: {self.robot_status.get('state')} -> moving")
                    self.robot_status['state'] = 'moving'
                    self.robot_status['target_marker_id'] = target_id
                    print(f"[{self.name}] 로봇 상태 변경 -> 'moving'")
                    
                    # 2. 목표 지점에 도착할 때까지 대기 (Blocking Call)
                    self._wait_for_arrival(target_id)
                    
                    # 3. 도착 후, 로봇 상태를 'patrolling'으로 변경
                    print(f"[🚦 시스템 상태] RobotCommander: 상태 변경: {self.robot_status.get('state')} -> patrolling")
                    self.robot_status['state'] = 'patrolling'
                    self.robot_status['target_marker_id'] = None
                    print(f"[{self.name}] 목표 지역 도착! 로봇 상태 변경 -> 'patrolling'")
                else:
                    # 그 외의 일반 명령은 로봇 컨트롤러로 전달
                    self._send_command_to_robot(data)

        except (ConnectionResetError, BrokenPipeError):
            print(f"[{self.name}] GUI와 연결이 비정상적으로 끊어졌습니다.")
        except Exception as e:
            print(f"[{self.name}] GUI 연결 처리 중 오류: {e}")
        finally:
            conn.close()

    def _wait_for_arrival(self, target_id):
        """aruco_result_queue에서 결과를 받아 도착 여부를 판단합니다."""
        print(f"[{self.name}] ArUco 마커({target_id}) 탐색 및 도착 대기 시작...")
        while self.running and self.robot_status['state'] == 'moving':
            try:
                # 큐에서 데이터가 올 때까지 최대 1초간 대기
                result = self.aruco_result_queue.get(timeout=1.0)
                
                marker_id = result.get('id')
                distance = result.get('distance')

                print(f"[⬅️ 큐 출력] 9. RobotCommander <- ImageManager : ArUco id={marker_id}, dist={distance:.2f}")
                # 탐지된 마커가 목표 마커와 일치하는지 확인
                if marker_id == target_id:
                    print(f"[{self.name}] 타겟 마커({marker_id}) 발견! 거리: {distance:.2f}m")
                    # 거리가 설정된 임계값보다 가까운지 확인
                    if distance <= ARRIVAL_DISTANCE:
                        print(f"[{self.name}] 목표 거리({ARRIVAL_DISTANCE}m) 내에 도착!")
                        break # 도착했으므로 while 루프 탈출
            
            except queue.Empty:
                # 1초 동안 큐에 데이터가 없으면 '아직 이동 중'으로 간주하고 계속 대기
                continue
            except Exception as e:
                print(f"[{self.name}] 도착 대기 중 오류: {e}")
                break # 예기치 않은 오류 발생 시 루프 종료

    def _send_command_to_robot(self, command_bytes):
        """수신한 명령을 로봇 컨트롤러에 TCP로 전송합니다."""
        try:
            # 로봇 컨트롤러와 일회성으로 연결할 소켓 생성
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as robot_socket:
                robot_socket.connect(self.robot_controller_addr)
                robot_socket.sendall(command_bytes)
                print(f"[{self.name}] 로봇 컨트롤러로 명령 전송 완료: {command_bytes.hex()}")
        except Exception as e:
            print(f"[{self.name}] 로봇 컨트롤러에 명령 전송 실패: {e}")

    def stop(self): # 스레드를 안전하게 종료하는 메서드
        self.running = False # 메인 루프 종료를 위한 플래그 설정
        # run() 메서드에서 accept() 대기 상태를 해제하기 위해 소켓을 닫음
        if self.gui_server_socket:
            self.gui_server_socket.close()
        print(f"[{self.name}] 종료 요청 수신.")