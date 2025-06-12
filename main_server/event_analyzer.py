# =====================================================================================
# FILE: main_server/event_analyzer.py
#
# PURPOSE:
#   - AI 서버(detector_manager)로부터 TCP로 전송된 영상 분석 결과를 수신.
#   - 수신한 데이터는 JSON 형식이며, 객체의 종류, 신뢰도, 좌표 등의 정보 포함.
#   - 수신한 분석 결과를 내부의 Merger가 사용할 수 있도록 공유 큐에 저장.
#   - SystemManager에 의해 스레드로 생성되고 관리됨.
# =====================================================================================

import socket
import threading
import queue
import json
import struct

class EventAnalyzer(threading.Thread):
    """
    ai_server(detector_manager)로부터 TCP로 객체 탐지 결과를 수신하여,
    이벤트를 분석하고, 분석된 결과를 공유 큐(Queue)를 통해 DataMerger로 전송하는 클래스.
    threading.Thread를 상속받아 SystemManager에 의해 관리됨.
    """
    def __init__(self, listen_port, output_queue):
        super().__init__()
        # 1. 수신부 (ai_server로부터 데이터를 받음)
        self.listen_port = listen_port
        self.server_socket = None

        # 2. 송신부 (분석 결과를 DataMerger로 보내기 위한 공유 큐)
        self.output_queue = output_queue
        
        # 3. 이벤트 분석 규칙 정의 (Interface Specification 기반)
        self.EVENT_RULES = {
            "knife": {"case": "danger", "actions": ["IGNORE", "POLICE_REPORT"]},
            "gun": {"case": "danger", "actions": ["IGNORE", "POLICE_REPORT"]},
            "person_fall": {"case": "emergency", "actions": ["IGNORE", "VOICE_CALL", "HORN", "FIRE_REPORT"]},
            "smoke": {"case": "warning", "actions": ["IGNORE", "WARN_SIGNAL", "POLICE_REPORT"]},
            "cigarette": {"case": "warning", "actions": ["IGNORE", "WARN_SIGNAL"]}
        }

        self.running = False
        self.name = "EventAnalyzerThread"

    def _analyze_and_queue(self, data):
        """
        탐지된 객체를 분석하고, 유의미한 이벤트가 있을 경우 공유 큐에 추가
        """
        is_event_detected = False
        if "detections" in data and data["detections"]:
            for det in data["detections"]:
                label = det.get("label")
                rule = self.EVENT_RULES.get(label)
                if rule:
                    is_event_detected = True
                    det["case"] = rule["case"]
                    det["actions"] = rule["actions"]
        
        # 유의미한 이벤트가 하나라도 탐지되었을 경우에만 큐에 추가
        if is_event_detected:
            print(f"[{self.name}] frame_id={data['frame_id']} 이벤트 탐지. Merger로 전송합니다.")
            self.output_queue.put(data)
        else:
            # 유의미한 이벤트가 없으면 아무 작업도 하지 않음
            pass

    def _handle_detector_connection(self, conn, addr):
        """
        detector_manager로부터 들어온 연결을 처리
        """
        print(f"[{self.name}] ai_server({addr})와 연결됨.")
        try:
            while self.running:
                # 1. 4바이트 길이 접두사(length-prefix) 수신
                len_prefix = conn.recv(4)
                if not len_prefix:
                    break
                
                msg_len = struct.unpack('!I', len_prefix)[0]

                # 2. 실제 JSON 데이터 수신
                body_data = b''
                while len(body_data) < msg_len:
                    packet = conn.recv(msg_len - len(body_data))
                    if not packet:
                        raise ConnectionError("수신 중 연결이 끊어졌습니다.")
                    body_data += packet
                
                request = json.loads(body_data.decode('utf-8'))
                
                # 3. 수신된 데이터 분석 및 큐에 추가
                self._analyze_and_queue(request)

        except ConnectionResetError:
            print(f"[{self.name}] ai_server({addr})와 연결이 초기화되었습니다.")
        except Exception as e:
            if self.running:
                print(f"[{self.name}] 연결 처리 중 오류 발생: {e}")
        finally:
            print(f"[{self.name}] ai_server({addr})와 연결 종료.")
            conn.close()

    def run(self):
        """
        .start() 메서드가 호출되면 스레드에서 실제 실행되는 메인 작업 루프.
        ai_server로부터의 연결을 수신 대기.
        """
        self.running = True
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(('0.0.0.0', self.listen_port))
        self.server_socket.listen(1)
        print(f"[{self.name}] ai_server의 분석 결과를 기다리는 중... (TCP Port: {self.listen_port})")

        while self.running:
            try:
                conn, addr = self.server_socket.accept()
                # 현재는 ai_server가 하나이므로, 단일 연결만 처리
                self._handle_detector_connection(conn, addr)
            except socket.error:
                # stop() 메서드에서 소켓이 닫힐 때 발생하는 에러를 처리
                if not self.running:
                    break
        
        print(f"[{self.name}] 스레드 루프를 종료합니다.")

    def stop(self):
        """
        스레드를 안전하게 중지
        """
        print(f"[{self.name}] 종료 요청을 받았습니다.")
        self.running = False
        if self.server_socket:
            self.server_socket.close() # accept() 대기를 중단시키기 위해 소켓을 닫음