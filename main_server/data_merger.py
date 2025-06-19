# =====================================================================================
# FILE: main_server/data_merger.py (개선 완료)
#
# PURPOSE:
#   - ImageManager(영상)와 EventAnalyzer(AI 분석 결과)로부터 데이터를 수신.
#   - 수신된 데이터를 'frame_id' 기준으로 병합.
#   - 병합된 최종 데이터(JSON + 이미지)를 인터페이스 명세서에 맞춰 GUI로 전송.
#   - GUI의 연결 요청을 받는 '서버' 역할 수행.
#
# 주요 로직:
#   1. 버퍼 기반 병합:
#      - 이미지와 이벤트 데이터를 각각의 딕셔너리 버퍼에 'frame_id'를 키로 저장.
#      - 별도의 병합 스레드가 주기적으로 버퍼를 확인하여 frame_id가 일치하는 데이터를 병합.
#      - 이 방식은 데이터 도착 순서나 시간 차이에 관계없이 안정적인 병합을 보장.
#   2. 멀티스레드 아키텍처:
#      - GUI 연결 수락, 이미지 수신, 이벤트 수신, 데이터 병합, GUI 전송을
#        각각의 전담 스레드로 분리하여 성능 및 안정성 극대화.
#   3. ImageOnly 처리:
#      - 'idle', 'moving' 상태이거나, 'patrolling' 상태에서 AI 분석 결과가 없는 이미지도
#        GUI로 전송하여 사용자 경험(UX) 향상.
# =====================================================================================

# -------------------------------------------------------------------------------------
# [섹션 1] 모듈 임포트
# -------------------------------------------------------------------------------------
import threading
import queue
import socket
import json
import struct
import time
import cv2
import numpy as np
from datetime import datetime, timedelta

