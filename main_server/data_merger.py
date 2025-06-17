# =====================================================================================
# FILE: main_server/data_merger.py
#
# PURPOSE:
#   - ImageManager, EventAnalyzer로부터 각각 이미지와 분석 결과를 큐(Queue)로 수신.
#   - 'frame_id'를 기준으로 두 데이터를 동기화하고 병합.
#   - TCP 서버 역할을 수행하여 GUI 클라이언트의 연결을 대기하고 수락.
#   - 병합된 최종 데이터(JSON + 이미지)를 연결된 GUI 클라이언트에 지속적으로 전송.
#   - SystemManager에 의해 스레드로 생성되고 관리됨.
#
# 주요 로직:
#   1. DataMerger (메인 스레드):
#      - 각 기능(이미지 처리, 이벤트 처리, 버퍼 정리, GUI 서버)을 수행할 워커 스레드들을 생성하고 관리.
#   2. _process_image_queue (워커 스레드 1):
#      - image_queue에서 (frame_id, 이미지, 타임스탬프)를 꺼냄.
#      - GUI에 실시간 스트리밍을 위해 '기본 데이터'를 즉시 gui_send_queue에 추가.
#      - 짝이 되는 이벤트가 버퍼에 있는지 확인하고, 있다면 병합하여 gui_send_queue에 추가.
#      - 없다면 이미지를 image_buffer에 저장.
#   3. _process_event_queue (워커 스레드 2):
#      - event_queue에서 '분석 결과(JSON)'를 꺼냄.
#      - 짝이 되는 이미지가 버퍼에 있는지 확인하고, 있다면 병합하여 gui_send_queue에 추가.
#      - 없다면 분석 결과를 event_buffer에 저장.
#   4. _cleanup_buffers (워커 스레드 3):
#      - 주기적으로 image_buffer와 event_buffer를 검사하여 오래된 데이터를 삭제 (메모리 누수 방지).
#   5. _gui_server_thread (워커 스레드 4 - 서버 역할):
#      - TCP 서버 소켓을 열고 GUI 클라이언트의 연결을 기다림 (listen, accept).
#      - 클라이언트가 연결되면, gui_send_queue에서 최종 병합된 데이터를 꺼내 지속적으로 전송.
#      - 클라이언트 연결이 끊어지면 다시 연결을 기다림.
# =====================================================================================

import threading # 스레드 기능을 사용하기 위한 모듈 임포트
import queue     # 큐(Queue) 자료구조를 사용하기 위한 모듈 임포트
import time      # 시간 관련 함수를 사용하기 위한 모듈 임포트
import socket    # 소켓 통신을 위한 모듈 임포트
import json      # JSON 데이터 처리를 위한 모듈 임포트
import struct    # 바이트와 파이썬 값 간의 변환을 위한 모듈 임포트

