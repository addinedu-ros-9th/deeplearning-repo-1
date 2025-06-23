# robot/robot_controller.py (사운드 즉시 변경 가능 버전)

import socket
import threading
import os
import pygame
from shared.protocols import (
    FIRE_REPORT,
    POLICE_REPORT,
    ILLEGAL_WARNING,
    DANGER_WARNING,
    EMERGENCY_WARNING
)

# 스크립트 파일의 절대 경로를 기준으로 'sounds' 폴더의 경로를 미리 계산
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SOUNDS_DIR = os.path.join(SCRIPT_DIR, "sounds")

SOUND_MAPPING = {
    FIRE_REPORT: "119_report.mp3",      #안쓰임
    POLICE_REPORT: "112_report.mp3",    #안쓰임 
    ILLEGAL_WARNING: "horn.mp3",
    DANGER_WARNING: "police_siren.mp3",
    EMERGENCY_WARNING: "abulance.mp3"
}


class RobotController(threading.Thread):
    # ... (__init__, run, _handle_connection 메서드는 이전과 동일) ...
    def __init__(self, listen_port):
        super().__init__()
        self.name = "RobotControllerThread"
        self.listen_port = listen_port
        self.server_socket = None
        self.running = True
        try:
            pygame.mixer.init()
            print(f"[{self.name}] 오디오 장치(pygame.mixer) 초기화 성공.")
        except pygame.error as e:
            print(f"[{self.name}] 오디오 장치 초기화 실패: {e}")
            print(f"[{self.name}] 사운드 출력이 불가능합니다. 스피커 연결 또는 OS 설정을 확인하세요.")
            self.running = False
            return
        print(f"[{self.name}] Main Server의 제어 명령 수신 대기 중... (Port: {self.listen_port})")

    def run(self):
        if not self.running:
            return
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(('0.0.0.0', self.listen_port))
        self.server_socket.listen(1)
        while self.running:
            try:
                conn, addr = self.server_socket.accept()
                print(f"[{self.name}] Main Server({addr})와 연결됨.")
                self._handle_connection(conn)
            except socket.error:
                if not self.running: break
                print(f"[{self.name}] 소켓 오류 발생.")
        print(f"[{self.name}] 스레드 종료.")

    def _handle_connection(self, conn):
        try:
            while self.running:
                data = conn.recv(1024)
                if not data:
                    print(f"[{self.name}] Main Server와 연결 끊어짐.")
                    break
                if data.startswith(b'CMD'):
                    command_code = data[3:4]
                    print(f"[✅ TCP 수신] Main Server -> RobotController : Command {command_code.hex()}")
                    sound_file = SOUND_MAPPING.get(command_code)
                    if sound_file:
                        self.play_sound(sound_file)
                    else:
                        print(f"[{self.name}] 알 수 없는 명령어 코드 수신: {command_code.hex()}")
        except ConnectionResetError:
            print(f"[{self.name}] Main Server와 연결이 리셋되었습니다.")
        finally:
            conn.close()

    # ✨✨✨ 핵심 수정 부분 ✨✨✨
    def play_sound(self, sound_file_name):
        """
        지정된 사운드 파일을 'sounds' 폴더에서 찾아 즉시 재생합니다.
        (기존에 재생 중인 사운드는 중지됩니다.)
        """
        sound_path = os.path.join(SOUNDS_DIR, sound_file_name)
        
        if not os.path.exists(sound_path):
            print(f"[⚠️ 로봇 오류] 사운드 파일을 찾을 수 없습니다: {sound_path}")
            return

        try:
            # 1. 먼저 현재 재생 중인 사운드를 즉시 정지합니다.
            pygame.mixer.music.stop()
            
            # 2. 새로운 사운드 파일을 로드합니다.
            pygame.mixer.music.load(sound_path)
            
            # 3. 새로운 사운드를 재생합니다.
            pygame.mixer.music.play()
            
            print(f"[🔊 로봇 동작] '{sound_file_name}' 재생 시작 (이전 사운드 중지됨).")
        except pygame.error as e:
            # 'load'나 'play'에서 발생할 수 있는 오류 처리
            print(f"[{self.name}] 사운드 파일 처리 오류: {e}")

    def stop(self):
        self.running = False
        if self.server_socket:
            self.server_socket.close()


# ... (스크립트 실행 부분은 이전과 동일) ...
if __name__ == '__main__':
    ROBOT_CONTROLLER_PORT = 9008
    
    controller_thread = RobotController(listen_port=ROBOT_CONTROLLER_PORT)
    if controller_thread.running:
        controller_thread.start()
        try:
            controller_thread.join()
        except KeyboardInterrupt:
            print("\n[Main] Ctrl+C 입력. RobotController를 종료합니다.")
            controller_thread.stop()
            controller_thread.join()