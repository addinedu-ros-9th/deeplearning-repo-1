from pydub import AudioSegment
from pydub.playback import play
import socket
import threading
import os


SOUND_MAP = {
    "1": "robot/sounds/horn.mp3",
    "2": "robot/sounds/police.mp3",
    "3": "robot/sounds/police_siren.mp3",
    "4": "robot/sounds/ambulance.mp3",
}

def handle_client(conn, addr):
    print(f"[클라이언트 연결됨] {addr}")
    while True:
        data = conn.recv(1024)
        if not data:
            break
        command = data.decode().strip().upper() # 날라오는 모든 메세지를 대문자로
        print(f"[수신] {command}")

        if command in SOUND_MAP:
            mp3_path = SOUND_MAP[command]
            if os.path.exists(mp3_path):
                print(f"[실행] {mp3_path} 재생")

                sound = AudioSegment.from_file(mp3_path, format="mp3")
                play(sound) 

                conn.sendall(b"PLAYED") # 해당 MP3 가 모두 플레이 되면 그제서야 답변해줌
            else:
                conn.sendall(b"MP3_NOT_FOUND") # 음성 파일이 없을때
        else:
            conn.sendall(b"UNKNOWN_COMMAND")
    conn.close()

def start_server():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind(("0.0.0.0", 8282))  # 모든 IP에서 접속 허용
    server_socket.listen(1)
    print("[서버 실행중] 포트 8282에서 대기 중...")

    while True:
        conn, addr = server_socket.accept()
        thread = threading.Thread(target=handle_client, args=(conn, addr))
        thread.start()

if __name__ == "__main__":
    start_server()
