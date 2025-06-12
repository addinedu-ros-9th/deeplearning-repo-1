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

import threading        # 이 클래스를 스레드로 만들고, 데이터 버퍼 동기화를 위한 Lock, 워커 스레드 생성에 필요.
import queue            # SystemManager로부터 받은 공유 큐를 사용하기 위해 필요.
import time             # 버퍼에 저장된 데이터의 유효 시간(timeout)을 관리하기 위해 필요.
import socket           # 병합된 데이터를 GUI로 전송하는 TCP 클라이언트를 만들기 위해 필요.
import json             # 최종 전송할 데이터를 JSON 형식의 문자열로 변환하기 위해 필요.
import struct           # JSON 데이터의 길이를 4바이트 헤더로 패킹하기 위해 필요.

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

        매개변수:
        - image_queue (queue.Queue): ImageManager로부터 (frame_id, image_binary)를 받는 큐.
        - event_queue (queue.Queue): EventAnalyzer로부터 분석 결과(JSON)를 받는 큐.
        - gui_addr (tuple): 데이터를 전송할 GUI의 주소 (host, port).
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

        # 각 임무를 수행할 워커 스레드들을 생성하고 시작 (daemon=True로 메인 스레드 종료 시 함께 종료)
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
                # 1초 타임아웃으로 큐에서 데이터를 가져와 stop()에 반응할 수 있게 함
                frame_id, image_binary = self.image_queue.get(timeout=1)

                with self.lock: # 버퍼 접근 전 Lock 획득
                    if frame_id in self.event_buffer:
                        # 짝을 찾았으면, event_buffer에서 데이터를 꺼내고 GUI로 전송
                        event_data, _ = self.event_buffer.pop(frame_id)
                        print(f"[{self.name}] 이미지 큐에서 frame_id={frame_id} 병합 성공.")
                        self._send_to_gui(event_data, image_binary)
                    else:
                        # 짝이 없으면, image_buffer에 타임스탬프와 함께 저장
                        self.image_buffer[frame_id] = (image_binary, time.time())
            except queue.Empty:
                # 큐가 비어있는 것은 정상적인 상황. 루프를 계속 돌며 stop 신호 확인.
                continue

    def _process_event_queue(self):
        """ [워커 2] event_queue에서 데이터를 꺼내 처리하는 역할. """
        while self.running:
            try:
                event_data = self.event_queue.get(timeout=1)
                frame_id = event_data['frame_id']

                with self.lock: # 버퍼 접근 전 Lock 획득
                    if frame_id in self.image_buffer:
                        # 짝을 찾았으면, image_buffer에서 데이터를 꺼내고 GUI로 전송
                        image_binary, _ = self.image_buffer.pop(frame_id)
                        print(f"[{self.name}] 이벤트 큐에서 frame_id={frame_id} 병합 성공.")
                        self._send_to_gui(event_data, image_binary)
                    else:
                        # 짝이 없으면, event_buffer에 타임스탬프와 함께 저장
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
                    self.image_buffer.pop(fid)
                    print(f"[{self.name}] 버퍼 정리: 오래된 이미지 데이터(frame_id={fid}) 삭제.")
                
                for fid in expired_events:
                    self.event_buffer.pop(fid)
                    print(f"[{self.name}] 버퍼 정리: 오래된 이벤트 데이터(frame_id={fid}) 삭제.")

    def _send_to_gui(self, event_data, image_binary):
        """ 조합된 데이터를 최종 패키징하여 GUI에 TCP로 전송. """
        try:
            # GUI에 연결할 TCP 클라이언트 소켓을 매번 새로 생성하여 연결
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.connect(self.gui_addr)

                # 전송할 JSON 데이터에 'robot_status'와 같은 추가 정보 삽입
                event_data['robot_status'] = 'detected'

                # [핵심] 전송 패킷 생성: [JSON 길이(4B)] + [JSON 데이터] + [이미지 바이너리]
                # Interface Specification Index 6을 구현한 부분
                json_bytes = json.dumps(event_data).encode('utf-8')
                len_prefix = struct.pack('!I', len(json_bytes))
                final_packet = len_prefix + json_bytes + image_binary
                
                sock.sendall(final_packet)
                print(f"[{self.name}] GUI로 데이터 전송 완료 (frame_id={event_data['frame_id']})")
        
        except ConnectionRefusedError:
            print(f"[{self.name}] GUI 연결 실패 ({self.gui_addr}). GUI가 실행 중인지 확인하세요.")
        except Exception as e:
            print(f"[{self.name}] GUI 전송 중 오류 발생: {e}")
        