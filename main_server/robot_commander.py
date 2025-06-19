# =====================================================================================
# FILE: main_server/robot_commander.py (수정 완료)
#
# PURPOSE:
#   - GUI로부터 사용자의 제어 명령(지역 이동, 긴급 대응 등)을 수신하는 사령탑(Commander) 역할.
#   - 시스템의 핵심 두뇌로, 로봇의 전반적인 상태와 위치를 직접 변경.
#   - '지역 이동' 명령 수신 시, 로봇 상태를 'moving'으로, 위치를 '이동 중'으로 변경.
#   - ArUco 마커 탐지 결과를 수신하여 목표 지점 도착 여부를 판단.
#   - 목표 지점 도착 시, 로봇 상태를 'patrolling'으로, 위치를 최종 목적지로 변경.
# =====================================================================================

# -------------------------------------------------------------------------------------
# [섹션 1] 모듈 임포트
# -------------------------------------------------------------------------------------
import socket
import threading
import queue
# ✨ shared 폴더의 프로토콜 모듈에서 명령어 코드를 모두 임포트하도록 수정
from shared.protocols import MOVE_TO_A, MOVE_TO_B, RETURN_TO_BASE

# -------------------------------------------------------------------------------------
# [섹션 2] 전역 상수 정의
# -------------------------------------------------------------------------------------
ARUCO_ID_A = 10         # A 지역을 나타내는 ArUco 마커의 ID
ARUCO_ID_B = 20         # B 지역을 나타내는 ArUco 마커의 ID
ARUCO_ID_BASE = 30       # ✨ 기지(BASE)를 나타내는 ArUco 마커 ID 추가
ARRIVAL_DISTANCE = 0.2  # 로봇이 지역에 도착했다고 판단할 거리 (단위: m)

