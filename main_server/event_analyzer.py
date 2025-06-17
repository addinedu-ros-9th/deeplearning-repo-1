# =====================================================================================
# FILE: main_server/event_analyzer.py
#
# PURPOSE:
#   - AI 서버(detector_manager)로부터 TCP로 전송된 영상 분석 결과를 수신.
#   - 수신한 데이터는 JSON 형식이며, 객체의 종류, 신뢰도, 좌표 등의 정보 포함.
#   - 수신한 분석 결과를 내부의 Merger가 사용할 수 있도록 공유 큐에 저장.
#   - SystemManager에 의해 스레드로 생성되고 관리됨.
#
# 주요 로직:
#   1. EventAnalyzer (메인 스레드):
#      - TCP 서버 소켓을 열고 AI 서버(detector_manager)의 연결을 대기하고 수락.
#      - 연결이 수립되면 'handle_detector_connection' 메서드를 호출하여 AI 서버의 데이터를 지속적으로 처리.
#   2. _handle_detector_connection (워커 역할):
#      - AI 서버로부터 'length-prefix'와 실제 JSON 분석 결과 데이터를 수신.
#      - 수신된 JSON 데이터에서 후행 개행 문자(b'\n')를 정확히 처리하여 다음 메시지 수신 준비.
#      - 수신된 데이터를 '_analyze_and_queue' 메서드로 전달하여 분석 및 큐잉.
#   3. _analyze_and_queue (분석 및 큐잉):
#      - 수신된 분석 결과(detections)를 미리 정의된 'EVENT_RULES'와 비교하여 유의미한 이벤트(danger, emergency, warning)인지 판단.
#      - 유의미한 이벤트가 탐지되면, 해당 이벤트 정보와 함께 데이터를 'output_queue'에 추가하여 DataMerger로 전송.
# =====================================================================================

import socket # 소켓 통신을 위한 모듈 임포트
import threading # 스레드 기능을 사용하기 위한 모듈 임포트
import queue # 큐(Queue) 자료구조를 사용하기 위한 모듈 임포트
import json # JSON 데이터 처리를 위한 모듈 임포트
import struct # 바이트와 파이썬 값 간의 변환을 위한 모듈 임포트

