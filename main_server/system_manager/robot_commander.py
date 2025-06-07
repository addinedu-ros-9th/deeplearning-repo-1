import socket

def send_commands():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("192.168.219.106", 8282))  # 서버 연결 유지

    try:
        while True:
            command = input("[발신] ") 
            if command.lower() == "exit": # exit 입력시 프로그램 종료됨
                break  # fianlly 로 넘어감
            sock.sendall(command.encode())           # 명령 전송
            response = sock.recv(1024).decode()      # 응답 수신
            print(f"[서버 응답] {response}")
    finally:
        sock.close()
        print("연결 종료됨")

if __name__ == "__main__":
    send_commands()