# -------------------------------------------------------------------------------------
# [섹션 3] RobotCommander 클래스 정의
# -------------------------------------------------------------------------------------
class RobotCommander(threading.Thread):
    """
    GUI 명령을 수신하여 로봇의 상태와 위치를 제어하고, 실제 로봇에 명령을 전달하는 클래스.
    """
    def __init__(self, gui_listen_port, robot_controller_addr, robot_status, aruco_result_queue):
        super().__init__()
        self.name = "RobotCommanderThread"
        self.running = True

        self.robot_status = robot_status
        self.aruco_result_queue = aruco_result_queue
        self.gui_listen_port = gui_listen_port
        self.robot_controller_addr = robot_controller_addr
        self.gui_server_socket = None

    def run(self):
        """스레드의 메인 루프: GUI의 연결을 받아 처리 스레드를 생성합니다."""
        self.gui_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.gui_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.gui_server_socket.bind(('0.0.0.0', self.gui_listen_port))
        self.gui_server_socket.listen(1)
        print(f"[{self.name}] GUI의 제어 명령 대기 중... (Port: {self.gui_listen_port})")

        while self.running:
            try:
                conn, addr = self.gui_server_socket.accept()
                print(f"[{self.name}] GUI 클라이언트 연결됨: {addr}")
                # ✨ 각 클라이언트 연결을 별도 스레드로 처리하여 여러 클라이언트의 동시 접속이나 재접속에 유연하게 대응
                handler_thread = threading.Thread(target=self._handle_gui_connection, args=(conn,), daemon=True)
                handler_thread.start()
            except socket.error:
                if not self.running: break
                print(f"[{self.name}] 소켓 오류 발생.")
        
        print(f"[{self.name}] 스레드 종료.")

    def _handle_gui_connection(self, conn):
        """GUI로부터 받은 명령을 처리하고, 상태를 변경하거나 로봇에 전달합니다."""
        try:
            while self.running:
                data = conn.recv(1024)
                if not data or not data.startswith(b'CMD'):
                    break
                
                command_code = data[3:4]
                print(f"[✅ TCP 수신] 8. GUI -> RobotCommander : Command {command_code.hex()}")

                target_id = None
                target_location_name = None
                
                if command_code == MOVE_TO_A:
                    target_id = ARUCO_ID_A
                    target_location_name = 'A'
                elif command_code == MOVE_TO_B:
                    target_id = ARUCO_ID_B
                    target_location_name = 'B'
                elif command_code == RETURN_TO_BASE:
                    target_id = ARUCO_ID_BASE
                    target_location_name = 'BASE'

                if target_id is not None:
                    # 1. 로봇의 상태와 '이동 중' 위치 정보 업데이트
                    print(f"[🚦 시스템 상태] RobotCommander: 상태 변경: {self.robot_status.get('state')} -> moving")
                    self.robot_status['state'] = 'moving'
                    self.robot_status['target_marker_id'] = target_id
                    self.robot_status['current_location'] = f"{target_location_name} 지역으로 이동 중..."
                    
                    # 2. 목표 지점에 도착할 때까지 대기
                    is_arrival_success = self._wait_for_arrival(target_id)
                    
                    # ✨ 3. 수정된 로직: 도착 위치에 따라 상태를 다르게 설정
                    if is_arrival_success:
                        # 먼저 도착 위치를 설정
                        self.robot_status['current_location'] = target_location_name

                        # 도착지가 BASE인지 확인
                        if target_location_name == 'BASE':
                            self.robot_status['state'] = 'idle' # 상태를 'idle'로 변경
                            print(f"[{self.name}] 기지({target_location_name}) 복귀 완료! 로봇 상태를 'idle'로 변경합니다.")
                        else: # 도착지가 A 또는 B인 경우
                            self.robot_status['state'] = 'patrolling' # 상태를 'patrolling'으로 변경
                            print(f"[{self.name}] 목표 지역({target_location_name}) 도착! 로봇 상태를 'patrolling'으로 변경합니다.")
                    else:
                        # 도착 실패 또는 중단 시 'idle' 상태 및 초기 위치로 복귀
                        self.robot_status['state'] = 'idle'
                        self.robot_status['current_location'] = 'BASE'
                        print(f"[{self.name}] 목표 지역 도착 실패. 로봇 상태를 'idle'로 변경합니다.")
                    
                    self.robot_status['target_marker_id'] = None
                else:
                    self._send_command_to_robot(data)

        except (ConnectionResetError, BrokenPipeError):
            print(f"[{self.name}] GUI와 연결이 비정상적으로 끊어졌습니다.")
        except Exception as e:
            print(f"[{self.name}] GUI 연결 처리 중 오류: {e}")
        finally:
            print(f"[{self.name}] GUI 클라이언트 연결 종료.")
            conn.close()


    def _wait_for_arrival(self, target_id):
        """
        aruco_result_queue에서 결과를 받아 도착 여부를 판단합니다.
        ✨ 도착 성공 시 True, 실패 또는 중단 시 False를 반환합니다.
        """
        print(f"[{self.name}] ArUco 마커({target_id}) 탐색 및 도착 대기 시작...")
        while self.running and self.robot_status.get('state') == 'moving':
            try:
                result = self.aruco_result_queue.get(timeout=1.0)
                marker_id = result.get('id')
                distance = result.get('distance')

                print(f"[⬅️ 큐 출력] 9. RobotCommander <- ImageManager : ArUco id={marker_id}, dist={distance:.2f}")
                
                if marker_id == target_id:
                    if distance <= ARRIVAL_DISTANCE:
                        print(f"[{self.name}] 목표 거리({ARRIVAL_DISTANCE}m) 내에 도착!")
                        return True # ✨ 도착 성공
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[{self.name}] 도착 대기 중 오류: {e}")
                break
        
        return False # ✨ 루프가 중단되거나 state가 바뀌면 도착 실패

    def _send_command_to_robot(self, command_bytes):
        """수신한 명령을 로봇 컨트롤러에 TCP로 전송합니다."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as robot_socket:
                robot_socket.connect(self.robot_controller_addr)
                robot_socket.sendall(command_bytes)
                print(f"[{self.name}] 로봇 컨트롤러로 명령 전송 완료: {command_bytes.hex()}")
        except Exception as e:
            print(f"[{self.name}] 로봇 컨트롤러에 명령 전송 실패: {e}")

    def stop(self):
        """스레드를 안전하게 종료하는 메서드."""
        self.running = False
        if self.gui_server_socket:
            self.gui_server_socket.close()
        print(f"[{self.name}] 종료 요청 수신.")