class EventAnalyzer(threading.Thread): # EventAnalyzer 클래스는 threading.Thread를 상속받아 스레드로 동작
    """
    ai_server(detector_manager)로부터 TCP로 객체 탐지 결과를 수신하여,
    이벤트를 분석하고, 분석된 결과를 공유 큐(Queue)를 통해 DataMerger로 전송하는 클래스.
    threading.Thread를 상속받아 SystemManager에 의해 관리됨.
    """
    def __init__(self, listen_port, output_queue): # 생성자 정의
        super().__init__() # 부모 클래스(threading.Thread)의 생성자 호출
        # 1. 수신부 (ai_server로부터 데이터를 받음)
        self.listen_port = listen_port # AI 서버로부터 데이터를 수신할 포트 번호
        self.server_socket = None # 서버 소켓 객체 초기화

        # 2. 송신부 (분석 결과를 DataMerger로 보내기 위한 공유 큐)
        self.output_queue = output_queue # 분석 결과를 DataMerger로 전달할 공유 큐
        
        # 3. 이벤트 분석 규칙 정의 (Interface Specification 기반)
        self.EVENT_RULES = { # 객체 탐지 라벨에 따른 이벤트 규칙 정의
            "knife": {"case": "danger", "actions": ["IGNORE", "POLICE_REPORT"]}, # 칼 탐지 시 위험 케이스, 행동 지침
            "gun": {"case": "danger", "actions": ["IGNORE", "POLICE_REPORT"]},   # 총 탐지 시 위험 케이스, 행동 지침
            "person_fall": {"case": "emergency", "actions": ["IGNORE", "VOICE_CALL", "HORN", "FIRE_REPORT"]}, # 낙상 탐지 시 비상 케이스, 행동 지침
            "smoke": {"case": "warning", "actions": ["IGNORE", "WARN_SIGNAL", "POLICE_REPORT"]}, # 연기 탐지 시 경고 케이스, 행동 지침
            "cigarette": {"case": "warning", "actions": ["IGNORE", "WARN_SIGNAL"]} # 담배 탐지 시 경고 케이스, 행동 지침
        }

        self.running = False # 스레드 실행 상태를 나타내는 플래그 초기화
        self.name = "EventAnalyzerThread" # 스레드 이름 설정

    def _analyze_and_queue(self, data): # 탐지된 객체를 분석하고 유의미한 이벤트일 경우 큐에 추가하는 메서드
        """
        탐지된 객체를 분석하고, 유의미한 이벤트가 있을 경우 공유 큐에 추가
        """
        is_event_detected = False # 유의미한 이벤트 탐지 여부 플래그 초기화
        if "detections" in data and data["detections"]: # 'detections' 키가 있고 비어있지 않다면
            for det in data["detections"]: # 각 탐지된 객체에 대해 반복
                label = det.get("label") # 객체의 라벨(예: "knife", "smoke") 가져오기
                rule = self.EVENT_RULES.get(label) # 해당 라벨에 대한 이벤트 규칙 가져오기
                if rule: # 규칙이 존재한다면 (유의미한 이벤트라면)
                    is_event_detected = True # 이벤트 탐지 플래그 True로 설정
                    det["case"] = rule["case"] # 탐지된 객체에 이벤트 케이스 추가
                    det["actions"] = rule["actions"] # 탐지된 객체에 행동 지침 추가
        
        # 유의미한 이벤트가 하나라도 탐지되었을 경우에만 큐에 추가
        if is_event_detected: # 유의미한 이벤트가 탐지되었다면
            print(f"[➡️ 큐 입력] 4b. EventAnalyzer -> DataMerger: frame_id={data.get('frame_id')}, timestamp {data.get('timestamp')} 이벤트 데이터 추가") # 큐 추가 메시지 출력
            self.output_queue.put(data) # 처리된 데이터를 output_queue에 추가
        else:
            # 유의미한 이벤트가 없으면 아무 작업도 하지 않음
            pass # 아무 작업도 수행하지 않음

    def _handle_detector_connection(self, conn, addr): # detector_manager로부터의 연결을 처리하는 메서드
        """
        detector_manager로부터 들어온 연결을 처리
        """
        print(f"[{self.name}] ai_server({addr})와 연결됨.") # AI 서버 연결 메시지 출력
        try:
            while self.running: # 스레드가 실행 중인 동안 반복
                # 1. 4바이트 길이 접두사(length-prefix) 수신
                len_prefix = conn.recv(4) # 4바이트 길이의 메시지 헤더 수신
                if not len_prefix: # 헤더가 없으면 (연결 종료)
                    break # 루프 종료
                
                msg_len = struct.unpack('!I', len_prefix)[0] # 수신된 4바이트 헤더를 빅 엔디안 정수(메시지 길이)로 변환

                # 2. 실제 JSON 데이터 수신
                body_data = b'' # 메시지 본문 데이터를 저장할 변수 초기화
                while len(body_data) < msg_len: # 수신된 데이터 길이가 메시지 길이보다 작으면 반복
                    packet = conn.recv(msg_len - len(body_data)) # 남은 데이터만큼 패킷 수신
                    if not packet: # 패킷이 없으면 (연결 끊김)
                        raise ConnectionError("수신 중 연결이 끊어졌습니다.") # 연결 오류 발생
                    body_data += packet # 수신된 패킷을 본문 데이터에 추가
                
                # ========================= ✨ 수정된 부분 ✨ =========================
                # 3. Interface Specification.md (Index 5)에 명시된 후행 개행 문자(b'\n')를 읽어서 소비합니다.
                #    이것을 하지 않으면 다음 메시지를 읽을 때 이 개행 문자가 읽혀 오류가 발생합니다.
                trailing_newline = conn.recv(1) # 후행 개행 문자 1바이트 수신 및 소비
                # ===================================================================
                
                # 4. 수신된 데이터 분석 및 큐에 추가
                request = json.loads(body_data.decode('utf-8')) # 수신된 본문 데이터를 UTF-8로 디코딩 후 JSON 파싱
                # 수신 로그의 사이즈 계산을 정확하게 하기 위해 +1 (개행문자)
                total_size = len(len_prefix) + len(body_data) + len(trailing_newline) # 전체 수신 데이터 크기 계산
                print(f"[✅ 수신] 3. AI_Server -> EventAnalyzer: frame_id {request.get('frame_id')}, timestamp {request.get('timestamp')}, size {total_size} bytes, detections: {request.get('detections')}") # 수신 로그 출력

                
                # 5. 수신된 데이터 분석 및 큐에 추가
                self._analyze_and_queue(request) # 수신된 데이터를 분석 및 큐에 추가하는 메서드 호출

        except ConnectionResetError: # 클라이언트(AI 서버)가 연결을 강제로 끊었을 때
            print(f"[{self.name}] ai_server({addr})와 연결이 초기화되었습니다.") # 연결 초기화 메시지 출력
        except Exception as e: # 그 외 모든 예외 발생 시
            if self.running: # 스레드가 여전히 실행 중이라면
                print(f"[{self.name}] 연결 처리 중 오류 발생: {e}") # 오류 메시지 출력
        finally:
            print(f"[{self.name}] ai_server({addr})와 연결 종료.") # AI 서버 연결 종료 메시지 출력
            conn.close() # 클라이언트 소켓 닫기

    def run(self): # 스레드가 시작될 때 실행되는 메인 작업 루프
        """
        .start() 메서드가 호출되면 스레드에서 실제 실행되는 메인 작업 루프.
        ai_server로부터의 연결을 수신 대기.
        """
        self.running = True # 스레드 실행 상태를 True로 설정
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # TCP/IP 서버 소켓 생성
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # TIME_WAIT 상태의 포트 재사용 설정
        self.server_socket.bind(('0.0.0.0', self.listen_port)) # 모든 IP에서 지정된 포트로 바인딩
        self.server_socket.listen(1) # 클라이언트 연결 대기 (최대 1개)
        print(f"[{self.name}] ai_server의 분석 결과를 기다리는 중... (TCP Port: {self.listen_port})") # 대기 메시지 출력

        while self.running: # 스레드가 실행 중인 동안 반복
            try:
                conn, addr = self.server_socket.accept() # 클라이언트 연결 수락
                # 현재는 ai_server가 하나이므로, 단일 연결만 처리
                self._handle_detector_connection(conn, addr) # 연결된 AI 서버를 처리하는 메서드 호출
            except socket.error: # 소켓 관련 오류 발생 시 (주로 stop() 메서드에서 소켓이 닫힐 때 발생)
                # stop() 메서드에서 소켓이 닫힐 때 발생하는 에러를 처리
                if not self.running: # 스레드가 종료 중이라면
                    break # 루프 종료
        
        print(f"[{self.name}] 스레드 루프를 종료합니다.") # 스레드 루프 종료 메시지 출력

    def stop(self): # 스레드를 안전하게 중지하는 메서드
        """
        스레드를 안전하게 중지
        """
        print(f"[{self.name}] 종료 요청을 받았습니다.") # 종료 요청 수신 메시지 출력
        self.running = False # 스레드 실행 상태를 False로 설정하여 루프 종료 유도
        if self.server_socket: # 서버 소켓이 존재하면
            self.server_socket.close() # accept() 대기를 중단시키기 위해 소켓을 닫음 (루프 탈출 유도)