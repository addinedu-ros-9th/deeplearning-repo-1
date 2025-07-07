import socket
import threading
import json
import struct
import time
from queue import Queue
from yolo_detector import YOLODetector
import cv2
import numpy as np
# from mediapipe_detector import MediaPipeDetector  # 미디어 파이프 추가
from yolo_pose import YOLOPoseDetector
from queue import Empty  # 위에 추가
import datetime  # 위쪽에 추가



HOST_IP = "192.168.0.38"
UDP_PORT = 9002 # AI 서버가 수신 대기하는 포트
TCP_PORT = 9003 # Main 서버에 송신하는 포트

#-------------------------------------
# 통신 개선 , conf조절,  계산 필요
#-------------------------------------
# HOST_IP = "127.0.0.1"
# UDP_PORT = 9200 # AI 서버가 수신 대기하는 포트
# TCP_PORT = 9102 # Main 서버에 송신하는 포트


class DetectionManager:
    def __init__(self, sender_host=HOST_IP, sender_tcp_port=TCP_PORT, udp_port=UDP_PORT):
        self.sender_host = sender_host
        self.sender_tcp_port = sender_tcp_port
        self.udp_port = udp_port

        self.yolo_detector = YOLODetector() # # YOLO 객체 탐지기, 총, 칼
        # self.mediapipe_detector = MediaPipeDetector()  # MediaPipe 디텍터 추가
        self.yolo_pose_detector = YOLOPoseDetector()

        self.send_queue = Queue()  # TCP로 보낼 예측 결과 저장
        self.tcp_socket = None
        self.tcp_lock = threading.Lock() # TCP 소켓 보호용 Lock
        self.recv_time_queue = Queue()  # 수신 시간 전용

        self.recv_time_map = {}  # frame_id → recv_time 저장



    def tcp_sender_thread(self):
        """TCP 연결을 유지하면서 큐에서 꺼내 전송"""
        while True:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(5.0) # 연결 타임아웃 설정
                    sock.connect((self.sender_host, self.sender_tcp_port))
                    self.tcp_socket = sock
                    print(f"[TCP] sender에 연결됨: {self.sender_host}:{self.sender_tcp_port}", flush=True)

                    while True:
                        try:
                            response = self.send_queue.get()  # 예측 결과 큐에서 꺼냄
                            data = json.dumps(response).encode() # JSON 직렬화
                            length_prefix = struct.pack("!I", len(data)) # 길이 프리픽스
                            sock.sendall(length_prefix + data + b'\n') # 데이터 전송

                            print(f"[TCP 전송] json = {response}")
                            # print(f"[TCP 전송] 데이터 길이={[len(data)]}, frame_id={response['frame_id']}, 객체={len(response['detections'])}건", flush=True)
                            print(f"[📤 전송] . Dectection_manager → event_analyzer: frame_id={response['frame_id']}, 데이터 길이={[len(data)]}, 객체={len(response['detections'])}건")

                    

                            recv_time = self.recv_time_map.pop(response['frame_id'], None)
                            if recv_time is not None:
                                delay = time.time() - recv_time
                                print(f"[⏱ 지연] frame_id={response['frame_id']} → TCP 전송까지 {delay:.3f}초")
                            else:
                                print(f"[⏱ 경고] frame_id={response['frame_id']}의 수신 시간 없음 (TCP 재연결 후일 수 있음)")
                            
                            print("-----------------------------------------------------")


                        except Empty:
                            # 큐에 데이터가 없으면 계속 대기 (문제 아님)
                            continue
                        except Exception as e:
                            print("[TCP 오류] 데이터 전송 중 문제 발생:", e)
                            break  # 내부 루프 탈출 후 재연결

            except Exception as e:
                print("[TCP 오류] 연결 종료 또는 실패:", e)
                self.tcp_socket = None
                time.sleep(1)  # 재연결 대기


    def udp_listener(self):
        """sender로부터 UDP로 들어오는 프레임 수신 후 예측"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('0.0.0.0', self.udp_port))
        print(f"-----------------------------------------------------")
        print(f"[UDP] 이미지 수신 대기 중 (포트 {self.udp_port})")

        last_frame_id = -1 # 중복 수신 방지용

        while True:
            try:
                data, _ = sock.recvfrom(65535) # 최대 크기 수신
                # print(f"[UDP 수신] 총 데이터 길이: {len(data)} bytes", flush=True)
                recv_time = time.time() # 수신 시간 기록
                

                self.recv_time_queue.put(recv_time) # 이미지 받은 시간 저장

                # JSON 헤더 추출
                json_end = data.find(b'}') + 1
                if json_end == 0:
                    print("[UDP] JSON 헤더 파싱 실패")
                    continue

                json_part = data[:json_end]
                jpeg_bytes = data[json_end + 1:-1]

                header = json.loads(json_part.decode())
                frame_id = header.get("frame_id")
                timestamp = header.get("timestamp")
                # print(f"[UDP] JSON 부분 길이: {json_end} / JPEG 길이: {len(jpeg_bytes)}", flush=True)
                self.recv_time_map[frame_id] = recv_time
                
                if frame_id == last_frame_id:
                    print(f"[UDP] 중복 frame_id={frame_id} → 생략")
                    continue
                last_frame_id = frame_id

                # JPEG 디코딩 (추가 코드)
                nparr = np.frombuffer(jpeg_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

                # 시각화 (추가 코드)
                # cv2.imshow("UDP Frame", frame)
                # cv2.waitKey(1)

                # YOLO 예측, 총, 칼 탕지
                yolo_result = self.yolo_detector.predict_raw(frame_id, timestamp, jpeg_bytes, 0.65)

                # MediaPipe 예측 현재는 사용X
                # mediapipe_result = self.mediapipe_detector.predict_raw(frame_id, timestamp, jpeg_bytes)
                
                # POSE 에측, 쓰러짐, 담배 탐지
                pose_result = self.yolo_pose_detector.predict_raw(frame_id, timestamp, jpeg_bytes, 0.5)

                # 결과 병합
                merged_result = {
                    "frame_id": frame_id,
                    "timestamp": timestamp,
                    "detections": yolo_result.get("detections", []) + pose_result.get("detections", [])
                }
                

                # TCP 전송 큐에 병합 결과 추가
                self.send_queue.put(merged_result)
                print("-----------------------------------------------------")
                print(f"[✅ 수신] 1. ImageManager → Dectection_manager: frame_id={frame_id}, timestamp={timestamp}, all_size={len(data)} bytes")

            except Exception as e:
                print("[UDP 처리 오류]", e)

    def start(self):
        """UDP 수신 + TCP 송신 스레드 시작"""
        threading.Thread(target=self.udp_listener, daemon=True).start()
        threading.Thread(target=self.tcp_sender_thread, daemon=True).start()

        print("[DetectionManager] 실행 중... Ctrl+C로 종료")
        threading.Event().wait()


if __name__ == "__main__":
    # 매니저 생성 및 실행
    manager = DetectionManager(
        sender_host=HOST_IP,
        sender_tcp_port=TCP_PORT,
        udp_port=UDP_PORT
    )
    manager.start()
