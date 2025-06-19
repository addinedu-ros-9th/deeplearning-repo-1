# main_server/data_merger.py

import threading
import queue
import socket
import json
import struct
import time
import base64
import numpy as np
import cv2

# 상수 정의 (shared/protocols.py 또는 system_manager.py에서 가져올 수도 있음)
# DataMerger가 GUI의 서버 역할을 하므로, DataMerger가 리스닝할 포트를 정의합니다.
# 이 포트는 gui/src/main_window.py의 SERVER_PORT와 일치해야 합니다.
# system_manager.py에서 GUI_MERGER_PORT로 정의된 포트입니다.
# 예시:
# TCP_IP = "127.0.0.1" # 현재 PC의 IP
# GUI_MERGER_PORT = 9004 # GUI와 통신할 포트 (system_manager에서 정의된 포트 사용)

class DataMerger(threading.Thread):
    def __init__(self, image_queue, event_queue, gui_addr, robot_status):
        """
        DataMerger 스레드를 초기화합니다.

        Args:
            image_queue (queue.Queue): ImageManager로부터 영상 데이터를 수신하는 큐.
            event_queue (queue.Queue): EventAnalyzer로부터 이벤트 분석 결과를 수신하는 큐.
            gui_addr (tuple): GUI 클라이언트가 연결할 DataMerger의 (IP, Port) 주소.
                               (예: ("127.0.0.1", 9004))
            robot_status (dict): 로봇의 현재 상태를 공유하는 딕셔너리 (공유 메모리).
        """
        super().__init__()
        self.name = "DataMerger"
        self.image_queue = image_queue
        self.event_queue = event_queue
        self.gui_send_queue = queue.Queue() # GUI로 전송할 데이터를 담는 큐
        self.gui_addr = gui_addr # GUI가 연결할 DataMerger의 주소
        self.robot_status = robot_status

        self.running = True

        self.gui_server_socket = None # GUI 클라이언트의 연결을 받을 서버 소켓
        self.gui_client_socket = None # 연결된 GUI 클라이언트 소켓

        # 최근에 수신된 영상 데이터와 이벤트 데이터를 저장하여 병합에 사용
        self.latest_image_data = None
        self.latest_event_data = None

        print(f"[{self.name}] 초기화 완료. GUI 연결 주소: {self.gui_addr}")

    def run(self):
        """
        DataMerger 스레드의 메인 실행 함수입니다.
        ImageManager와 EventAnalyzer로부터 데이터를 수신하고, 이를 병합하여 GUI로 전송합니다.
        """
        print(f"[{self.name}] 스레드 시작.")

        # GUI 클라이언트 연결을 대기하는 스레드 시작
        threading.Thread(target=self._start_gui_server, daemon=True).start()
        # GUI로 데이터를 전송하는 스레드 시작
        threading.Thread(target=self._send_to_gui_thread, daemon=True).start()

        while self.running:
            # ImageManager로부터 영상 데이터 수신
            try:
                # image_queue는 (frame_id, timestamp, JPEG_binary) 형태일 것으로 예상
                frame_id, timestamp, jpeg_binary = self.image_queue.get(timeout=0.1)
                self.latest_image_data = {'frame_id': frame_id, 'timestamp': timestamp, 'jpeg_binary': jpeg_binary}
                print(f"[⬅️ 큐 출력] 5a. DataMerger <- ImageManager : Image for frame_id {frame_id}")
            except queue.Empty:
                pass # 큐가 비어있으면 다음으로 진행
            except Exception as e:
                print(f"[{self.name}] 영상 수신 중 오류: {e}")

            # EventAnalyzer로부터 이벤트 분석 결과 수신
            try:
                # event_queue는 detection_result 스키마를 따르는 딕셔너리 형태일 것으로 예상
                # {'frame_id': ..., 'timestamp': ..., 'detections': [...]}
                event_data = self.event_queue.get(timeout=0.1)
                self.latest_event_data = event_data
                print(f"[⬅️ 큐 출력] 5b. DataMerger <- EventAnalyzer : Event for frame_id {event_data.get('frame_id')}")
            except queue.Empty:
                pass # 큐가 비어있으면 다음으로 진행
            except Exception as e:
                print(f"[{self.name}] 이벤트 수신 중 오류: {e}")

            # 최신 영상 데이터와 최신 이벤트 데이터가 모두 있을 경우 병합하여 GUI 전송 큐에 추가
            # 단, 영상의 frame_id와 이벤트의 frame_id가 일치하는 경우에만 병합하는 것이 이상적
            # 여기서는 단순히 최신 데이터를 사용하므로, 실제 시스템에서는 동기화 로직이 필요할 수 있음.
            if self.latest_image_data and self.latest_event_data:
                # 프레임 ID가 일치하는지 확인 (선택 사항이지만, 정확성을 위해 권장)
                if self.latest_image_data['frame_id'] == self.latest_event_data['frame_id']:
                    self._merge_and_queue_for_gui(self.latest_image_data, self.latest_event_data)
                    print(f"[✈️ GUI 전송준비] 6a. DataMerger (Merged) -> GUI : frame_id {self.latest_image_data['frame_id']}")
                    # 병합 후 사용된 데이터는 초기화 (필요에 따라)
                    self.latest_image_data = None
                    self.latest_event_data = None
                else:
                    # 프레임 ID가 일치하지 않는 경우, 이미지 데이터만이라도 GUI로 전송
                    # 명세서에 'ImageOnly' 시나리오가 있다면 해당 로직을 여기에 구현
                    # 현재 명세서에는 'ImageOnly' 시나리오가 명확하지 않으므로,
                    # 일단은 일치하지 않는 경우 데이터 전송을 하지 않음.
                    # 만약 ImageOnly 전송이 필요하다면 아래와 같이 추가
                    # self._queue_image_only_for_gui(self.latest_image_data)
                    # print(f"[✈️ GUI 전송준비] 6b. DataMerger (ImageOnly) -> GUI : frame_id {self.latest_image_data['frame_id']} (state: {self.robot_status.get('current_state')})")
                    # self.latest_image_data = None # 사용했으니 초기화
                    pass # 여기서는 일단 넘어감

            time.sleep(0.01) # 짧은 지연으로 CPU 사용량 조절

        print(f"[{self.name}] 스레드 종료.")

    def _start_gui_server(self):
        """
        GUI 클라이언트의 연결을 대기하고 수락하는 서버 스레드입니다.
        DataMerger는 GUI로부터 연결을 받는 서버 역할을 수행합니다.
        """
        self.gui_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.gui_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            listen_host, listen_port = self.gui_addr
            self.gui_server_socket.bind((listen_host, listen_port))
            self.gui_server_socket.listen(1) # 단일 GUI 클라이언트 연결만 허용
            print(f"[{self.name}] GUI 클라이언트 연결 대기 중... (IP: {listen_host}, Port: {listen_port})")
        except Exception as e:
            print(f"[{self.name}] GUI 서버 소켓 바인딩/리스닝 오류: {e}")
            self.running = False # 오류 발생 시 스레드 종료

        while self.running:
            try:
                # 일정 시간 동안 연결을 기다립니다.
                self.gui_server_socket.settimeout(1.0) 
                conn, addr = self.gui_server_socket.accept()
                print(f"[{self.name}] GUI 클라이언트 연결됨: {addr}")
                
                # 기존 연결이 있다면 닫고 새로운 연결을 설정합니다.
                if self.gui_client_socket:
                    try: 
                        self.gui_client_socket.shutdown(socket.SHUT_RDWR)
                        self.gui_client_socket.close()
                        print(f"[{self.name}] 이전 GUI 클라이언트 연결 종료.")
                    except Exception as e:
                        print(f"[{self.name}] 이전 GUI 클라이언트 소켓 닫기 오류: {e}")
                self.gui_client_socket = conn
                # 연결이 수락되면, 이제 데이터 전송은 _send_to_gui_thread에서 self.gui_client_socket을 통해 수행됩니다.
            except socket.timeout:
                continue # 타임아웃 발생 시 다시 대기
            except socket.error as e:
                if not self.running:
                    print(f"[{self.name}] 스레드 종료 중 GUI 서버 소켓 오류: {e}")
                    break # 스레드가 종료 중이면 소켓 에러 무시
                print(f"[{self.name}] GUI 서버 소켓 오류: {e}. 재연결 대기 중.")
                time.sleep(1) # 오류 발생 시 잠시 대기 후 재시도
            except Exception as e:
                print(f"[{self.name}] GUI 서버 오류: {e}")
                if not self.running:
                    break
                time.sleep(1)

        print(f"[{self.name}] GUI 서버 스레드 종료.")

    def _merge_and_queue_for_gui(self, image_data, event_data):
        """
        영상 데이터와 이벤트 데이터를 병합하여 GUI 전송 큐에 추가합니다.
        merged_result 스키마에 맞춰 JSON을 구성하고, 영상 위에 탐지 결과를 그립니다.
        """
        try:
            # 1. 원본 이미지 로드
            np_arr = np.frombuffer(image_data['jpeg_binary'], np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

            if frame is None:
                print(f"[{self.name}] 이미지 디코딩 실패. Frame ID: {image_data['frame_id']}")
                return

            # 2. 탐지 결과 그리기
            detections_for_gui = []
            if 'detections' in event_data and event_data['detections']:
                for det in event_data['detections']:
                    label = det.get('label', 'unknown')
                    confidence = det.get('confidence', 0.0)
                    box = det.get('box') # [x1, y1, x2, y2]

                    if box and len(box) == 4:
                        x1, y1, x2, y2 = map(int, box)
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2) # 초록색 박스
                        cv2.putText(frame, f"{label}: {confidence:.2f}", (x1, y1 - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                        
                        # GUI로 전송할 detection 정보 구성 (인터페이스 명세서 merged_result 참고)
                        # 명세서에 따르면 detections 내부에는 label, case만 있으면 됨
                        detection_info = {"label": label}
                        # 특정 레이블에 대해 'case' 필드 추가 (예시)
                        if label in ["knife", "gun"]:
                            detection_info["case"] = "danger"
                        elif label == "쓰러짐": # 예시, 실제 레이블과 매핑 필요
                            detection_info["case"] = "emergency"
                        
                        detections_for_gui.append(detection_info)
            
            # 3. 변경된 이미지를 JPEG 바이너리로 인코딩
            # 이미지 품질을 90으로 설정 (0-100)
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90] 
            result, encoded_image = cv2.imencode('.jpg', frame, encode_param)

            if not result:
                print(f"[{self.name}] 이미지 인코딩 실패. Frame ID: {image_data['frame_id']}")
                return

            modified_jpeg_binary = encoded_image.tobytes()

            # 4. 최종 JSON 데이터 구성
            merged_json_data = {
                "frame_id": image_data['frame_id'],
                "timestamp": event_data['timestamp'], # EventAnalyzer에서 온 timestamp를 사용
                "detections": detections_for_gui, # AI 분석 결과를 가공하여 포함
                "robot_status": self.robot_status.get('current_state', 'idle'), # 로봇 상태 추가
                "location": self.robot_status.get('current_location', 'N/A') # 로봇 위치 추가
            }

            # 5. GUI 전송 큐에 추가
            self.gui_send_queue.put((merged_json_data, modified_jpeg_binary))

        except Exception as e:
            print(f"[{self.name}] 데이터 병합 및 큐 추가 중 오류: {e}")

    def _send_to_gui_thread(self):
        """
        GUI 전송 큐에서 데이터를 가져와 연결된 GUI 클라이언트로 전송합니다.
        DataMerger가 서버 역할을 하므로, 연결된 gui_client_socket을 통해 데이터를 보냅니다.
        """
        while self.running:
            if not self.gui_client_socket:
                # print(f"[{self.name}] GUI가 연결되지 않아 데이터 전송 대기 중...")
                time.sleep(0.5) # GUI 연결 대기
                continue

            try:
                json_data, image_binary = self.gui_send_queue.get(timeout=0.1)

                # 인터페이스 명세서에 따라 JSON + b'|' + Binary + b'\n' 형식으로 패킷 구성
                # JSON 데이터는 UTF-8로 인코딩되어야 합니다.
                json_part = json.dumps(json_data).encode('utf-8')
                data_to_send = json_part + b'|' + image_binary + b'\n' # 명세서에 따르면 마지막에 b'\n'이 추가되어야 함

                # 4바이트 길이 헤더 추가 (TCP 통신 규약에 따름)
                header = struct.pack('>I', len(data_to_send)) # 빅 엔디안 부호 없는 정수

                state_in_packet = json_data.get('robot_status', 'N/A')
                frame_id_in_packet = json_data.get('frame_id')
                packet_size = len(header) + len(data_to_send)

                # 데이터 전송
                self.gui_client_socket.sendall(header + data_to_send)
                print(f"[✈️ GUI 전송] 7. DataMerger -> GUI : frame_id {frame_id_in_packet} (state: {state_in_packet}), size: {packet_size} with drawings")

            except queue.Empty:
                continue # 큐가 비어있으면 다음으로 진행
            except (BrokenPipeError, ConnectionResetError) as e:
                print(f"[{self.name}] GUI 연결 끊어짐: {e}. 재연결 대기 중.")
                # 연결이 끊어졌으므로 클라이언트 소켓을 닫고 다시 연결을 기다립니다.
                if self.gui_client_socket:
                    try: 
                        self.gui_client_socket.shutdown(socket.SHUT_RDWR)
                        self.gui_client_socket.close()
                    except: pass
                self.gui_client_socket = None # 클라이언트 소켓 초기화하여 재연결 대기
            except socket.error as e:
                print(f"[{self.name}] 소켓 전송 오류: {e}. 재연결 대기 중.")
                if self.gui_client_socket:
                    try: 
                        self.gui_client_socket.shutdown(socket.SHUT_RDWR)
                        self.gui_client_socket.close()
                    except: pass
                self.gui_client_socket = None
            except Exception as e:
                print(f"[{self.name}] GUI 전송 중 예상치 못한 오류: {e}")
                time.sleep(0.1) # 오류 발생 시 잠시 대기

        print(f"[{self.name}] GUI 전송 스레드 종료.")

    def stop(self):
        """
        DataMerger 스레드를 안전하게 종료합니다.
        """
        print(f"[{self.name}] 종료 요청 수신.")
        self.running = False
        # 모든 소켓을 닫습니다.
        if self.gui_client_socket:
            try:
                self.gui_client_socket.shutdown(socket.SHUT_RDWR)
                self.gui_client_socket.close()
                print(f"[{self.name}] GUI 클라이언트 소켓 종료.")
            except Exception as e:
                print(f"[{self.name}] GUI 클라이언트 소켓 종료 오류: {e}")
        if self.gui_server_socket:
            try:
                self.gui_server_socket.close()
                print(f"[{self.name}] GUI 서버 소켓 종료.")
            except Exception as e:
                print(f"[{self.name}] GUI 서버 소켓 종료 오류: {e}")