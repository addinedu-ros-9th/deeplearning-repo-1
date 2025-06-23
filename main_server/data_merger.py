# # =====================================================================================
# # FILE: main_server/data_merger.py (사용자 요청 반영 버전)
# #
# # PURPOSE:
# #   - ImageManager(영상)와 EventAnalyzer(AI 분석 결과)로부터 데이터를 수신.
# #   - 수신된 데이터를 'frame_id' 기준으로 병합.
# #   - 병합된 최종 데이터(JSON + 이미지)를 인터페이스 명세서에 맞춰 GUI로 전송.
# #   - GUI의 연결 요청을 받는 '서버' 역할 수행.
# #
# # 주요 로직:
# #   1. 버퍼 기반 병합 및 상태별 동작:
# #      - idle/moving 상태: 짧은 타임아웃 후 ImageOnly 데이터 전송.
# #      - patrolling 상태: 타임아웃 없이 AI 결과와 이미지가 병합될 때까지 대기.
# #   2. 멀티스레드 아키텍처:
# #      - GUI 연결 수락, 이미지 수신, 이벤트 수신, 데이터 병합, GUI 전송을
# #        각각의 전담 스레드로 분리하여 성능 및 안정성 극대화.
# # =====================================================================================

# # -------------------------------------------------------------------------------------
# # [섹션 1] 모듈 임포트
# # -------------------------------------------------------------------------------------
# import threading
# import queue
# import socket
# import json
# import struct
# import time
# import cv2
# import numpy as np
# from datetime import datetime, timedelta

# # -------------------------------------------------------------------------------------
# # [섹션 2] DataMerger 클래스 정의
# # -------------------------------------------------------------------------------------
# class DataMerger(threading.Thread):
#     """
#     이미지와 AI 분석 결과를 병합하여 GUI로 전송하는 데이터 허브 클래스.
#     """
#     # ==================== 초기화 메서드 ====================
#     def __init__(self, image_queue, event_queue, gui_listen_addr, robot_status):
#         super().__init__()
#         self.name = "DataMerger"
#         self.running = True

#         # --- 공유 자원 및 큐 연결 ---
#         self.image_queue = image_queue
#         self.event_queue = event_queue
#         self.gui_send_queue = queue.Queue(maxsize=100)
#         self.robot_status = robot_status

#         # --- 데이터 병합을 위한 버퍼 ---
#         self.image_buffer = {}
#         self.event_buffer = {}
#         self.buffer_lock = threading.Lock()

#         # --- GUI 연결을 위한 서버 소켓 설정 ---
#         self.gui_listen_addr = gui_listen_addr
#         self.gui_server_socket = None
#         self.gui_client_socket = None

#         print(f"[{self.name}] 초기화 완료. GUI 연결 대기 주소: {self.gui_listen_addr}")

#     # ==================== 메인 실행 메서드 ====================
#     def run(self):
#         print(f"[{self.name}] 스레드 시작.")
#         threads = [
#             threading.Thread(target=self._gui_accept_thread, daemon=True, name="GuiAcceptThread"),
#             threading.Thread(target=self._gui_send_thread, daemon=True, name="GuiSendThread"),
#             threading.Thread(target=self._image_receive_thread, daemon=True, name="ImageRecvThread"),
#             threading.Thread(target=self._event_receive_thread, daemon=True, name="EventRecvThread"),
#             threading.Thread(target=self._merge_thread, daemon=True, name="MergeThread")
#         ]
#         for t in threads:
#             t.start()
#         while self.running:
#             time.sleep(1)
#         print(f"[{self.name}] 메인 스레드 종료.")

#     # ==================== 하위 기능 스레드들 ====================
#     def _gui_accept_thread(self):
#         self.gui_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#         self.gui_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
#         self.gui_server_socket.bind(self.gui_listen_addr)
#         self.gui_server_socket.listen(1)
#         print(f"[{self.name}] GUI 클라이언트 연결 대기 중... ({self.gui_listen_addr})")
#         while self.running:
#             try:
#                 conn, addr = self.gui_server_socket.accept()
#                 print(f"[{self.name}] GUI 클라이언트 연결됨: {addr}")
#                 if self.gui_client_socket:
#                     self.gui_client_socket.close()
#                 self.gui_client_socket = conn
#             except socket.error:
#                 if not self.running: break
#                 time.sleep(1)

#     def _image_receive_thread(self):
#         while self.running:
#             try:
#                 frame_id, timestamp, jpeg_binary = self.image_queue.get(timeout=1)
#                 print(f"[⬅️ 큐 출력] 5a. DataMerger <- ImageManager : Image for frame_id {frame_id}")
#                 with self.buffer_lock:
#                     self.image_buffer[frame_id] = (jpeg_binary, timestamp, datetime.now())
#             except queue.Empty:
#                 continue