# -------------------------------------------------------------------------------------
# [섹션 2] DataMerger 클래스 정의
# -------------------------------------------------------------------------------------
class DataMerger(threading.Thread):
    """
    이미지와 AI 분석 결과를 병합하여 GUI로 전송하는 데이터 허브 클래스.
    """
    # ==================== 초기화 메서드 ====================
    def __init__(self, image_queue, event_queue, gui_listen_addr, robot_status):
        super().__init__()
        self.name = "DataMerger"
        self.running = True

        # --- 공유 자원 및 큐 연결 ---
        self.image_queue = image_queue
        self.event_queue = event_queue
        self.gui_send_queue = queue.Queue(maxsize=100) # GUI 전송 버퍼링 큐
        self.robot_status = robot_status

        # --- 데이터 병합을 위한 버퍼 ---
        self.image_buffer = {}  # key: frame_id, value: (jpeg_binary, timestamp, received_time)
        self.event_buffer = {}  # key: frame_id, value: (event_data, received_time)
        self.buffer_lock = threading.Lock() # 버퍼 동시 접근을 막기 위한 Lock

        # --- GUI 연결을 위한 서버 소켓 설정 ---
        self.gui_listen_addr = gui_listen_addr
        self.gui_server_socket = None
        self.gui_client_socket = None

        print(f"[{self.name}] 초기화 완료. GUI 연결 대기 주소: {self.gui_listen_addr}")

    # ==================== 메인 실행 메서드 ====================
    def run(self):
        """클래스의 모든 기능(스레드)을 시작합니다."""
        print(f"[{self.name}] 스레드 시작.")
        # 각 기능을 별도 스레드로 분리하여 병렬 처리
        threads = [
            threading.Thread(target=self._gui_accept_thread, daemon=True, name="GuiAcceptThread"),
            threading.Thread(target=self._gui_send_thread, daemon=True, name="GuiSendThread"),
            threading.Thread(target=self._image_receive_thread, daemon=True, name="ImageRecvThread"),
            threading.Thread(target=self._event_receive_thread, daemon=True, name="EventRecvThread"),
            threading.Thread(target=self._merge_thread, daemon=True, name="MergeThread")
        ]
        for t in threads:
            t.start()

        # 메인 스레드는 실행 상태만 체크하며 대기
        while self.running:
            time.sleep(1)

        print(f"[{self.name}] 메인 스레드 종료.")

    # ==================== 하위 기능 스레드들 ====================
    def _gui_accept_thread(self):
        """(스레드 1) GUI 클라이언트의 연결을 대기하고 수락합니다 (서버 역할)."""
        self.gui_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.gui_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.gui_server_socket.bind(self.gui_listen_addr)
        self.gui_server_socket.listen(1)
        print(f"[{self.name}] GUI 클라이언트 연결 대기 중... ({self.gui_listen_addr})")

        while self.running:
            try:
                conn, addr = self.gui_server_socket.accept()
                print(f"[{self.name}] GUI 클라이언트 연결됨: {addr}")
                if self.gui_client_socket:
                    self.gui_client_socket.close() # 기존 연결은 닫음
                self.gui_client_socket = conn
            except socket.error:
                if not self.running: break
                print(f"[{self.name}] GUI 서버 소켓 오류 발생.")
                time.sleep(1)

    def _image_receive_thread(self):
        """(스레드 2) ImageManager로부터 데이터를 받아 이미지 버퍼에 저장합니다."""
        while self.running:
            try:
                frame_id, timestamp, jpeg_binary = self.image_queue.get(timeout=1)
                print(f"[⬅️ 큐 출력] 5a. DataMerger <- ImageManager : Image for frame_id {frame_id}")
                with self.buffer_lock:
                    self.image_buffer[frame_id] = (jpeg_binary, timestamp, datetime.now())
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[{self.name}] 이미지 수신 스레드 오류: {e}")

    def _event_receive_thread(self):
        """(스레드 3) EventAnalyzer로부터 데이터를 받아 이벤트 버퍼에 저장합니다."""
        while self.running:
            try:
                event_data = self.event_queue.get(timeout=1)
                frame_id = event_data['frame_id']
                print(f"[⬅️ 큐 출력] 5b. DataMerger <- EventAnalyzer : Event for frame_id {frame_id}")
                with self.buffer_lock:
                    self.event_buffer[frame_id] = (event_data, datetime.now())
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[{self.name}] 이벤트 수신 스레드 오류: {e}")

    def _merge_thread(self):
        """(스레드 4) 버퍼를 주기적으로 확인하여 데이터를 병합하고 오래된 데이터를 정리합니다."""
        while self.running:
            processed_ids = set() # 이번 사이클에서 처리(병합 또는 삭제)된 ID 집합
            with self.buffer_lock:
                # ✨ 1. 현재 로봇 상태 가져오기
                current_state = self.robot_status.get('state', 'idle')

                # ✨ 2. 상태에 따라 버퍼 타임아웃 동적 설정
                # 'patrolling' 상태에서는 AI 분석 결과를 기다리기 위해 1초 대기
                # 그 외 상태에서는 즉각적인 반응을 위해 매우 짧게(0.1초) 대기
                timeout_seconds = 1.0 if current_state == 'patrolling' else 0.1
                timeout = timedelta(seconds=timeout_seconds)
                
                # 3. '완전체' 데이터 병합 (기존 로직과 동일)
                common_ids = self.image_buffer.keys() & self.event_buffer.keys()
                for frame_id in common_ids:
                    jpeg_binary, _, _ = self.image_buffer[frame_id]
                    event_data, _ = self.event_buffer[frame_id]
                    self._queue_merged_for_gui(event_data, jpeg_binary)
                    processed_ids.add(frame_id)

                # 4. 타임아웃된 데이터 정리 (✨ 수정된 타임아웃 값 사용)
                now = datetime.now()
                
                # 4-1. 오래된 '이미지' 정리
                old_image_ids = {fid for fid, (_, _, recv_time) in self.image_buffer.items() if now - recv_time > timeout}
                for frame_id in old_image_ids:
                    if frame_id in processed_ids: continue
                    jpeg_binary, timestamp, _ = self.image_buffer[frame_id]
                    self._queue_image_only_for_gui(frame_id, timestamp, jpeg_binary)
                    processed_ids.add(frame_id)

                # 4-2. 오래된 '이벤트' 정리 (AI 결과는 이미지가 없으면 그냥 버림)
                # 'patrolling'이 아닌데도 이벤트가 들어오는 예외적인 경우를 대비해 더 긴 타임아웃(2초)으로 이벤트는 정리
                event_cleanup_timeout = timedelta(seconds=2.0)
                old_event_ids = {fid for fid, (_, recv_time) in self.event_buffer.items() if now - recv_time > event_cleanup_timeout}
                processed_ids.update(old_event_ids)

                # 5. 처리된 ID들을 버퍼에서 최종 삭제 (기존 로직과 동일)
                for frame_id in processed_ids:
                    self.image_buffer.pop(frame_id, None)
                    self.event_buffer.pop(frame_id, None)
            
            time.sleep(0.05) # 50ms 마다 병합/정리 로직 실행

    def _gui_send_thread(self):
        """(스레드 5) GUI 전송 큐에서 데이터를 꺼내 최종 패킷을 만들어 클라이언트로 전송합니다."""
        while self.running:
            if not self.gui_client_socket:
                time.sleep(0.5)
                continue
            try:
                json_data, image_binary_with_drawings = self.gui_send_queue.get(timeout=1)

                # --- 최종 전송 패킷 생성 (인터페이스 명세서 기반) ---
                json_part = json.dumps(json_data).encode('utf-8')
                # 명세서: JSON + b'|' + Binary + b'\n'
                payload = json_part + b'|' + image_binary_with_drawings + b'\n'
                header = struct.pack('>I', len(payload))

                # --- 데이터 전송 ---
                self.gui_client_socket.sendall(header + payload)
                frame_id = json_data.get('frame_id')
                state = json_data.get('robot_status')
                print(f"[✈️ GUI 전송] 7. DataMerger -> GUI : frame_id {frame_id} (state: {state}), size: {len(header)+len(payload)}")

            except queue.Empty:
                continue
            except (BrokenPipeError, ConnectionResetError, socket.error) as e:
                print(f"[{self.name}] GUI 연결 끊어짐: {e}. 재연결 대기.")
                if self.gui_client_socket: self.gui_client_socket.close()
                self.gui_client_socket = None
            except Exception as e:
                print(f"[{self.name}] GUI 전송 중 예상치 못한 오류: {e}")

    # ==================== 데이터 처리 및 큐잉 헬퍼 메서드 ====================
    def _queue_merged_for_gui(self, event_data, jpeg_binary):
        """병합된 데이터를 GUI 전송 큐에 넣습니다."""
        if self.gui_send_queue.full(): return

        frame_id = event_data.get('frame_id')
        print(f"[✈️ GUI 전송준비] 6a. DataMerger (Merged) -> GUI : frame_id {frame_id}")

        # --- 이미지에 탐지 결과 그리기 ---
        image_with_drawings = self._draw_detections(jpeg_binary, event_data.get('detections', []))

        # --- 최종 JSON 구성 (인터페이스 명세서 merged_result 스키마 참고) ---
        merged_json = {
            "frame_id": frame_id,
            "timestamp": event_data.get('timestamp'),
            "detections": event_data.get('detections', []), # AI 분석 결과 포함
            "robot_status": self.robot_status.get('state', 'idle'),
            "location": self.robot_status.get('current_location', 'BASE')
        }
        self.gui_send_queue.put((merged_json, image_with_drawings))

    def _queue_image_only_for_gui(self, frame_id, timestamp, jpeg_binary):
        """이미지만 있는 데이터를 GUI 전송 큐에 넣습니다."""
        if self.gui_send_queue.full(): return

        current_state = self.robot_status.get('state', 'idle')
        print(f"[✈️ GUI 전송준비] 6b. DataMerger (ImageOnly) -> GUI : frame_id {frame_id} (state: {current_state})")

        # --- 기본 JSON 구성 (탐지 결과 없음) ---
        image_only_json = {
            "frame_id": frame_id,
            "timestamp": timestamp,
            "detections": [],
            "robot_status": current_state,
            "location": self.robot_status.get('current_location', 'BASE')
        }
        # ImageOnly 데이터는 별도로 그림을 그릴 필요 없음
        self.gui_send_queue.put((image_only_json, jpeg_binary))

    def _draw_detections(self, jpeg_binary, detections):
        """이미지 위에 탐지된 객체의 바운딩 박스와 라벨을 그립니다."""
        try:
            np_arr = np.frombuffer(jpeg_binary, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None or not detections: return jpeg_binary

            for det in detections:
                box = det.get('box')
                if not box or len(box) != 4: continue
                x1, y1, x2, y2 = map(int, box)
                label = det.get('label', 'unknown')
                confidence = det.get('confidence', 0.0)
                text = f"{label}: {confidence:.2f}"
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                cv2.putText(frame, text, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

            _, encoded_image = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            return encoded_image.tobytes()
        except Exception as e:
            print(f"[{self.name}] 이미지 드로잉 오류: {e}")
            return jpeg_binary # 오류 시 원본 반환

    # ==================== 종료 메서드 ====================
    def stop(self):
        """스레드를 안전하게 종료합니다."""
        print(f"[{self.name}] 종료 요청 수신.")
        self.running = False
        if self.gui_client_socket:
            self.gui_client_socket.close()
        if self.gui_server_socket:
            # self.gui_server_socket.shutdown(socket.SHUT_RDWR) # accept() 블록을 풀기 위해 close()만으로 충분
            self.gui_server_socket.close()