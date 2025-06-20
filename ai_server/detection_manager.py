import socket
import threading
import json
import struct
import time
from queue import Queue
from yolo_detector import YOLODetector
import numpy as np
import cv2


HOST_IP = "127.0.0.1"
UDP_PORT = 9002 # AI 서버가 수신 대기하는 포트
TCP_PORT = 9003 # Main 서버에 송신하는 포트


class DetectionManager:
    def __init__(self, sender_host=HOST_IP, sender_tcp_port=TCP_PORT, udp_port=UDP_PORT):
        self.sender_host = sender_host
        self.sender_tcp_port = sender_tcp_port
        self.udp_port = udp_port

        self.detector = YOLODetector()
        self.send_queue = Queue()  # TCP로 보낼 예측 결과 저장
        self.tcp_socket = None
        self.tcp_lock = threading.Lock()

    def tcp_sender_thread(self):
        """TCP 연결을 유지하면서 큐에서 꺼내 전송"""
        while True:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.connect((self.sender_host, self.sender_tcp_port))
                    self.tcp_socket = sock
                    print(f"[TCP] sender에 연결됨: {self.sender_host}:{self.sender_tcp_port}", flush=True)

                    while True:
                        response = self.send_queue.get()  # 큐에서 꺼냄
                        data = json.dumps(response).encode()
                        length_prefix = struct.pack("!I", len(data))
                        sock.sendall(length_prefix + data + b'\n')

                        print(f"[📤TCP 전송] all={response}")
                        # print(f"[TCP 전송] 데이터 길이={[len(data)]}, frame_id={response['frame_id']}, 객체={len(response['detections'])}건", flush=True)
                        print(f"[📤TCP 전송] ai_server -> main_server: frame_id={response['frame_id']}, jsonbytes={[len(data)]}, 객체={len(response['detections'])}건")

            except Exception as e:
                print("[TCP 오류] 연결 종료 또는 실패:", e)
                self.tcp_socket = None
                time.sleep(1)  # 재연결 대기

    def udp_listener(self):
        """sender로부터 UDP로 들어오는 프레임 수신 후 예측"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('0.0.0.0', self.udp_port))
        print(f"[UDP] 이미지 수신 대기 중 (포트 {self.udp_port})")

        last_frame_id = -1

        while True:
            try:
                data, _ = sock.recvfrom(65535)
                print(f"-----------------------------------------------------------------------------")
                print(f"[UDP 수신] 총 데이터 길이: {len(data)} bytes", flush=True)
                json_end = data.find(b'}') + 1
                if json_end == 0:
                    print("[UDP] JSON 헤더 파싱 실패")
                    continue

                json_part = data[:json_end]
                jpeg_bytes = data[json_end + 1:-1]

                header = json.loads(json_part.decode())
                print(f"[UDP] 수신 json: {header} ")
                frame_id = header.get("frame_id")
                timestamp = header.get("timestamp")
                print(f"[UDP] JSON 부분 길이: {json_end} / JPEG 길이: {len(jpeg_bytes)}", flush=True)

                if frame_id == last_frame_id:
                    print(f"[UDP] 중복 frame_id={frame_id} → 생략")
                    continue
                last_frame_id = frame_id

                # JPEG 디코딩 (추가 코드)
                nparr = np.frombuffer(jpeg_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

                # 시각화 (추가 코드)
                cv2.imshow("UDP Frame", frame)
                cv2.waitKey(1)

                # 예측 수행
                response = self.detector.predict_raw(frame_id, timestamp, jpeg_bytes)

                # 예측 결과를 TCP 큐에 추가
                self.send_queue.put(response)

                print(f"[✅UDP 수신] 1. Robot → ImageManager: frame_id={frame_id}, timestamp={timestamp}")
                # print(f"[UDP 수신] frame_id={frame_id}, 객체={len(response['detections'])}건", flush=True)

            except Exception as e:
                print("[⚠️UDP 처리 오류]", e)

    def start(self):
        """UDP 수신 + TCP 송신 스레드 시작"""
        threading.Thread(target=self.udp_listener, daemon=True).start()
        threading.Thread(target=self.tcp_sender_thread, daemon=True).start()

        print("[DetectionManager] 실행 중... Ctrl+C로 종료")
        threading.Event().wait()


if __name__ == "__main__":
    manager = DetectionManager(
        sender_host=HOST_IP,
        sender_tcp_port=TCP_PORT,
        udp_port=UDP_PORT
    )
    manager.start()