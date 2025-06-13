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
# [섹션 1] 모듈 임포트
# -------------------------------------------------------------------------------------
import threading
import queue
import socket
import json
import struct
import time

# -------------------------------------------------------------------------------------
# [섹션 2] DataMerger 클래스 정의
# -------------------------------------------------------------------------------------
class DataMerger(threading.Thread):
    """
    이미지 스트림과 이벤트 데이터를 병합하여 GUI로 전송하는 컴포넌트.
    """
    def __init__(self, image_queue: queue.Queue, event_queue: queue.Queue, gui_addr: tuple):
        """
        DataMerger를 초기화합니다.

        :param image_queue: ImageManager로부터 (frame_id, image_binary)를 받는 큐.
        :param event_queue: EventAnalyzer로부터 분석 결과(JSON)를 받는 큐.
        :param gui_addr: 데이터를 전송할 GUI의 (host, port) 튜플.
        """
        super().__init__()
        self.image_queue = image_queue
        self.event_queue = event_queue
        self.gui_addr = gui_addr
        self.running = True
        # 최근 이미지를 임시 저장할 버퍼 (frame_id를 key로 사용)
        self.image_buffer = {}
        self.last_cleanup_time = time.time()
        print("[Data Merger] 초기화 완료.")

    def _send_to_gui(self, data: bytes):
        """
        데이터를 GUI로 전송하는 내부 메소드.
        :param data: 전송할 최종 바이너리 데이터.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.connect(self.gui_addr)
                sock.sendall(data)
        except ConnectionRefusedError:
            # GUI가 켜져 있지 않을 때 반복적인 오류 메시지를 막기 위해 pass 처리도 가능
            # print(f"[Data Merger] GUI({self.gui_addr}) 연결 거부됨. GUI가 실행 중인지 확인하세요.")
            pass
        except Exception as e:
            print(f"[Data Merger] GUI 전송 오류: {e}")

    def _cleanup_buffer(self):
        """
        오래된 데이터를 버퍼에서 주기적으로 삭제하여 메모리 누수를 방지합니다.
        """
        current_time = time.time()
        # 10초마다 클린업 수행
        if current_time - self.last_cleanup_time > 10:
            # 10초 이상 버퍼에 머무른 데이터 삭제
            timeout = 10.0
            expired_keys = [
                k for k, (ts, _) in self.image_buffer.items()
                if current_time - ts > timeout
            ]
            for key in expired_keys:
                del self.image_buffer[key]
                # print(f"[Data Merger] 버퍼에서 만료된 프레임 삭제: {key}")
            self.last_cleanup_time = current_time

    def run(self):
        """
        메인 스레드 로직.
        이미지와 이벤트를 각각의 큐에서 받아 버퍼를 이용해 병합하고,
        주기적으로 버퍼를 정리합니다.
        """
        print("[Data Merger] 시작. 이벤트 병합 및 스트리밍 모드.")
        while self.running:
            self._cleanup_buffer()
            try:
                # 1. 이벤트 큐를 먼저 확인 (non-blocking)
                try:
                    event_data = self.event_queue.get_nowait()
                    frame_id = event_data.get("frame_id")
                    
                    # 해당 frame_id의 이미지가 버퍼에 있는지 확인
                    if frame_id in self.image_buffer:
                        timestamp, image_binary = self.image_buffer.pop(frame_id)
                        
                        # [이벤트 + 이미지] 병합 및 전송
                        response_json = {
                            "frame_id": frame_id,
                            "detections": event_data.get("detections", []),
                            "robot_status": "detected"
                        }
                        json_bytes = json.dumps(response_json).encode('utf-8')
                        message = struct.pack('>I', len(json_bytes)) + json_bytes + image_binary
                        self._send_to_gui(message)
                except queue.Empty:
                    # 처리할 이벤트가 없으면 이미지 큐를 확인
                    pass

                # 2. 이미지 큐 확인 (non-blocking)
                try:
                    frame_id, image_binary = self.image_queue.get_nowait()
                    # 이미지를 버퍼에 저장
                    self.image_buffer[frame_id] = (time.time(), image_binary)
                    
                    # [이미지만] 바로 전송 (스트리밍)
                    response_json = {
                        "frame_id": frame_id,
                        "detections": [],
                        "robot_status": "streaming"
                    }
                    json_bytes = json.dumps(response_json).encode('utf-8')
                    message = struct.pack('>I', len(json_bytes)) + json_bytes + image_binary
                    self._send_to_gui(message)
                except queue.Empty:
                    # 처리할 이미지가 없으면 잠시 대기
                    time.sleep(0.01)

            except Exception as e:
                print(f"[Data Merger] 메인 루프 오류: {e}")
                time.sleep(1)

    def stop(self):
        """
        스레드를 안전하게 종료합니다.
        """
        self.running = False
        print("[Data Merger] 종료 신호 수신. 스레드를 중지합니다.")