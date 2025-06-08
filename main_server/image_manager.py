# main_server/image_manager.py
import socket
import threading
import cv2
import numpy as np

class ImageManager:
    """로봇 PC로부터 UDP 영상을 수신하여 2가지 작업을 수행합니다.
    1. 분석용 프레임 큐에 영상 프레임(cv2.Mat)을 넣습니다.
    2. GUI 클라이언트로 원본 영상 데이터(jpeg)를 TCP로 전달합니다.
    """
    def __init__(self, frame_queue, udp_host='0.0.0.0', udp_port=9998, tcp_host='127.0.0.1', tcp_port=9997):
        self.frame_queue = frame_queue
        
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.bind((udp_host, udp_port))
        
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_socket.bind((tcp_host, tcp_port))
        
        self.gui_connections = []
        self.lock = threading.Lock()

    def start(self):
        print("[이미지 매니저] 시작됨. 영상 수신 및 전달 대기 중...")
        threading.Thread(target=self._accept_gui_connections, daemon=True).start()
        threading.Thread(target=self._receive_and_process, daemon=True).start()

    def _accept_gui_connections(self):
        self.tcp_socket.listen(1)
        while True:
            try:
                conn, addr = self.tcp_socket.accept()
                with self.lock:
                    print(f"[이미지 매니저] GUI 영상 채널 연결됨: {addr}")
                    self.gui_connections.append(conn)
            except Exception as e:
                print(f"[이미지 매니저] GUI 연결 수락 중 오류: {e}")


    def _receive_and_process(self):
        while True:
            try:
                data, _ = self.udp_socket.recvfrom(65535)
                
                # 1. SystemManager로 영상 프레임 전달 (분석용)
                frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    if self.frame_queue.full():
                        self.frame_queue.get_nowait() # 큐가 꽉 찼으면 가장 오래된 프레임 제거
                    self.frame_queue.put(frame)

                # 2. GUI로 원본 영상 데이터 전달 (모니터링용)
                with self.lock:
                    for conn in list(self.gui_connections):
                        try:
                            # 데이터 길이를 먼저 보내고 실제 데이터를 전송
                            conn.sendall(len(data).to_bytes(4, 'big') + data)
                        except socket.error:
                            print(f"[이미지 매니저] GUI 클라이언트 연결 끊김. 목록에서 제거.")
                            self.gui_connections.remove(conn)
            except Exception as e:
                print(f"[이미지 매니저] UDP 수신/처리 오류: {e}")