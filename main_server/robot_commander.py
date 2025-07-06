# =====================================================================================
# FILE: main_server/robot_commander.py
#
# PURPOSE:
#   - GUI(사용자 인터페이스)로부터 제어 명령을 수신하고, 이를 로봇의 상태 변경이나
#     실제 로봇(RobotController)에 대한 명령으로 변환하여 전달하는 '중앙 지휘관' 역할.
#   - 로봇의 자율 주행(네비게이션) 과정을 관리. 이동 명령을 받으면 목표 ArUco 마커 ID를
#     설정하고, ImageManager로부터 전달받는 ArUco 탐지 결과를 지속적으로 확인하여
#     목표 지점 도착 여부를 판단.
#   - 시스템의 핵심 상태('state')를 직접 변경하는 주요 컴포넌트 중 하나. 예를 들어,
#     'patrolling' -> 'moving' -> 'idle' 과 같은 상태 전환을 주도.
#
# 주요 로직:
#   1. 전역 상수:
#      - 각 지역(A, B, BASE)에 해당하는 ArUco 마커 ID와 도착으로 간주할 거리(m)를 정의.
#   2. RobotCommander 클래스:
#      - __init__():
#        - GUI로부터 TCP 명령을 수신하기 위한 서버 소켓을 생성하고 리슨 상태로 전환.
#        - ImageManager로부터 ArUco 탐지 결과를 받기 위한 `aruco_result_queue`를 연결.
#        - 로봇의 실제 제어를 담당하는 `RobotController`의 주소를 저장.
#      - run():
#        - 메인 스레드 루프. GUI 클라이언트의 연결을 수락하고, 각 연결마다
#          `_handle_gui_connection` 스레드를 생성하여 독립적으로 처리.
#      - _handle_gui_connection():
#        - 수신된 TCP 데이터가 'CMD'로 시작하는지 확인하여 유효한 명령인지 검사.
#        - 명령 코드를 분석하여 '이동 명령'과 '기타 명령'으로 분기.
#        - 이동 명령 (MOVE_TO_A, B, BASE):
#          a. `robot_status['state']`를 'moving'으로 변경하고, 목표 마커 ID를 설정.
#          b. `_wait_for_arrival` 메서드를 호출하여 목표 도착까지 대기.
#          c. 도착 결과(성공/실패)에 따라 로봇 상태를 'patrolling' 또는 'idle'로 최종 변경.
#        - 상태 변경 명령 (IGNORE, CASE_CLOSED):
#          a. 현재 상태가 'detected'일 경우, 'patrolling'으로 상태를 변경하여 일상 순찰 모드로 복귀시킴.
#        - 기타 명령 (경고, 신고 등):
#          a. `_send_command_to_robot` 메서드를 통해 수신된 명령을 RobotController에 그대로 전달.
#      - _wait_for_arrival():
#        - 로봇 상태가 'moving'인 동안 `aruco_result_queue`에서 탐지 결과를 계속해서 꺼내옴.
#        - 꺼내온 결과의 마커 ID와 거리가 목표와 일치하는지 확인.
#        - 목표 거리에 도달하면 True를 반환하여 이동 완료를 알림.
#      - _send_command_to_robot():
#        - 주어진 명령 바이트를 `RobotController`의 주소로 TCP 전송.
# =====================================================================================

# -------------------------------------------------------------------------------------
# [섹션 1] 모듈 임포트
# -------------------------------------------------------------------------------------
import socket # TCP/IP 통신을 위한 소켓 모듈
import threading # 다중 스레딩 기능을 위한 모듈
import queue # 스레드 간 안전한 데이터 교환을 위한 큐 모듈
# shared.protocols 모듈에서 필요한 명령어 상수들을 임포트
from shared.protocols import (
    MOVE_TO_A, MOVE_TO_B, RETURN_TO_BASE, 
    IGNORE, CASE_CLOSED
)

