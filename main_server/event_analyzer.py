# # =====================================================================================
# # FILE: main_server/event_analyzer.py (첫 검출 방지 로직 추가 버전)
# # =====================================================================================
# # 처음에 들어오는 60프레임 정도는 무시하고 그 이후부터 detect수행

# # ... (모듈 임포트 생략) ...
# import socket
# import threading
# import queue
# import json
# import struct
# import time
# from collections import deque, Counter

# class EventAnalyzer(threading.Thread):
#     # 탐지 안정성 분석을 위한 상수
#     WINDOW_SECONDS = 3.0
#     STABILITY_THRESHOLD = 0.8
#     # ✨ [신규] 안정성 분석을 시작하기 위한 최소 프레임 수
#     # - 이 값은 로봇 카메라의 FPS에 따라 조절할 수 있습니다. (예: 10~15 FPS 기준 10프레임은 약 0.7~1초에 해당)
#     MIN_FRAMES_FOR_STABILITY_CHECK = 25

#     # Label to Case 매핑 정의
#     CASE_MAPPING = {
#         'knife': 'danger',
#         'gun': 'danger',
#         'fall_down': 'danger',
#         'cigarette': 'illegality'
#     }

#     # ... (__init__, run, _handle_client, stop 메서드는 이전과 동일) ...
#     def __init__(self, listen_port, output_queue, robot_status):
#         super().__init__()
#         self.name = "EventAnalyzerThread"
#         self.running = True
#         self.output_queue = output_queue
#         self.robot_status = robot_status
#         self.detection_window = deque()
#         self.last_detected_label = None
#         self.is_paused_log_printed = False
#         self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#         self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
#         self.server_socket.bind(('0.0.0.0', listen_port))
#         self.server_socket.listen(5)
#         print(f"[{self.name}] AI 서버의 분석 결과 수신 대기 중... (Port: {listen_port})")
    
#     def run(self):
#         while self.running:
#             try:
#                 client_socket, addr = self.server_socket.accept()
#                 print(f"[{self.name}] AI 서버 연결됨: {addr}")
#                 handler_thread = threading.Thread(target=self._handle_client, args=(client_socket, addr))
#                 handler_thread.daemon = True
#                 handler_thread.start()
#             except socket.error:
#                 if not self.running: break
#         print(f"[{self.name}] 스레드 종료.")

#     def _handle_client(self, conn, addr):
#         try:
#             while self.running:
#                 current_state = self.robot_status.get('state', 'idle')
#                 if current_state in ['idle', 'moving']:
#                     if not self.is_paused_log_printed:
#                         print(f"[ℹ️ 상태 확인] EventAnalyzer: '{current_state}' 상태이므로 분석을 일시 중지합니다.")
#                         self.is_paused_log_printed = True
#                     time.sleep(0.5)
#                     self.detection_window.clear()
#                     self.last_detected_label = None
#                     continue
                
#                 if self.is_paused_log_printed:
#                     print(f"[ℹ️ 상태 확인] EventAnalyzer: '{current_state}' 상태이므로 분석을 재개합니다.")
#                     self.is_paused_log_printed = False
                
#                 header = conn.recv(4)
#                 if not header:
#                     print(f"[{self.name}] AI 서버({addr}) 연결 종료됨 (헤더 없음).")
#                     break
#                 msg_len = struct.unpack('>I', header)[0]
#                 data = b''
#                 while len(data) < msg_len:
#                     packet = conn.recv(msg_len - len(data))
#                     if not packet: break
#                     data += packet
                
#                 try:
#                     trailing_data = conn.recv(1, socket.MSG_DONTWAIT)
#                 except BlockingIOError:
#                     pass
                
#                 result_json_str = data.decode('utf-8')
#                 result_json_for_print = json.loads(result_json_str)
#                 print(f"[✅ TCP 수신] 3. AI_Server -> EventAnalyzer : frame_id {result_json_for_print.get('frame_id')}, dets {len(result_json_for_print.get('detections',[]))}건")
#                 self._process_detection_result(result_json_str)
#         except ConnectionResetError:
#             print(f"[{self.name}] AI 서버({addr})와 연결이 재설정되었습니다.")
#         except Exception as e:
#             print(f"[{self.name}] AI 서버({addr}) 처리 중 오류: {e}")
#         finally:
#             conn.close()

#     def _process_detection_result(self, data_str):
#         try:
#             result_json = json.loads(data_str)
#             now = time.time()
            
