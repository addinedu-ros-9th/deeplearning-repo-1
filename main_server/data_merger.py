# =====================================================================================
# FILE: main_server/data_merger.py
#
# PURPOSE:
#   - ImageManager로부터 원본 이미지 데이터를 큐(Queue)를 통해 수신.
#   - EventAnalyzer로부터 영상 분석 결과(JSON)를 큐(Queue)를 통해 수신.
#   - 두 데이터 스트림을 'frame_id'를 기준으로 동기화하고 하나로 병합.
#   - 병합된 최종 데이터(JSON + 이미지)를 TCP 통신을 통해 GUI로 전송.
#   - SystemManager에 의해 스레드로 생성되고 관리됨.
# =====================================================================================

# -------------------------------------------------------------------------------------
# [섹션 1] 모듈 임포트 (Module Imports)
# -------------------------------------------------------------------------------------

import threading
import queue
import time
import socket
import json
import struct

# -------------------------------------------------------------------------------------
# [섹션 2] DataMerger 클래스 정의
# -------------------------------------------------------------------------------------

class DataMerger(threading.Thread):
    """
    이미지 데이터와 이벤트 데이터를 병합하여 GUI로 전송하는 클래스.
    두 개의 입력 큐를 감시하고, 데이터의 frame_id를 기준으로 조합함.
    """
    # 버퍼에 데이터가 머무를 수 있는 최대 시간 (초). 이 시간을 넘으면 데이터가 삭제됨.
    BUFFER_TIMEOUT = 5

    def __init__(self, image_queue, event_queue, gui_addr):
        """
        DataMerger 초기화 메서드.

        :param image_queue: ImageManager로부터 (frame_id, image_binary)를 받는 큐.
        :param event_queue: EventAnalyzer로부터 분석 결과(JSON)를 받는 큐.
        :param gui_addr: 데이터를 전송할 GUI의 주소 (host, port).
        """
        super().__init__()
        self.name = "DataMergerThread"

        # SystemManager로부터 받은 설정값들을 인스턴스 변수로 저장
        self.image_queue = image_queue
        self.event_queue = event_queue
        self.gui_addr = gui_addr

        # 데이터 동기화를 위한 임시 저장소(버퍼)와 Lock 생성
        self.image_buffer = {}  # 형식: {frame_id: (image_binary, timestamp)}
        self.event_buffer = {}  # 형식: {frame_id: (event_data, timestamp)}
        self.lock = threading.Lock() # 버퍼 동시 접근을 막기 위한 잠금 장치

        # 스레드의 메인 루프를 제어하기 위한 플래그 변수
        self.running = False

    def run(self):
        """
        .start() 메서드가 호출되면 스레드에서 실제 실행되는 메인 작업 루프.
        각 큐를 처리하는 워커 스레드를 생성하고 관리.
        """
        self.running = True
        print(f"[{self.name}] 스레드 시작.")

        # 각 임무를 수행할 워커 스레드들을 생성하고 시작
        image_worker = threading.Thread(target=self._process_image_queue, daemon=True)
        event_worker = threading.Thread(target=self._process_event_queue, daemon=True)
        cleaner_worker = threading.Thread(target=self._cleanup_buffers, daemon=True)
        
        image_worker.start()
        event_worker.start()
        cleaner_worker.start()

        # stop() 메서드가 호출될 때까지 메인 스레드는 대기
        while self.running:
            time.sleep(1)

        print(f"[{self.name}] 스레드 종료 중...")

    def stop(self):
        """ SystemManager가 호출하여 스레드를 안전하게 종료. """
        print(f"[{self.name}] 종료 요청 수신.")
        self.running = False

    def _process_image_queue(self):
        """ [워커 1] image_queue에서 데이터를 꺼내 처리하는 역할. """
        while self.running:
            try:
                frame_id, image_binary = self.image_queue.get(timeout=1)

                # [수정된 핵심 로직]
                # 1. '스트리밍'을 위해 이미지를 즉시 GUI로 전송합니다.
                #    탐지 결과가 없는 기본 상태의 패킷을 만듭니다.
                streaming_event_data = {
                    'frame_id': frame_id,
                    'detections': [],
                    'robot_status': 'streaming'
                }
                self._send_to_gui(streaming_event_data, image_binary)

                # 2. 나중에 도착할 이벤트를 대비하여 이미지를 버퍼에도 저장합니다.
                with self.lock:
                    # 만약 해당 이벤트가 이미지보다 먼저 도착해서 버퍼에 있다면,
                    # 병합된 'detected' 데이터를 GUI에 한 번 더 보내 상태를 업데이트합니다.
                    if frame_id in self.event_buffer:
                        event_data, _ = self.event_buffer.pop(frame_id)
                        print(f"[{self.name}] 빠른 이벤트와 병합 (frame_id={frame_id}). GUI 상태 업데이트.")
                        self._send_to_gui(event_data, image_binary)
                    else:
                        # 짝이 되는 이벤트가 아직 없으면, 이미지를 버퍼에 저장합니다.
                        self.image_buffer[frame_id] = (image_binary, time.time())
            
            except queue.Empty:
                continue

    def _process_event_queue(self):
        """ [워커 2] event_queue에서 데이터를 꺼내 처리하는 역할. """
        while self.running:
            try:
                event_data = self.event_queue.get(timeout=1)
                frame_id = event_data['frame_id']

                with self.lock:
                    # 짝이 되는 이미지가 버퍼에 있는지 확인합니다.
                    if frame_id in self.image_buffer:
                        # 짝을 찾았으면, 이미지 버퍼에서 데이터를 꺼내고 병합하여 GUI로 전송합니다.
                        image_binary, _ = self.image_buffer.pop(frame_id)
                        print(f"[{self.name}] 이벤트 큐에서 병합 성공 (frame_id={frame_id}).")
                        self._send_to_gui(event_data, image_binary)
                    else:
                        # 짝이 없으면, 이벤트 버퍼에 타임스탬프와 함께 저장합니다.
                        self.event_buffer[frame_id] = (event_data, time.time())
            except queue.Empty:
                continue

    def _cleanup_buffers(self):
        """ [워커 3] 주기적으로 버퍼를 확인하여 오래된 데이터를 삭제. (메모리 누수 방지) """
        while self.running:
            time.sleep(self.BUFFER_TIMEOUT)
            
            with self.lock:
                current_time = time.time()
                # 타임아웃이 지난 데이터들의 키를 리스트로 만듦
                expired_images = [fid for fid, (_, ts) in self.image_buffer.items() if current_time - ts > self.BUFFER_TIMEOUT]
                expired_events = [fid for fid, (_, ts) in self.event_buffer.items() if current_time - ts > self.BUFFER_TIMEOUT]

                # 리스트를 순회하며 버퍼에서 해당 키를 삭제
                for fid in expired_images:
                    self.image_buffer.pop(fid, None)
                    print(f"[{self.name}] 버퍼 정리: 오래된 이미지 데이터(frame_id={fid}) 삭제.")
                
                for fid in expired_events:
                    self.event_buffer.pop(fid, None)
                    print(f"[{self.name}] 버퍼 정리: 오래된 이벤트 데이터(frame_id={fid}) 삭제.")

    def _send_to_gui(self, event_data, image_binary):
        """ 조합된 데이터를 최종 패키징하여 GUI에 TCP로 전송. """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.connect(self.gui_addr)

                # Interface Specification Index 6 형식에 따라 패킷 생성
                # [JSON 길이(4B)] + [JSON 데이터] + [이미지 바이너리]
                json_bytes = json.dumps(event_data).encode('utf-8')
                len_prefix = struct.pack('!I', len(json_bytes))
                final_packet = len_prefix + json_bytes + image_binary
                
                sock.sendall(final_packet)
        
        except ConnectionRefusedError:
            # GUI가 꺼져있을 때 콘솔이 어지러워지는 것을 방지
            pass
        except Exception as e:
            print(f"[{self.name}] GUI 전송 중 오류 발생: {e}")