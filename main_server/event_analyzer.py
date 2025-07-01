# main_server/event_analyzer.py (워밍업 기능 추가 버전)

import socket
import threading
import queue
import json
import struct
import time
from collections import deque, Counter

class EventAnalyzer(threading.Thread):
    # [추가] Patrolling 상태 진입 후 안정화를 위한 워밍업 시간 (초)
    # 사용자가 제안한 60프레임을 20fps 기준으로 3초로 설정
    PATROL_WARM_UP_SECONDS = 1.0
    
    WINDOW_SECONDS = 2.0
    STABILITY_THRESHOLD = 0.4
    MIN_FRAMES_FOR_STABILITY_CHECK = 40
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

        # [추가] 상태 변경 감지를 위한 변수들
        self.previous_state = self.robot_status.get('state', 'idle')
        self.patrol_mode_start_time = None

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

                # [추가] 'patrolling' 상태로 처음 진입했는지 확인하는 로직
                if current_state == 'patrolling' and self.previous_state != 'patrolling':
                    print(f"\n[🚦 시스템 상태] {self.name}: Patrolling 상태 진입. {self.PATROL_WARM_UP_SECONDS}초의 워밍업을 시작합니다.")
                    self.patrol_mode_start_time = time.time()
                    self.detection_window.clear() # 이전 상태의 탐지 기록은 초기화

                # 현재 상태를 이전 상태로 기록
                self.previous_state = current_state

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
                    # (기존 코드와 동일)
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
            # (기존 코드와 동일)
            result_json = json.loads(data_bytes.decode('utf-8'))
            frame_id = result_json.get('frame_id')
            timestamp = result_json.get('timestamp')
            detections = result_json.get('detections', [])
            
            print("-----------------------------------------------------")
            print(f"[✅ TCP 수신] 3. AI_Server -> {self.name}: frame_id={frame_id}, timestamp={timestamp}, dets={len(detections)}건")

            now = time.time()
            for det in detections:
                det['case'] = self.CASE_MAPPING.get(det.get('label'))

            self.detection_window.append((now, [d['label'] for d in detections if d.get('label')]))
            while self.detection_window and now - self.detection_window[0][0] > self.WINDOW_SECONDS:
                self.detection_window.popleft()

            self._update_robot_state_based_on_stability()
            
            print(f"[➡️ 큐 입력] 4. {self.name} -> DataMerger: frame_id={frame_id}, timestamp={timestamp}")
            self.output_queue.put(result_json)

        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"[{self.name}] JSON 파싱 오류: {e}")

    def _update_robot_state_based_on_stability(self):
        if self.robot_status.get('state') == 'detected':
            return

        # [수정] 워밍업 시간 체크 로직 추가
        if self.patrol_mode_start_time is None or \
           time.time() - self.patrol_mode_start_time < self.PATROL_WARM_UP_SECONDS:
            # 워밍업 시간이 아직 지나지 않았으면, 안정성 분석을 수행하지 않고 종료
            return

        total_frames = len(self.detection_window)
        if total_frames < self.MIN_FRAMES_FOR_STABILITY_CHECK:
            return

        recent_classes = [cls for _, classes in self.detection_window for cls in classes]
        if not recent_classes: return

        counter = Counter(recent_classes)
        
        for label, count in counter.most_common():
            if label not in self.CASE_MAPPING: continue
            
            stability = count / total_frames
            if stability >= self.STABILITY_THRESHOLD:
                print("\n=====================================================")
                print(f"[🚨 안정적 탐지!] '{label}' 객체가 {self.WINDOW_SECONDS}초 내 {stability:.2%}의 안정도로 탐지됨.")
                print(f"[🚦 시스템 상태] {self.name}: 상태 변경: patrolling -> detected")
                print("=====================================================\n")
                self.robot_status['state'] = 'detected'
                self.last_detected_label = label
                break
            
    def stop(self):
        # (기존 코드와 동일)
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        print(f"\n[{self.name}] 종료 요청 수신.")