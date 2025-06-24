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
        'lying_down': 'emergency',
        'cigarette': 'illegal'
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