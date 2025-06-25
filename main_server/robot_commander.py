# main_server/robot_commander.py (PROCEED 상태 변경 로직 제외)

import socket
import threading
import queue
# [수정] PROCEED를 임포트 목록에서 제외
from shared.protocols import (
    MOVE_TO_A, MOVE_TO_B, RETURN_TO_BASE, 
    IGNORE, CASE_CLOSED
)

ARUCO_ID_A = 10
ARUCO_ID_B = 20
ARUCO_ID_BASE = 30
ARRIVAL_DISTANCE = 0.1

class RobotCommander(threading.Thread):
    def __init__(self, gui_listen_port, robot_controller_addr, robot_status, aruco_result_queue):
        super().__init__()
        self.name = "RobotCommander"
        self.running = True

        self.robot_status = robot_status
        self.aruco_result_queue = aruco_result_queue
        self.gui_listen_port = gui_listen_port
        self.robot_controller_addr = robot_controller_addr
        self.gui_server_socket = None

    def run(self):
        print(f"[{self.name}] 스레드 시작.")
        self.gui_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.gui_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.gui_server_socket.bind(('0.0.0.0', self.gui_listen_port))
        self.gui_server_socket.listen(1)
        print(f"[{self.name}] GUI의 제어 명령 대기 중... (Port: {self.gui_listen_port})")

        while self.running:
            try:
                conn, addr = self.gui_server_socket.accept()
                print(f"[{self.name}] GUI 클라이언트 연결됨: {addr}")
                handler = threading.Thread(target=self._handle_gui_connection, args=(conn,), daemon=True)
                handler.start()
            except socket.error:
                if not self.running: break
        
        print(f"[{self.name}] 스레드 종료.")

    def _handle_gui_connection(self, conn):
        try:
            while self.running:
                data = conn.recv(1024)
                if not data or not data.startswith(b'CMD'): break
                
                command_code = data[3:4]
                print("-----------------------------------------------------")
                print(f"[✅ TCP 수신] 8. GUI -> {self.name}: Command {command_code.hex()}")

                target_info = {
                    MOVE_TO_A: (ARUCO_ID_A, 'A'),
                    MOVE_TO_B: (ARUCO_ID_B, 'B'),
                    RETURN_TO_BASE: (ARUCO_ID_BASE, 'BASE')
                }.get(command_code)
                
                # [수정] PROCEED를 상태 변경 조건에서 제외
                if command_code in [IGNORE, CASE_CLOSED]:
                    if self.robot_status['state'] == 'detected':
                        print(f"[🚦 시스템 상태] {self.name}: '{command_code.hex()}' 명령 수신. 상태 변경: detected -> patrolling")
                        self.robot_status['state'] = 'patrolling'
                elif target_info:
                    target_id, target_loc = target_info
                    original_state = self.robot_status.get('state')
                    print(f"[🚦 시스템 상태] {self.name}: 상태 변경: {original_state} -> moving")
                    self.robot_status.update({
                        'state': 'moving',
                        'target_marker_id': target_id,
                        'current_location': f"{target_loc} 지역으로 이동 중..."
                    })
                    
                    is_arrival = self._wait_for_arrival(target_id)
                    
                    self.robot_status['target_marker_id'] = None
                    if is_arrival:
                        self.robot_status['current_location'] = target_loc
                        final_state = 'idle' if target_loc == 'BASE' else 'patrolling'
                        print(f"[{self.name}] 목표({target_loc}) 도착! 상태를 '{final_state}'(으)로 변경합니다.")
                        self.robot_status['state'] = final_state
                    else:
                        print(f"[{self.name}] 목표 도착 실패 또는 중단. 상태를 'idle'로 변경합니다.")
                        self.robot_status['state'] = 'idle'
                        self.robot_status['current_location'] = 'BASE'
                else:
                    # PROCEED를 포함하여, 여기서 처리되지 않는 다른 모든 CMD 명령은 로봇 컨트롤러로 직접 전달
                    self._send_command_to_robot(data)

        except (ConnectionResetError, BrokenPipeError):
            print(f"[{self.name}] GUI와 연결이 비정상적으로 끊어졌습니다.")
        finally:
            print(f"[{self.name}] GUI 클라이언트 연결 종료.")
            conn.close()

    def _wait_for_arrival(self, target_id):
        print(f"[{self.name}] ArUco 마커({target_id}) 탐색 및 도착 대기 시작...")
        while self.running and self.robot_status.get('state') == 'moving':
            try:
                result = self.aruco_result_queue.get(timeout=1.0)
                marker_id, distance = result.get('id'), result.get('distance')

                print(f"[⬅️ 큐 출력] 9. {self.name} <- ImageManager: ArUco id={marker_id}, dist={distance:.2f}")
                
                if marker_id == target_id and distance <= ARRIVAL_DISTANCE:
                    print(f"[{self.name}] 목표 거리({ARRIVAL_DISTANCE}m) 내에 도착!")
                    return True
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[{self.name}] 도착 대기 중 오류: {e}")
                break
        return False

    def _send_command_to_robot(self, command_bytes):
        print(f"[✈️ TCP 전송] 10. {self.name} -> RobotController: Command {command_bytes.hex()}")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(self.robot_controller_addr)
                s.sendall(command_bytes)
        except Exception as e:
            print(f"[{self.name}] 로봇 컨트롤러에 명령 전송 실패: {e}")

    def stop(self):
        self.running = False
        if self.gui_server_socket:
            self.gui_server_socket.close()
        print(f"\n[{self.name}] 종료 요청 수신.")