#             detections = result_json.get('detections', [])
#             for detection in detections:
#                 label = detection.get('label')
#                 case_value = self.CASE_MAPPING.get(label)
#                 if case_value:
#                     detection['case'] = case_value

#             detected_classes = [d['label'] for d in detections]
#             self.detection_window.append((now, detected_classes))

#             while self.detection_window and now - self.detection_window[0][0] > self.WINDOW_SECONDS:
#                 self.detection_window.popleft()

#             total_frames_in_window = len(self.detection_window)
#             is_stable_detection_found = False

#             # ✨ [핵심 수정] 최소 프레임 수 조건을 만족할 때만 안정성 분석 수행
#             if total_frames_in_window >= self.MIN_FRAMES_FOR_STABILITY_CHECK:
#                 recent_classes = [cls for _, classes in self.detection_window for cls in classes]
#                 counter = Counter(recent_classes)
#                 for label, count in counter.most_common():
#                     if label not in self.CASE_MAPPING:
#                         continue
                        
#                     stability = count / total_frames_in_window
#                     if stability >= self.STABILITY_THRESHOLD:
#                         is_stable_detection_found = True
#                         break # 안정적인 첫 탐지를 발견하면 루프 탈출
                
#                 # 안정성 검사 후 상태 변경 로직 (이전과 동일)
#                 if is_stable_detection_found:
#                     if self.robot_status.get('state') != 'detected' or self.last_detected_label != label:
#                         print(f"\n=======================================================================")
#                         print(f"[🚨 안정적 탐지!] '{label}' 객체가 {self.WINDOW_SECONDS}초 내 {stability:.2%}의 안정도로 탐지됨.")
#                         print(f"[🚦 시스템 상태] EventAnalyzer: 상태 변경: patrolling -> detected")
#                         print(f"=======================================================================\n")
#                         self.robot_status['state'] = 'detected'
#                         self.last_detected_label = label
#                 else: # 안정적인 탐지가 없다면 'patrolling'으로 복귀
#                     if self.robot_status.get('state') == 'detected':
#                         print(f"[ℹ️ 상태 복귀] EventAnalyzer: 안정적 탐지 사라짐. 상태 변경: detected -> patrolling")
#                         self.robot_status['state'] = 'patrolling'
#                         self.last_detected_label = None
#             else: # 최소 프레임 수를 만족하지 못했다면, 'detected' 였다가 사라진 경우를 대비해 상태 복귀 로직만 수행
#                  if self.robot_status.get('state') == 'detected':
#                         print(f"[ℹ️ 상태 복귀] EventAnalyzer: 탐지 객체 사라짐 (윈도우 비워짐). 상태 변경: detected -> patrolling")
#                         self.robot_status['state'] = 'patrolling'
#                         self.last_detected_label = None


#             # 수정된 최종 결과를 DataMerger로 전달
#             self.output_queue.put(result_json)

#         except (json.JSONDecodeError, UnicodeDecodeError) as e:
#             print(f"[{self.name}] JSON 파싱 오류: {e}")
            
#     def stop(self):
#         self.running = False
#         if self.server_socket:
#             self.server_socket.close()
#         print(f"[{self.name}] 종료 요청 수신.")


# main_server/event_analyzer.py (디버깅 로그 강화 버전)

import socket
import threading
import queue
import json
import struct
import time
from collections import deque, Counter