#     def _event_receive_thread(self):
#         while self.running:
#             try:
#                 event_data = self.event_queue.get(timeout=1)
#                 frame_id = event_data['frame_id']
#                 print(f"[⬅️ 큐 출력] 5b. DataMerger <- EventAnalyzer : Event for frame_id {frame_id}")
#                 with self.buffer_lock:
#                     self.event_buffer[frame_id] = (event_data, datetime.now())
#             except queue.Empty:
#                 continue

#     def _merge_thread(self):
#         """(스레드 4) 버퍼를 주기적으로 확인하여 데이터를 병합하고 오래된 데이터를 정리합니다."""
#         while self.running:
#             processed_ids = set()
#             with self.buffer_lock:
#                 current_state = self.robot_status.get('state', 'idle')
                
#                 # '완전체' 데이터 병합
#                 common_ids = self.image_buffer.keys() & self.event_buffer.keys()
#                 for frame_id in common_ids:
#                     jpeg_binary, _, _ = self.image_buffer[frame_id]
#                     event_data, _ = self.event_buffer[frame_id]
#                     self._queue_merged_for_gui(event_data, jpeg_binary)
#                     processed_ids.add(frame_id)

#                 # --- [✨ 핵심 수정] ---
#                 # 'patrolling' 상태가 아닐 때만 타임아웃 로직을 적용합니다.
#                 if current_state not in ['patrolling', 'detected']:
#                     timeout = timedelta(seconds=0.1) # idle, moving 상태의 타임아웃
#                     now = datetime.now()
                    
#                     old_image_ids = {fid for fid, (_, _, recv_time) in self.image_buffer.items() if now - recv_time > timeout}
#                     for frame_id in old_image_ids:
#                         if frame_id in processed_ids: continue
#                         jpeg_binary, timestamp, _ = self.image_buffer[frame_id]
#                         self._queue_image_only_for_gui(frame_id, timestamp, jpeg_binary)
#                         processed_ids.add(frame_id)

#                 # 오래된 '이벤트'는 이미지가 없으면 항상 버리도록 정리
#                 event_cleanup_timeout = timedelta(seconds=2.0)
#                 now = datetime.now()
#                 old_event_ids = {fid for fid, (_, recv_time) in self.event_buffer.items() if now - recv_time > event_cleanup_timeout}
#                 processed_ids.update(old_event_ids)

#                 # 처리된 ID들을 버퍼에서 최종 삭제
#                 for frame_id in processed_ids:
#                     self.image_buffer.pop(frame_id, None)
#                     self.event_buffer.pop(frame_id, None)
            
#             time.sleep(0.05)

#     def _gui_send_thread(self):
#         while self.running:
#             if not self.gui_client_socket:
#                 time.sleep(0.5)
#                 continue
#             try:
#                 json_data, image_binary = self.gui_send_queue.get(timeout=1)
#                 json_part = json.dumps(json_data).encode('utf-8')
#                 payload = json_part + b'|' + image_binary + b'\n'
#                 header = struct.pack('>I', len(payload))
#                 self.gui_client_socket.sendall(header + payload)
                
#                 frame_id = json_data.get('frame_id')
#                 state = json_data.get('robot_status')
#                 print(f"[✈️ GUI 전송] 7. DataMerger -> GUI : frame_id {frame_id} (state: {state}), size: {len(header)+len(payload)}")

#             except queue.Empty:
#                 continue
#             except (BrokenPipeError, ConnectionResetError, socket.error) as e:
#                 print(f"[{self.name}] GUI 연결 끊어짐: {e}.")
#                 if self.gui_client_socket: self.gui_client_socket.close()
#                 self.gui_client_socket = None

#     # ==================== 데이터 처리 및 큐잉 헬퍼 메서드 ====================
#     def _queue_merged_for_gui(self, event_data, jpeg_binary):
#         if self.gui_send_queue.full(): return

#         frame_id = event_data.get('frame_id')
#         print(f"[✈️ GUI 전송준비] 6a. DataMerger (Merged) -> GUI : frame_id {frame_id}")

#         image_with_drawings = self._draw_detections(jpeg_binary, event_data.get('detections', []))

#         merged_json = {
#             "frame_id": frame_id,
#             "timestamp": event_data.get('timestamp'),
#             "detections": event_data.get('detections', []),
#             "robot_status": self.robot_status.get('state', 'patrolling'), # 병합은 patrolling에서만 발생
#             "location": self.robot_status.get('current_location', 'BASE')
#         }
#         self.gui_send_queue.put((merged_json, image_with_drawings))

#     def _queue_image_only_for_gui(self, frame_id, timestamp, jpeg_binary):
#         if self.gui_send_queue.full(): return

