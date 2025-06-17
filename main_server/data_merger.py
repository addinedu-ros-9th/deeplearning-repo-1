# =====================================================================================
# FILE: main_server/data_merger.py
#
# PURPOSE:
#   - ImageManager로부터 받은 이미지와 EventAnalyzer로부터 받은 AI 분석 결과를 병합하는 역할.
#   - 'frame_id'를 기준으로 두 데이터 스트림의 싱크를 맞춤.
#   - 병합된 최종 결과(JSON + 이미지)를 GUI 클라이언트로 TCP 전송하여 사용자가 상황을 인지하도록 함.
#   - 로봇이 'moving' 상태일 때는 AI 분석 결과가 없더라도, ImageManager가 보낸
#     'ArUco 마커가 그려진 영상'을 GUI로 전송하는 특수 처리를 수행.
#
# 주요 로직:
#   1. 다중 스레드 실행:
#      - _image_thread: image_queue에서 이미지를 받아 버퍼(image_buffer)에 저장.
#      - _event_thread: event_queue에서 이벤트를 받아 버퍼(event_buffer)에 저장.
#      - _merge_data_thread: 두 버퍼에서 frame_id가 일치하는 데이터를 찾아 병합 후 gui_send_queue에 삽입.
#      - _send_to_gui_thread: gui_send_queue에서 최종 데이터를 꺼내 GUI로 전송.
#   2. 버퍼 관리 및 클린업 (_cleanup_buffers):
#      - 버퍼에 데이터가 너무 오래 머무는 것을 방지하기 위해 주기적으로 실행.
#      - [핵심 로직] 'moving' 상태 등에서 이벤트 없이 이미지만 있는 경우,
#        상태 정보를 포함한 기본 JSON을 생성하여 이미지만이라도 GUI로 전송.
#      - 이를 통해 '이동 중'인 로봇의 ArUco 탐지 상황을 GUI에서 실시간으로 확인 가능.
# =====================================================================================

# -------------------------------------------------------------------------------------
# [섹션 1] 모듈 임포트
# -------------------------------------------------------------------------------------
import socket
import threading
import queue
import json
import struct
import time
from datetime import datetime, timedelta

