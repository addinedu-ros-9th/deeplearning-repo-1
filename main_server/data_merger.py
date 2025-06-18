# =====================================================================================
# FILE: main_server/data_merger.py
#
# PURPOSE:
#   - ImageManager, EventAnalyzer로부터 각각 이미지와 분석 결과를 큐(Queue)로 수신.
#   - 'frame_id'를 기준으로 두 데이터를 동기화하고 병합.
#   - TCP 서버 역할을 수행하여 GUI 클라이언트의 연결을 대기하고 수락.
#   - 병합된 최종 데이터(JSON + 이미지)를 연결된 GUI 클라이언트에 지속적으로 전송.
#   - SystemManager에 의해 스레드로 생성되고 관리됨.
#
# 주요 로직:
#   1. DataMerger (메인 스레드):
#      - 각 기능(이미지 처리, 이벤트 처리, 버퍼 정리, GUI 서버)을 수행할 워커 스레드들을 생성하고 관리.
#   2. _process_image_queue (워커 스레드 1):
#      - image_queue에서 (frame_id, 이미지, 타임스탬프)를 꺼냄.
#      - GUI에 실시간 스트리밍을 위해 '기본 데이터'를 즉시 gui_send_queue에 추가.
#      - 짝이 되는 이벤트가 버퍼에 있는지 확인하고, 있다면 병합하여 gui_send_queue에 추가.
#      - 없다면 이미지를 image_buffer에 저장.
#   3. _process_event_queue (워커 스레드 2):
#      - event_queue에서 '분석 결과(JSON)'를 꺼냄.
#      - 짝이 되는 이미지가 버퍼에 있는지 확인하고, 있다면 병합하여 gui_send_queue에 추가.
#      - 없다면 분석 결과를 event_buffer에 저장.
#   4. _cleanup_buffers (워커 스레드 3):
#      - 주기적으로 image_buffer와 event_buffer를 검사하여 오래된 데이터를 삭제 (메모리 누수 방지).
#   5. _gui_server_thread (워커 스레드 4 - 서버 역할):
#      - TCP 서버 소켓을 열고 GUI 클라이언트의 연결을 기다림 (listen, accept).
#      - 클라이언트가 연결되면, gui_send_queue에서 최종 병합된 데이터를 꺼내 지속적으로 전송.
#      - 클라이언트 연결이 끊어지면 다시 연결을 기다림.
# =====================================================================================

import threading
import queue
import time
import socket
import json
import struct