#         current_state = self.robot_status.get('state', 'idle')
#         print(f"[✈️ GUI 전송준비] 6b. DataMerger (ImageOnly) -> GUI : frame_id {frame_id} (state: {current_state})")

#         image_only_json = {
#             "frame_id": frame_id,
#             "timestamp": timestamp,
#             "detections": [],
#             "robot_status": current_state,
#             "location": self.robot_status.get('current_location', 'BASE')
#         }
#         self.gui_send_queue.put((image_only_json, jpeg_binary))

#     def _draw_detections(self, jpeg_binary, detections):
#         try:
#             np_arr = np.frombuffer(jpeg_binary, np.uint8)
#             frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
#             if frame is None or not detections: return jpeg_binary

#             for det in detections:
#                 box = det.get('box')
#                 if not box or len(box) != 4: continue
#                 x1, y1, x2, y2 = map(int, box)
#                 label = det.get('label', 'unknown')
#                 confidence = det.get('confidence', 0.0)
#                 text = f"{label}: {confidence:.2f}"
#                 cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), 2)
#                 cv2.putText(frame, text, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

#             _, encoded_image = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
#             return encoded_image.tobytes()
#         except Exception as e:
#             print(f"[{self.name}] 이미지 드로잉 오류: {e}")
#             return jpeg_binary

#     # ==================== 종료 메서드 ====================
#     def stop(self):
#         print(f"[{self.name}] 종료 요청 수신.")
#         self.running = False
#         if self.gui_client_socket:
#             self.gui_client_socket.close()
#         if self.gui_server_socket:
#             self.gui_server_socket.close()

# main_server/data_merger.py (디버깅 로그 강화 버전)

import threading
import queue
import socket
import json
import struct
import time
import cv2
import numpy as np
from datetime import datetime, timedelta

