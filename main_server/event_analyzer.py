# =====================================================================================
# FILE: main_server/event_analyzer.py
#
# PURPOSE:
#   - AI 서버(Detection Manager)로부터 TCP를 통해 객체 탐지 분석 결과를 수신.
#   - 수신된 결과 중에서 'person', 'knife', 'gun'과 같이 의미 있는 이벤트만 필터링.
#   - 필터링된 유의미한 이벤트 데이터를 DataMerger가 사용할 수 있도록 'event_result_queue'에 전송.
#   - SystemManager로부터 공유받은 robot_status 값을 확인하여, 로봇이 'idle' 또는 'moving'
#     상태일 때는 분석 결과 수신 및 처리를 일시 중지하는 '조건부 실행자' 역할을 수행.
#
# 주요 로직:
#   1. TCP 서버 실행 (run):
#      - AI 서버의 연결 요청을 지속적으로 수신 대기.
#      - 새로운 클라이언트(AI 서버)가 연결될 때마다 전용 처리 스레드(_handle_client)를 생성.
#   2. 데이터 수신 및 처리 (_handle_client):
#      - 루프 시작 시, 로봇의 상태(robot_status['state'])를 먼저 확인.
#      - 'idle' 또는 'moving' 상태이면, 처리를 건너뛰고 잠시 대기하여 CPU 사용을 방지.
#      - 'patrolling' 상태일 때만, 4바이트 길이 헤더가 포함된 TCP 스트림을 수신하여 JSON 데이터를 파싱.
#      - 파싱된 데이터를 _process_detection_result 메서드로 전달.
#   3. 이벤트 필터링 (_process_detection_result):
#      - JSON 데이터 안의 'detections' 배열을 검사.
#      - 미리 정의된 주요 객체('person', 'knife', 'gun')가 포함된 경우에만, 해당 데이터를
#        'event_result_queue'에 삽입.
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

# -------------------------------------------------------------------------------------
# [섹션 2] EventAnalyzer 클래스 정의
# -------------------------------------------------------------------------------------
class EventAnalyzer(threading.Thread):
    def __init__(self, listen_port, output_queue, robot_status):
        super().__init__()
        self.name = "EventAnalyzerThread"
        self.running = True
        self.output_queue = output_queue
        self.robot_status = robot_status
        self.is_paused_log_printed = False
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(('0.0.0.0', listen_port))
        self.server_socket.listen(5)
        print(f"[{self.name}] AI 서버의 분석 결과 수신 대기 중... (Port: {listen_port})")

    def run(self):
        while self.running:
            try:
                client_socket, addr = self.server_socket.accept()
                print(f"[{self.name}] AI 서버 연결됨: {addr}")
                handler_thread = threading.Thread(target=self._handle_client, args=(client_socket, addr))
                handler_thread.daemon = True
                handler_thread.start()
            except socket.error:
                if not self.running: break
        print(f"[{self.name}] 스레드 종료.")

    def _handle_client(self, conn, addr):
        try:
            while self.running:
                current_state = self.robot_status.get('state', 'idle')
                if current_state in ['idle', 'moving']:
                    if not self.is_paused_log_printed:
                        print(f"[ℹ️ 상태 확인] EventAnalyzer: '{current_state}' 상태이므로 분석을 일시 중지합니다.")
                        self.is_paused_log_printed = True
                    time.sleep(0.5)
                    continue
                
                if self.is_paused_log_printed:
                    print(f"[ℹ️ 상태 확인] EventAnalyzer: '{current_state}' 상태이므로 분석을 재개합니다.")
                    self.is_paused_log_printed = False
                
                header = conn.recv(4)
                if not header:
                    print(f"[{self.name}] AI 서버({addr}) 연결 종료됨 (헤더 없음).")
                    break
                msg_len = struct.unpack('>I', header)[0]
                data = b''
                while len(data) < msg_len:
                    packet = conn.recv(msg_len - len(data))
                    if not packet: break
                    data += packet
                
                result_json_str = data.decode('utf-8')
                result_json_for_print = json.loads(result_json_str)
                print(f"[✅ TCP 수신] 3. AI_Server -> EventAnalyzer : frame_id {result_json_for_print.get('frame_id')}, dets {len(result_json_for_print.get('detections',[]))}건")
                self._process_detection_result(result_json_str)
        except ConnectionResetError:
            print(f"[{self.name}] AI 서버({addr})와 연결이 재설정되었습니다.")
        except Exception as e:
            print(f"[{self.name}] AI 서버({addr}) 처리 중 오류: {e}")
        finally:
            conn.close()

    def _process_detection_result(self, data_str):
        try:
            result_json = json.loads(data_str)
            detections = result_json.get('detections', [])
            significant_labels = {'person', 'knife', 'gun'}
            is_significant = any(d.get('label') in significant_labels for d in detections)
            if is_significant:
                print(f"[➡️ 큐 입력] 4. EventAnalyzer -> DataMerger : (patrolling) frame_id {result_json.get('frame_id')}")
                self.output_queue.put(result_json)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"[{self.name}] JSON 파싱 오류: {e}")

    def stop(self):
        self.running = False
        self.server_socket.close()
        print(f"[{self.name}] 종료 요청 수신.")