class DataMerger(threading.Thread): # DataMerger 클래스는 threading.Thread를 상속받아 스레드로 동작
    BUFFER_TIMEOUT = 5 # 버퍼에 데이터가 유지되는 최대 시간(초) 정의

    def __init__(self, image_queue, event_queue, gui_addr): # 생성자 정의
        super().__init__() # 부모 클래스(threading.Thread)의 생성자 호출
        self.name = "DataMergerThread" # 스레드 이름 설정
        self.running = False # 스레드 실행 상태를 나타내는 플래그 초기화

        # 데이터 처리용 큐
        self.image_queue = image_queue # ImageManager로부터 이미지를 받을 큐
        self.event_queue = event_queue # EventAnalyzer로부터 분석 결과를 받을 큐
        
        # GUI 전송용 서버 설정
        self.gui_addr = gui_addr # GUI 서버의 IP 주소와 포트
        self.gui_client_socket = None # 연결된 GUI 클라이언트 소켓 초기화
        self.gui_send_queue = queue.Queue(maxsize=100) # GUI로 보낼 데이터를 쌓아둘 큐 (최대 100개)

        # 데이터 동기화용 버퍼
        self.image_buffer = {} # frame_id를 키로 이미지 데이터를 저장할 버퍼
        self.event_buffer = {} # frame_id를 키로 이벤트 데이터를 저장할 버퍼
        self.lock = threading.Lock() # 버퍼 접근 시 동기화를 위한 락(Lock) 객체 생성

    def run(self): # 스레드가 시작될 때 실행되는 메서드
        self.running = True # 스레드 실행 상태를 True로 설정
        print(f"[{self.name}] 스레드 시작.") # 스레드 시작 메시지 출력

        # 워커 스레드 생성 및 시작
        threading.Thread(target=self._process_image_queue, daemon=True).start() # 이미지 처리 스레드 시작 (데몬 스레드)
        threading.Thread(target=self._process_event_queue, daemon=True).start() # 이벤트 처리 스레드 시작 (데몬 스레드)
        threading.Thread(target=self._cleanup_buffers, daemon=True).start() # 버퍼 정리 스레드 시작 (데몬 스레드)
        
        # GUI 클라이언트 연결을 처리하고 데이터를 전송하는 서버 스레드 시작
        threading.Thread(target=self._gui_server_thread, daemon=True).start() # GUI 서버 스레드 시작 (데몬 스레드)

        while self.running: # self.running이 True인 동안 반복
            time.sleep(1) # 1초 대기

        print(f"[{self.name}] 스레드 종료 중...") # 스레드 종료 메시지 출력

    def stop(self): # 스레드 종료를 요청하는 메서드
        print(f"[{self.name}] 종료 요청 수신.") # 종료 요청 수신 메시지 출력
        self.running = False # 스레드 실행 상태를 False로 설정하여 루프 종료 유도
        if self.gui_client_socket: # GUI 클라이언트 소켓이 열려있으면
            self.gui_client_socket.close() # 소켓 닫기

    def _gui_server_thread(self):
        """[서버 스레드] GUI 클라이언트의 연결을 받고, 큐의 데이터를 전송합니다."""
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # TCP/IP 소켓 생성
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # TIME_WAIT 상태의 포트 재사용 설정
        server_socket.bind(self.gui_addr) # 지정된 주소에 소켓 바인딩
        server_socket.listen(1) # 클라이언트 연결 대기 (최대 1개)
        print(f"[{self.name}] GUI 클라이언트 연결 대기 중... (TCP: {self.gui_addr})") # 연결 대기 메시지 출력

        while self.running: # 스레드가 실행 중인 동안 반복
            try:
                self.gui_client_socket, addr = server_socket.accept() # 클라이언트 연결 수락
                print(f"[{self.name}] GUI 클라이언트 연결됨: {addr}") # 클라이언트 연결 메시지 출력

                while self.running and self.gui_client_socket: # 스레드 실행 중이고 클라이언트 소켓이 연결되어 있는 동안 반복
                    try:
                        event_data, image_binary = self.gui_send_queue.get(timeout=1) # GUI 전송 큐에서 데이터 가져오기 (1초 타임아웃)
                        
                        json_part = json.dumps(event_data).encode('utf-8') # JSON 데이터를 UTF-8로 인코딩
                        data_to_send = json_part + b'|' + image_binary # JSON과 이미지 바이너리를 '|'로 연결
                        header = struct.pack('>I', len(data_to_send)) # 전송할 데이터 길이를 4바이트 빅 엔디안 정수로 팩

                        self.gui_client_socket.sendall(header + data_to_send) # 헤더와 데이터를 클라이언트에 전송
                        print(f"[✈️ 전달] 5. DataMerger -> GUI: frame_id {event_data.get('frame_id')}, status: {event_data.get('robot_status')}, size {len(header) + len(data_to_send)} bytes") # 전송 정보 출력

                    except queue.Empty: # 큐가 비어있을 경우
                        continue # 다음 루프 계속
                    except (socket.error, BrokenPipeError, ConnectionResetError) as e: # 소켓 관련 오류 발생 시
                        print(f"[{self.name}] GUI 클라이언트와 연결이 끊어졌습니다: {e}") # 연결 끊김 메시지 출력
                        self.gui_client_socket.close() # 클라이언트 소켓 닫기
                        self.gui_client_socket = None # 클라이언트 소켓 초기화
                        break # 내부 루프 종료 (새로운 연결 대기)
            
            except Exception as e: # 그 외 예외 발생 시
                print(f"[{self.name}] GUI 서버 스레드 오류: {e}") # 오류 메시지 출력
                time.sleep(1) # 1초 대기

        server_socket.close() # 서버 소켓 닫기
        print(f"[{self.name}] GUI 서버 스레드 종료.") # 서버 스레드 종료 메시지 출력

    def _put_data_to_gui_queue(self, event_data, image_binary): # 병합된 데이터를 GUI 전송 큐에 넣는 메서드
        """병합된 데이터를 GUI 전송 큐에 넣습니다."""
        if not self.gui_send_queue.full(): # 큐가 가득 차지 않았다면
            self.gui_send_queue.put((event_data, image_binary)) # 데이터 튜플을 큐에 추가

    def _process_image_queue(self):
        """[워커 1] image_queue 처리."""
        while self.running: # 스레드가 실행 중인 동안 반복
            try:
                frame_id, image_binary, timestamp = self.image_queue.get(timeout=1) # 이미지 큐에서 데이터 가져오기 (1초 타임아웃)
                
                print(f"[⬅️ 큐 출력] 4a. DataMerger: Image 큐에서 frame_id {frame_id} 수신") # 이미지 수신 메시지 출력

                streaming_data = { # 스트리밍용 기본 JSON 데이터 생성
                    'frame_id': frame_id, # 프레임 ID
                    'timestamp': timestamp, # 타임스탬프
                    'detections': [], # 빈 감지 리스트
                    'robot_status': 'streaming' # 로봇 상태를 'streaming'으로 설정
                }
                self._put_data_to_gui_queue(streaming_data, image_binary) # 기본 데이터와 이미지를 GUI 전송 큐에 추가

                with self.lock: # 락을 사용하여 버퍼 접근 동기화
                    if frame_id in self.event_buffer: # 해당 frame_id의 이벤트 데이터가 버퍼에 있다면
                        event_data, _ = self.event_buffer.pop(frame_id) # 버퍼에서 이벤트 데이터 가져오고 삭제
                        event_data['robot_status'] = 'detected' # 로봇 상태를 'detected'로 변경
                        self._put_data_to_gui_queue(event_data, image_binary) # 병합된 데이터를 GUI 전송 큐에 추가
                        print(f"[{self.name}] 빠른 이벤트와 병합 (frame_id={frame_id}). GUI 상태 업데이트.") # 병합 메시지 출력
                    else: # 짝이 되는 이벤트가 버퍼에 없다면
                        self.image_buffer[frame_id] = (image_binary, time.time()) # 이미지와 현재 시간을 버퍼에 저장
            except queue.Empty: # 큐가 비어있을 경우
                continue # 다음 루프 계속

    def _process_event_queue(self):
        """[워커 2] event_queue 처리."""
        while self.running: # 스레드가 실행 중인 동안 반복
            try:
                event_data = self.event_queue.get(timeout=1) # 이벤트 큐에서 데이터 가져오기 (1초 타임아웃)

                frame_id = event_data['frame_id'] # 이벤트 데이터에서 frame_id 추출
                print(f"[⬅️ 큐 출력] 4b. DataMerger: Event 큐에서 frame_id {frame_id} 수신") # 이벤트 수신 메시지 출력

                with self.lock: # 락을 사용하여 버퍼 접근 동기화
                    if frame_id in self.image_buffer: # 해당 frame_id의 이미지 데이터가 버퍼에 있다면
                        image_binary, _ = self.image_buffer.pop(frame_id) # 버퍼에서 이미지 데이터 가져오고 삭제
                        event_data['robot_status'] = 'detected' # 로봇 상태를 'detected'로 변경
                        self._put_data_to_gui_queue(event_data, image_binary) # 병합된 데이터를 GUI 전송 큐에 추가
                        print(f"[{self.name}] 이벤트 큐에서 병합 성공 (frame_id={frame_id}).") # 병합 성공 메시지 출력
                    else: # 짝이 되는 이미지가 버퍼에 없다면
                        self.event_buffer[frame_id] = (event_data, time.time()) # 이벤트와 현재 시간을 버퍼에 저장
            except queue.Empty: # 큐가 비어있을 경우
                continue # 다음 루프 계속

    def _cleanup_buffers(self):
        """[워커 3] 주기적으로 버퍼 정리"""
        while self.running: # 스레드가 실행 중인 동안 반복
            time.sleep(self.BUFFER_TIMEOUT) # BUFFER_TIMEOUT(5초)만큼 대기
            with self.lock: # 락을 사용하여 버퍼 접근 동기화
                current_time = time.time() # 현재 시간 기록
                # 이미지 버퍼에서 타임아웃된 이미지 ID 목록 생성
                expired_images = [fid for fid, (_, ts) in self.image_buffer.items() if current_time - ts > self.BUFFER_TIMEOUT]
                for fid in expired_images: # 만료된 각 이미지 ID에 대해
                    del self.image_buffer[fid] # 이미지 버퍼에서 해당 이미지 삭제
                    print(f"[{self.name}] 버퍼 정리: 오래된 이미지 데이터(frame_id={fid}) 삭제.") # 이미지 삭제 메시지 출력
                
                # 이벤트 버퍼에서 타임아웃된 이벤트 ID 목록 생성
                expired_events = [fid for fid, (_, ts) in self.event_buffer.items() if current_time - ts > self.BUFFER_TIMEOUT]
                for fid in expired_events: # 만료된 각 이벤트 ID에 대해
                    del self.event_buffer[fid] # 이벤트 버퍼에서 해당 이벤트 삭제
                    print(f"[{self.name}] 버퍼 정리: 오래된 이벤트 데이터(frame_id={fid}) 삭제.") # 이벤트 삭제 메시지 출력