# -------------------------------------------------------------------------------------
# [섹션 2] DataMerger 클래스 정의
# -------------------------------------------------------------------------------------
class DataMerger(threading.Thread):
    def __init__(self, image_queue, event_queue, gui_addr, robot_status):
        super().__init__()
        self.name = "DataMergerThread"
        self.running = True
        self.image_queue = image_queue
        self.event_queue = event_queue
        self.robot_status = robot_status
        self.image_buffer = {}
        self.event_buffer = {}
        self.gui_send_queue = queue.Queue()
        self.gui_addr = gui_addr
        self.gui_client_socket = None
        self.buffer_lock = threading.Lock()

    def run(self):
        # GUI 연결은 _send_to_gui_thread에서 필요할 때 시도하도록 변경
        threads = [
            threading.Thread(target=self._image_thread, daemon=True),
            threading.Thread(target=self.event_thread, daemon=True),
            threading.Thread(target=self._merge_data_thread, daemon=True),
            threading.Thread(target=self._send_to_gui_thread, daemon=True)
        ]
        for t in threads:
            t.start()
        while self.running:
            time.sleep(1)
        print(f"[{self.name}] 스레드 종료.")

    def _connect_to_gui(self):
        if self.gui_client_socket:
             self.gui_client_socket.close()
        
        while self.running:
            try:
                print(f"[{self.name}] GUI({self.gui_addr})에 연결 시도 중...")
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect(self.gui_addr)
                self.gui_client_socket = sock
                print(f"[{self.name}] GUI에 성공적으로 연결되었습니다.")
                break
            except ConnectionRefusedError:
                print(f"[{self.name}] GUI 연결 거부. 5초 후 재시도합니다.")
                time.sleep(5)
            except Exception as e:
                print(f"[{self.name}] GUI 연결 중 알 수 없는 오류: {e}")
                time.sleep(5)

    def _image_thread(self):
        while self.running:
            try:
                header_json, image_binary = self.image_queue.get(timeout=1)
                frame_id = header_json['frame_id']
                print(f"[⬅️ 큐 출력] 5a. DataMerger <- ImageManager : Image for frame_id {frame_id}")
                with self.buffer_lock:
                    self.image_buffer[frame_id] = (image_binary, datetime.now(), header_json.get('timestamp'))
            except queue.Empty:
                continue

    def event_thread(self):
        while self.running:
            try:
                event_data = self.event_queue.get(timeout=1)
                frame_id = event_data['frame_id']
                print(f"[⬅️ 큐 출력] 5b. DataMerger <- EventAnalyzer : Event for frame_id {frame_id}")
                with self.buffer_lock:
                    self.event_buffer[frame_id] = (event_data, datetime.now())
            except queue.Empty:
                continue

    def _merge_data_thread(self):
        while self.running:
            merged_ids = set()
            with self.buffer_lock:
                common_ids = self.image_buffer.keys() & self.event_buffer.keys()
                for frame_id in common_ids:
                    image_binary, _, _ = self.image_buffer[frame_id]
                    event_data, _ = self.event_buffer[frame_id]
                    print(f"[✈️ GUI 전송준비] 6a. DataMerger (Merged) -> GUI : frame_id {frame_id}")
                    self.gui_send_queue.put((event_data, image_binary))
                    merged_ids.add(frame_id)
                for frame_id in merged_ids:
                    del self.image_buffer[frame_id]
                    del self.event_buffer[frame_id]
            self._cleanup_buffers()
            time.sleep(0.01)

    def _cleanup_buffers(self):
        now = datetime.now()
        cleanup_ids = set()
        with self.buffer_lock:
            for frame_id, (_, timestamp, _) in self.image_buffer.items():
                if now - timestamp > timedelta(seconds=2):
                    cleanup_ids.add(frame_id)
            for frame_id in cleanup_ids:
                if frame_id in self.image_buffer and frame_id not in self.event_buffer:
                    image_binary, _, original_timestamp = self.image_buffer[frame_id]
                    default_event_data = {
                        "frame_id": frame_id, "timestamp": original_timestamp,
                        "detections": [], "robot_status": self.robot_status.get('state', 'unknown')
                    }
                    print(f"[✈️ GUI 전송준비] 6b. DataMerger (ImageOnly) -> GUI : frame_id {frame_id} (state: {self.robot_status.get('state')})")
                    self.gui_send_queue.put((default_event_data, image_binary))
                    del self.image_buffer[frame_id]

    def _send_to_gui_thread(self):
        self._connect_to_gui() # 스레드 시작 시 먼저 연결 시도
        while self.running:
            try:
                event_data, image_binary = self.gui_send_queue.get(timeout=1)
                json_part = json.dumps(event_data).encode('utf-8')
                data_to_send = json_part + b'|' + image_binary
                header = struct.pack('>I', len(data_to_send))
                
                state_in_packet = event_data.get('robot_status', 'N/A')
                frame_id_in_packet = event_data.get('frame_id')
                packet_size = len(header) + len(data_to_send)
                print(f"[✈️ TCP 전송] 7. DataMerger -> GUI : Final packet for frame_id {frame_id_in_packet} (state: {state_in_packet}), size: {packet_size}")
                
                if self.gui_client_socket:
                    self.gui_client_socket.sendall(header + data_to_send)
                else:
                    print(f"[{self.name}] GUI가 연결되지 않아 데이터 전송 실패. 재연결 시도.")
                    self._connect_to_gui()
            except queue.Empty:
                continue
            except (BrokenPipeError, ConnectionResetError, socket.error) as e:
                print(f"[{self.name}] GUI 연결 끊어짐: {e}. 재연결을 시도합니다.")
                self._connect_to_gui()
            except Exception as e:
                print(f"[{self.name}] GUI 전송 중 오류: {e}")

    def stop(self):
        self.running = False
        if self.gui_client_socket:
            self.gui_client_socket.close()
        print(f"[{self.name}] 종료 요청 수신.")