# -------------------------------------------------------------------------------------
# [섹션 2] 전역 상수 정의
# -------------------------------------------------------------------------------------
ARUCO_ID_A = 10 # A 지역에 해당하는 ArUco 마커 ID
ARUCO_ID_B = 20 # B 지역에 해당하는 ArUco 마커 ID
ARUCO_ID_BASE = 30 # BASE(기지)에 해당하는 ArUco 마커 ID
ARRIVAL_DISTANCE = 0.5 # 로봇이 목표 마커에 도착했다고 판단할 거리(미터 단위)

# -------------------------------------------------------------------------------------
# [섹션 3] RobotCommander 클래스 정의
# -------------------------------------------------------------------------------------
class RobotCommander(threading.Thread):
    def __init__(self, gui_listen_port, robot_controller_addr, robot_status, aruco_result_queue):
        super().__init__()
        self.name = "RobotCommander"
        self.running = True

        # --- 공유 자원 및 외부 설정 초기화 ---
        self.robot_status = robot_status # 시스템 전역 로봇 상태 공유 객체
        self.aruco_result_queue = aruco_result_queue # ImageManager로부터 ArUco 결과를 받을 큐
        self.gui_listen_port = gui_listen_port # GUI의 제어 명령을 수신할 포트
        self.robot_controller_addr = robot_controller_addr # 실제 로봇 제어부(RobotController)의 주소
        self.gui_server_socket = None # GUI 연결을 위한 서버 소켓

    def run(self):
        """스레드 메인 루프. GUI 클라이언트의 연결을 수락하고 처리."""
        print(f"[{self.name}] 스레드 시작.")
        self.gui_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # TCP 소켓 생성
        self.gui_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # 주소 재사용 옵션 설정
        self.gui_server_socket.bind(('0.0.0.0', self.gui_listen_port)) # 모든 인터페이스의 지정된 포트에서 수신 대기
        self.gui_server_socket.listen(1) # 연결 대기열 크기를 1로 설정
        print(f"[{self.name}] GUI의 제어 명령 대기 중... (Port: {self.gui_listen_port})")

        while self.running:
            try:
                conn, addr = self.gui_server_socket.accept() # 클라이언트 연결 수락
                print(f"[{self.name}] GUI 클라이언트 연결됨: {addr}")
                # 각 클라이언트 연결을 별도의 스레드에서 처리하여 동시 요청에 대응
                handler = threading.Thread(target=self._handle_gui_connection, args=(conn,), daemon=True)
                handler.start()
            except socket.error:
                if not self.running: break
        
        print(f"[{self.name}] 스레드 종료.")

    def _handle_gui_connection(self, conn):
        """연결된 GUI 클라이언트로부터 명령을 수신하고 처리."""
        try:
            while self.running:
                data = conn.recv(1024) # 최대 1024바이트 데이터 수신
                # 데이터가 없거나 'CMD'로 시작하지 않으면 유효하지 않은 명령으로 간주하고 루프 종료
                if not data or not data.startswith(b'CMD'): break
                
                command_code = data[3:4] # 명령어 코드 부분 추출 (CMD 다음 1바이트)
                print("-----------------------------------------------------")
                print(f"[✅ TCP 수신] 8. GUI -> {self.name}: Command {command_code.hex()}")

                # 이동 명령인지 확인하기 위한 딕셔너리
                target_info = {
                    MOVE_TO_A: (ARUCO_ID_A, 'A'),
                    MOVE_TO_B: (ARUCO_ID_B, 'B'),
                    RETURN_TO_BASE: (ARUCO_ID_BASE, 'BASE')
                }.get(command_code)
                
                # --- 명령에 따른 분기 처리 ---
                if command_code in [IGNORE, CASE_CLOSED]:
                    # '무시' 또는 '사건 종료' 명령 시, 현재 상태가 'detected'이면 'patrolling'으로 변경
                    if self.robot_status['state'] == 'detected':
                        print(f"[🚦 시스템 상태] {self.name}: '{command_code.hex()}' 명령 수신. 상태 변경: detected -> patrolling")
                        self.robot_status['state'] = 'patrolling'
                elif target_info:
                    # 이동 명령 처리
                    target_id, target_loc = target_info
                    original_state = self.robot_status.get('state')
                    print(f"[🚦 시스템 상태] {self.name}: 상태 변경: {original_state} -> moving")
                    # 로봇 상태를 'moving'으로 변경하고, 목표 마커 ID와 현재 위치 설명을 업데이트
                    self.robot_status.update({
                        'state': 'moving',
                        'target_marker_id': target_id,
                        'current_location': f"{target_loc} 지역으로 이동 중..."
                    })
                    
                    # 목표 지점 도착 대기
                    is_arrival = self._wait_for_arrival(target_id)
                    
                    self.robot_status['target_marker_id'] = None # 목표 마커 ID 초기화
                    if is_arrival:
                        # 도착 성공 시
                        self.robot_status['current_location'] = target_loc
                        final_state = 'idle' if target_loc == 'BASE' else 'patrolling'
                        print(f"[{self.name}] 목표({target_loc}) 도착! 상태를 '{final_state}'(으)로 변경합니다.")
                        self.robot_status['state'] = final_state
                    else:
                        # 도착 실패 또는 중단 시
                        print(f"[{self.name}] 목표 도착 실패 또는 중단. 상태를 'idle'로 변경합니다.")
                        self.robot_status['state'] = 'idle'
                        self.robot_status['current_location'] = 'BASE'
                else:
                    # 위에서 처리되지 않은 다른 모든 명령(경고, 신고 등)은 로봇 컨트롤러로 직접 전달
                    self._send_command_to_robot(data)

        except (ConnectionResetError, BrokenPipeError):
            print(f"[{self.name}] GUI와 연결이 비정상적으로 끊어졌습니다.")
        finally:
            print(f"[{self.name}] GUI 클라이언트 연결 종료.")
            conn.close()

    def _wait_for_arrival(self, target_id):
        """목표 ArUco 마커가 탐지되고 지정된 거리 내에 들어올 때까지 대기."""
        print(f"[{self.name}] ArUco 마커({target_id}) 탐색 및 도착 대기 시작...")
        while self.running and self.robot_status.get('state') == 'moving':
            try:
                # aruco_result_queue에서 1초 타임아웃으로 데이터 가져오기
                result = self.aruco_result_queue.get(timeout=1.0)
                marker_id, distance = result.get('id'), result.get('distance')

                print(f"[⬅️ 큐 출력] 9. {self.name} <- ImageManager: ArUco id={marker_id}, dist={distance:.2f}")
                
                # 탐지된 마커 ID가 목표와 같고, 거리가 도착 기준 거리보다 가까우면 도착으로 판단
                if marker_id == target_id and distance <= ARRIVAL_DISTANCE:
                    print(f"[{self.name}] 목표 거리({ARRIVAL_DISTANCE}m) 내에 도착!")
                    return True
            except queue.Empty:
                continue # 큐가 비어있으면 계속 대기
            except Exception as e:
                print(f"[{self.name}] 도착 대기 중 오류: {e}")
                break
        return False # 루프가 중단되면 도착 실패로 간주

    def _send_command_to_robot(self, command_bytes):
        """주어진 명령을 실제 로봇(RobotController)에 TCP로 전송."""
        print(f"[✈️ TCP 전송] 10. {self.name} -> RobotController: Command {command_bytes.hex()}")
        try:
            # RobotController에 연결하고 명령 전송
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(self.robot_controller_addr)
                s.sendall(command_bytes)
        except Exception as e:
            print(f"[{self.name}] 로봇 컨트롤러에 명령 전송 실패: {e}")

    def stop(self):
        """스레드를 안전하게 종료."""
        self.running = False
        if self.gui_server_socket:
            self.gui_server_socket.close() # 서버 소켓을 닫아 run 루프의 accept()에서 빠져나오게 함
        print(f"\n[{self.name}] 종료 요청 수신.")