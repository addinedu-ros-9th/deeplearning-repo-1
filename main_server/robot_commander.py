# main_server/robot_commander.py
import socket
import json
from shared.protocols import create_request

class RobotCommander:
    """
    SystemManager의 결정을 받아 로봇에게 실제 명령을 전송하는 역할.
    """
    def __init__(self, robot_socket: socket.socket):
        if not isinstance(robot_socket, socket.socket):
            raise TypeError("robot_socket must be a socket object")
        self.robot_socket = robot_socket

    def _send_command(self, req_type: str, payload: dict):
        """공통 명령 전송 메서드"""
        if self.robot_socket:
            try:
                request_bytes = create_request(req_type, payload)
                self.robot_socket.sendall(request_bytes)
                print(f"[RobotCommander] -> Robot: {request_bytes.decode('utf-8')}")
                return True
            except (BrokenPipeError, ConnectionResetError) as e:
                print(f"[RobotCommander] 로봇 연결 오류: {e}")
                self.robot_socket = None # 연결이 끊겼으므로 소켓을 무효화
                return False
        return False

    def move_to(self, destination: str):
        """로봇 이동 명령 전송"""
        return self._send_command("move_robot", {"destination": destination})

    def control_video(self, action: str):
        """비디오 스트리밍 제어 명령 (start/stop)"""
        return self._send_command("video_control", {"action": action})

    def send_human_decision(self, command: str):
        """사람의 개입 명령 전송 (예: EMERGENCY_STOP)"""
        return self._send_command("human_decision", {"command": command})