class DataMerger(threading.Thread):
    BUFFER_TIMEOUT = 5

    def __init__(self, image_queue, event_queue, gui_addr):
        super().__init__()
        self.name = "DataMergerThread"
        self.running = False

        # 데이터 처리용 큐
        self.image_queue = image_queue
        self.event_queue = event_queue
        
        # GUI 전송용 서버 설정
        self.gui_addr = gui_addr
        self.gui_client_socket = None
        self.gui_send_queue = queue.Queue(maxsize=100) # GUI로 보낼 데이터를 쌓아둘 큐

        # 데이터 동기화용 버퍼
        self.image_buffer = {}
        self.event_buffer = {}
        self.lock = threading.Lock()

    def run(self):
        self.running = True
        print(f"[{self.name}] 스레드 시작.")

        # 워커 스레드 생성 및 시작
        threading.Thread(target=self._process_image_queue, daemon=True).start()
        threading.Thread(target=self._process_event_queue, daemon=True).start()
        threading.Thread(target=self._cleanup_buffers, daemon=True).start()
        
        # GUI 클라이언트 연결을 처리하고 데이터를 전송하는 서버 스레드 시작
        threading.Thread(target=self._gui_server_thread, daemon=True).start()

        while self.running:
            time.sleep(1)

        print(f"[{self.name}] 스레드 종료 중...")

    def stop(self):
        print(f"[{self.name}] 종료 요청 수신.")
        self.running = False
        if self.gui_client_socket:
            self.gui_client_socket.close()

    def _gui_server_thread(self):
        """[서버 스레드] GUI 클라이언트의 연결을 받고, 큐의 데이터를 전송합니다."""
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(self.gui_addr)
        server_socket.listen(1)
        print(f"[{self.name}] GUI 클라이언트 연결 대기 중... (TCP: {self.gui_addr})")

        while self.running:
            try:
                self.gui_client_socket, addr = server_socket.accept()
                print(f"[{self.name}] GUI 클라이언트 연결됨: {addr}")

                while self.running and self.gui_client_socket:
                    try:
                        event_data, image_binary = self.gui_send_queue.get(timeout=1)
                        
                        json_part = json.dumps(event_data).encode('utf-8')
                        data_to_send = json_part + b'|' + image_binary
                        header = struct.pack('>I', len(data_to_send))

                        self.gui_client_socket.sendall(header + data_to_send)
                        print(f"[✈️ 전달] 5. DataMerger -> GUI: frame_id {event_data.get('frame_id')}, status: {event_data.get('robot_status')}, size {len(header) + len(data_to_send)} bytes")

                    except queue.Empty:
                        continue
                    except (socket.error, BrokenPipeError, ConnectionResetError) as e:
                        print(f"[{self.name}] GUI 클라이언트와 연결이 끊어졌습니다: {e}")
                        self.gui_client_socket.close()
                        self.gui_client_socket = None
                        break
            
            except Exception as e:
                print(f"[{self.name}] GUI 서버 스레드 오류: {e}")
                time.sleep(1)

        server_socket.close()
        print(f"[{self.name}] GUI 서버 스레드 종료.")

    def _put_data_to_gui_queue(self, event_data, image_binary):
        """병합된 데이터를 GUI 전송 큐에 넣습니다."""
        if not self.gui_send_queue.full():
            self.gui_send_queue.put((event_data, image_binary))

    def _process_image_queue(self):
        """[워커 1] image_queue 처리."""
        while self.running:
            try:
                frame_id, image_binary, timestamp = self.image_queue.get(timeout=1)
                
                print(f"[⬅️ 큐 출력] 4a. DataMerger: Image 큐에서 frame_id {frame_id} 수신")

                streaming_data = {
                    'frame_id': frame_id,
                    'timestamp': timestamp,
                    'detections': [],
                    'robot_status': 'streaming'
                }
                self._put_data_to_gui_queue(streaming_data, image_binary)

                with self.lock:
                    if frame_id in self.event_buffer:
                        event_data, _ = self.event_buffer.pop(frame_id)
                        event_data['robot_status'] = 'detected'
                        self._put_data_to_gui_queue(event_data, image_binary)
                        print(f"[{self.name}] 빠른 이벤트와 병합 (frame_id={frame_id}). GUI 상태 업데이트.")
                    else:
                        self.image_buffer[frame_id] = (image_binary, time.time())
            except queue.Empty:
                continue

    def _process_event_queue(self):
        """[워커 2] event_queue 처리."""
        while self.running:
            try:
                event_data = self.event_queue.get(timeout=1)

                frame_id = event_data['frame_id']
                print(f"[⬅️ 큐 출력] 4b. DataMerger: Event 큐에서 frame_id {frame_id} 수신")

                with self.lock:
                    if frame_id in self.image_buffer:
                        image_binary, _ = self.image_buffer.pop(frame_id)
                        event_data['robot_status'] = 'detected'
                        self._put_data_to_gui_queue(event_data, image_binary)
                        print(f"[{self.name}] 이벤트 큐에서 병합 성공 (frame_id={frame_id}).")
                    else:
                        self.event_buffer[frame_id] = (event_data, time.time())
            except queue.Empty:
                continue

    def _cleanup_buffers(self):
        """[워커 3] 주기적으로 버퍼 정리"""
        while self.running:
            time.sleep(self.BUFFER_TIMEOUT)
            with self.lock:
                current_time = time.time()
                expired_images = [fid for fid, (_, ts) in self.image_buffer.items() if current_time - ts > self.BUFFER_TIMEOUT]
                for fid in expired_images:
                    del self.image_buffer[fid]
                    print(f"[{self.name}] 버퍼 정리: 오래된 이미지 데이터(frame_id={fid}) 삭제.")
                
                expired_events = [fid for fid, (_, ts) in self.event_buffer.items() if current_time - ts > self.BUFFER_TIMEOUT]
                for fid in expired_events:
                    del self.event_buffer[fid]
                    print(f"[{self.name}] 버퍼 정리: 오래된 이벤트 데이터(frame_id={fid}) 삭제.")