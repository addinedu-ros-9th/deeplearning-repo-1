# robot_app/communication/command_receiver.py
import socket
import time
# [수정] import config -> from .. import config
from .. import config
import json

class CommandReceiver:
    def __init__(self, image_sender):
        self.image_sender = image_sender
        self.server_address = (config.MAIN_SERVER_IP, config.COMMAND_PORT)
        # __init__에서는 소켓을 생성하지 않습니다.
        print(f"명령 수신 대기 -> {self.server_address}")

    def listen(self):
        while True:
            # [수정] 루프가 돌 때마다 새로운 소켓 객체를 생성합니다.
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                self.socket.connect(self.server_address)
                print("Main Server에 연결되었습니다. 명령을 기다립니다...")
                while True:
                    command_str = self.socket.recv(1024).decode('utf-8')
                    if not command_str:
                        print("서버 연결이 끊겼습니다. 재연결을 시도합니다...")
                        self.socket.close() # 소켓을 명시적으로 닫아줍니다.
                        break
                    try:
                        command_data = json.loads(command_str)
                        cmd_type = command_data.get("type")
                        payload = command_data.get("payload")

                        print(f"--- [명령 수신] ---: {command_data}")

                        if cmd_type == "video_control":
                            action = payload.get("action")
                            if action == "start":
                                self.image_sender.start_streaming()
                            elif action == "stop":
                                self.image_sender.stop_streaming()
                    except json.JSONDecodeError:
                        print(f"[경고] 잘못된 형식의 명령 수신: {command_str}")
            except ConnectionRefusedError:
                # 서버가 아직 켜지지 않았을 경우
                print("서버에 연결할 수 없습니다. 3초 후 재시도합니다.")
                self.socket.close() # 실패한 소켓도 닫아줍니다.
                time.sleep(3)
            except Exception as e:
                print(f"명령 수신 중 오류 발생: {e}")
                self.socket.close()
                time.sleep(3)