class DataMerger(threading.Thread):
    def __init__(self, image_queue, event_queue, gui_listen_addr, robot_status):
        super().__init__()
        self.name = "DataMerger"
        self.running = True

        self.image_queue = image_queue
        self.event_queue = event_queue
        self.gui_send_queue = queue.Queue(maxsize=100)
        self.robot_status = robot_status

        self.image_buffer = {}
        self.event_buffer = {}
        self.buffer_lock = threading.Lock()

        self.gui_listen_addr = gui_listen_addr
        self.gui_server_socket = None
        self.gui_client_socket = None
        print(f"[{self.name}] 초기화 완료. GUI 연결 대기 주소: {self.gui_listen_addr}")

    def run(self):
        print(f"[{self.name}] 스레드 시작.")
        threads = [
            threading.Thread(target=self._gui_accept_thread, daemon=True),
            threading.Thread(target=self._gui_send_thread, daemon=True),
            threading.Thread(target=self._image_receive_thread, daemon=True),
            threading.Thread(target=self._event_receive_thread, daemon=True),
            threading.Thread(target=self._merge_thread, daemon=True)
        ]
        for t in threads: t.start()
        for t in threads: t.join()
        print(f"[{self.name}] 스레드 종료.")

    def _gui_accept_thread(self):
        self.gui_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.gui_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.gui_server_socket.bind(self.gui_listen_addr)
        self.gui_server_socket.listen(1)
        print(f"[{self.name}] GUI 클라이언트 연결 대기 중... ({self.gui_listen_addr})")
        while self.running:
            try:
                conn, addr = self.gui_server_socket.accept()
                print(f"[{self.name}] GUI 클라이언트 연결됨: {addr}")
                if self.gui_client_socket: self.gui_client_socket.close()
                self.gui_client_socket = conn
            except socket.error:
                if not self.running: break

    def _image_receive_thread(self):
        while self.running:
            try:
                frame_id, timestamp, jpeg_binary = self.image_queue.get(timeout=1)
                print(f"[⬅️ 큐 출력] 5a. {self.name} <- ImageManager: Image for frame_id={frame_id}, timestamp={timestamp}")
                with self.buffer_lock:
                    self.image_buffer[frame_id] = (jpeg_binary, timestamp, datetime.now())
            except queue.Empty:
                continue

    def _event_receive_thread(self):
        while self.running:
            try:
                event_data = self.event_queue.get(timeout=1)
                frame_id = event_data['frame_id']
                timestamp = event_data.get('timestamp')
                print(f"[⬅️ 큐 출력] 5b. {self.name} <- EventAnalyzer: Event for frame_id={frame_id}, timestamp={timestamp}")
                with self.buffer_lock:
                    self.event_buffer[frame_id] = (event_data, datetime.now())
            except queue.Empty:
                continue

    def _merge_thread(self):
        while self.running:
            processed_ids = set()
            with self.buffer_lock:
                # 1. 병합 (AI 결과 + 이미지)
                common_ids = self.image_buffer.keys() & self.event_buffer.keys()
                for fid in common_ids:
                    jpeg_binary, _, _ = self.image_buffer[fid]
                    event_data, _ = self.event_buffer[fid]
                    self._queue_merged_for_gui(event_data, jpeg_binary)
                    processed_ids.add(fid)

                # 2. 타임아웃된 이미지 단독 전송 (순찰/탐지 상태 제외)
                current_state = self.robot_status.get('state', 'idle')
                if current_state not in ['patrolling', 'detected']:
                    timeout = timedelta(seconds=0.1)
                    now = datetime.now()
                    old_image_ids = {fid for fid, (_, _, ts) in self.image_buffer.items() if now - ts > timeout}
                    for fid in old_image_ids:
                        if fid in processed_ids: continue
                        jpeg_binary, timestamp, _ = self.image_buffer[fid]
                        self._queue_image_only_for_gui(fid, timestamp, jpeg_binary)
                        processed_ids.add(fid)
                
                # 3. 버퍼 정리
                event_cleanup_timeout = timedelta(seconds=2.0)
                now = datetime.now()
                old_event_ids = {fid for fid, (_, ts) in self.event_buffer.items() if now - ts > event_cleanup_timeout}
                processed_ids.update(old_event_ids)

                for fid in processed_ids:
                    self.image_buffer.pop(fid, None)
                    self.event_buffer.pop(fid, None)
            time.sleep(0.03)

    def _gui_send_thread(self):
        while self.running:
            try:
                if not self.gui_client_socket:
                    time.sleep(0.5)
                    continue
                
                json_data, image_binary = self.gui_send_queue.get(timeout=1)
                
                json_part = json.dumps(json_data).encode('utf-8')
                payload = json_part + b'|' + image_binary
                header = struct.pack('>I', len(payload))
                
                self.gui_client_socket.sendall(header + payload)

                frame_id = json_data.get('frame_id')
                timestamp = json_data.get('timestamp')
                state = json_data.get('robot_status')
                print(f"[✈️ GUI 전송] 7. {self.name} -> GUI: frame_id={frame_id}, timestamp={timestamp}, state={state}, size={len(header)+len(payload)}")

            except queue.Empty:
                continue
            except (BrokenPipeError, ConnectionResetError, socket.error) as e:
                print(f"[{self.name}] GUI 연결 끊어짐: {e}.")
                if self.gui_client_socket: self.gui_client_socket.close()
                self.gui_client_socket = None

    def _queue_merged_for_gui(self, event_data, jpeg_binary):
        if self.gui_send_queue.full(): return

        frame_id = event_data.get('frame_id')
        timestamp = event_data.get('timestamp')
        print("-----------------------------------------------------")
        print(f"[➡️ GUI 전송준비] 6a. {self.name} (Merged): frame_id={frame_id}, timestamp={timestamp}")
        
        detections = event_data.get('detections', [])
        image_with_drawings = self._draw_detections(jpeg_binary, detections)

        merged_json = {
            "frame_id": frame_id,
            "timestamp": timestamp,
            "detections": detections,
            "robot_status": self.robot_status.get('state', 'detected'),
            "location": self.robot_status.get('current_location', 'unknown')
        }
        self.gui_send_queue.put((merged_json, image_with_drawings))

    def _queue_image_only_for_gui(self, frame_id, timestamp, jpeg_binary):
        if self.gui_send_queue.full(): return
        
        current_state = self.robot_status.get('state', 'idle')
        print("-----------------------------------------------------")
        print(f"[➡️ GUI 전송준비] 6b. {self.name} (ImageOnly): frame_id={frame_id}, timestamp={timestamp}, state={current_state}")

        image_only_json = {
            "frame_id": frame_id,
            "timestamp": timestamp,
            "detections": [],
            "robot_status": current_state,
            "location": self.robot_status.get('current_location', 'BASE')
        }
        self.gui_send_queue.put((image_only_json, jpeg_binary))

    def _draw_detections(self, jpeg_binary, detections):
        try:
            np_arr = np.frombuffer(jpeg_binary, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None or not detections: return jpeg_binary

            for det in detections:
                box = det.get('box')
                if not box or len(box) != 4: continue
                x1, y1, x2, y2 = map(int, box)
                label = det.get('label', 'unknown')
                text = f"{label}: {det.get('confidence', 0.0):.2f}"
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                cv2.putText(frame, text, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

            _, encoded_image = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            return encoded_image.tobytes()
        except Exception as e:
            print(f"[{self.name}] 이미지 드로잉 오류: {e}")
            return jpeg_binary

    def stop(self):
        print(f"\n[{self.name}] 종료 요청 수신.")
        self.running = False
        if self.gui_client_socket: self.gui_client_socket.close()
        if self.gui_server_socket: self.gui_server_socket.close()