class EventAnalyzer(threading.Thread):
    WINDOW_SECONDS = 3.0
    STABILITY_THRESHOLD = 0.8
    MIN_FRAMES_FOR_STABILITY_CHECK = 25
    CASE_MAPPING = {
        'knife': 'danger',
        'gun': 'danger',
        'fall_down': 'danger',
        'cigarette': 'illegality'
    }

    def __init__(self, listen_port, output_queue, robot_status):
        super().__init__()
        self.name = "EventAnalyzer"
        self.running = True
        self.output_queue = output_queue
        self.robot_status = robot_status
        self.detection_window = deque()
        self.last_detected_label = None
        self.is_paused_log_printed = False
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(('0.0.0.0', listen_port))
        self.server_socket.listen(5)
        print(f"[{self.name}] AI 서버의 분석 결과 수신 대기 중... (Port: {listen_port})")

    def run(self):
        print(f"[{self.name}] 스레드 시작.")
        while self.running:
            try:
                client_socket, addr = self.server_socket.accept()
                print(f"[{self.name}] AI 서버 연결됨: {addr}")
                handler = threading.Thread(target=self._handle_client, args=(client_socket, addr), daemon=True)
                handler.start()
            except socket.error:
                if not self.running: break
        print(f"[{self.name}] 스레드 종료.")

    def _handle_client(self, conn, addr):
        buffer = b''
        while self.running:
            try:
                current_state = self.robot_status.get('state', 'idle')
                if current_state in ['idle', 'moving']:
                    if not self.is_paused_log_printed:
                        print(f"[ℹ️ 상태 확인] {self.name}: '{current_state}' 상태이므로 분석을 일시 중지합니다.")
                        self.is_paused_log_printed = True
                    time.sleep(0.5)
                    self.detection_window.clear()
                    continue

                if self.is_paused_log_printed:
                    print(f"[ℹ️ 상태 확인] {self.name}: '{current_state}' 상태이므로 분석을 재개합니다.")
                    self.is_paused_log_printed = False

                data = conn.recv(4096)
                if not data: break
                buffer += data

                while b'\n' in buffer:
                    payload, buffer = buffer.split(b'\n', 1)
                    header = payload[:4]
                    msg_len = struct.unpack('>I', header)[0]
                    json_data_bytes = payload[4:4+msg_len]
                    
                    self._process_detection_result(json_data_bytes)
                    
            except (ConnectionResetError, struct.error, json.JSONDecodeError) as e:
                print(f"[{self.name}] AI 서버({addr}) 연결 오류: {e}")
                break
        conn.close()
        print(f"[{self.name}] AI 서버({addr}) 연결 종료.")


    def _process_detection_result(self, data_bytes):
        try:
            result_json = json.loads(data_bytes.decode('utf-8'))
            frame_id = result_json.get('frame_id')
            timestamp = result_json.get('timestamp')
            detections = result_json.get('detections', [])
            
            print("-----------------------------------------------------")
            print(f"[✅ TCP 수신] 3. AI_Server -> {self.name}: frame_id={frame_id}, timestamp={timestamp}, dets={len(detections)}건")

            now = time.time()
            for det in detections:
                det['case'] = self.CASE_MAPPING.get(det.get('label'))

            self.detection_window.append((now, [d['label'] for d in detections]))
            while self.detection_window and now - self.detection_window[0][0] > self.WINDOW_SECONDS:
                self.detection_window.popleft()

            self._update_robot_state_based_on_stability()
            
            print(f"[➡️ 큐 입력] 4. {self.name} -> DataMerger: frame_id={frame_id}, timestamp={timestamp}")
            self.output_queue.put(result_json)

        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"[{self.name}] JSON 파싱 오류: {e}")

    def _update_robot_state_based_on_stability(self):
        total_frames = len(self.detection_window)
        if total_frames < self.MIN_FRAMES_FOR_STABILITY_CHECK:
            if self.robot_status.get('state') == 'detected':
                self.robot_status['state'] = 'patrolling'
                self.last_detected_label = None
                print(f"[ℹ️ 상태 복귀] {self.name}: 탐지 객체 사라짐. 상태 변경: detected -> patrolling")
            return

        recent_classes = [cls for _, classes in self.detection_window for cls in classes]
        counter = Counter(recent_classes)
        
        stable_detection_found = False
        for label, count in counter.most_common():
            if label not in self.CASE_MAPPING: continue
            
            stability = count / total_frames
            if stability >= self.STABILITY_THRESHOLD:
                if self.robot_status.get('state') != 'detected' or self.last_detected_label != label:
                    print("\n=====================================================")
                    print(f"[🚨 안정적 탐지!] '{label}' 객체가 {self.WINDOW_SECONDS}초 내 {stability:.2%}의 안정도로 탐지됨.")
                    print(f"[🚦 시스템 상태] {self.name}: 상태 변경: patrolling -> detected")
                    print("=====================================================\n")
                    self.robot_status['state'] = 'detected'
                    self.last_detected_label = label
                stable_detection_found = True
                break
        
        if not stable_detection_found and self.robot_status.get('state') == 'detected':
            print(f"[ℹ️ 상태 복귀] {self.name}: 안정적 탐지 사라짐. 상태 변경: detected -> patrolling")
            self.robot_status['state'] = 'patrolling'
            self.last_detected_label = None
            
    def stop(self):
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        print(f"\n[{self.name}] 종료 요청 수신.")