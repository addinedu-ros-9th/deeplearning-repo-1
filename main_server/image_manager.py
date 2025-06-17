# =====================================================================================
# FILE: main_server/image_manager.py
#
# PURPOSE:
#   - 로봇(image_sender)으로부터 UDP 영상 패킷을 실시간으로 수신하는 역할.
#   - 수신한 데이터를 두 경로로 동시에 분배:
#     1. AI 서버(detector_manager)로 즉시 전달하여 영상 분석 요청.
#     2. 내부의 Merger가 사용할 수 있도록 원본 데이터를 공유 큐에 저장.
#   - SystemManager에 의해 스레드로 생성되고 관리됨.
#
# 주요 로직:
#   1. ImageManager (메인 스레드):
#      - 로봇으로부터 UDP 소켓을 통해 영상 데이터 패킷을 지속적으로 수신.
#      - 수신된 단일 패킷(JSON 메타데이터 + 이미지 바이너리)을 두 가지 목적으로 분배.
#   2. 데이터 수신 및 파싱:
#      - 수신된 데이터에서 '|'를 기준으로 JSON 메타데이터와 이미지 바이너리 부분을 분리.
#      - JSON 메타데이터를 파싱하여 'frame_id', 'timestamp' 등의 정보를 추출.
#   3. AI 서버로 전달 (즉시):
#      - 수신된 원본 전체 데이터(메타데이터 + 이미지)를 AI 서버(detector_manager)로 UDP를 통해 즉시 재전송.
#   4. Merger 큐에 저장:
#      - 파싱된 'frame_id', 원본 '이미지 바이너리', 'timestamp'를 `output_queue`에 넣어 DataMerger로 전송.
# =====================================================================================

# -------------------------------------------------------------------------------------
# [섹션 1] 모듈 임포트 (Module Imports)
# -------------------------------------------------------------------------------------
import socket # 소켓 통신을 위한 모듈 임포트
import threading # 스레드 기능을 사용하기 위한 모듈 임포트
import queue # 큐(Queue) 자료구조를 사용하기 위한 모듈 임포트
import json # JSON 데이터 처리를 위한 모듈 임포트

# -------------------------------------------------------------------------------------
# [섹션 2] ImageManager 클래스 정의
# -------------------------------------------------------------------------------------
class ImageManager(threading.Thread): # ImageManager 클래스는 threading.Thread를 상속받아 스레드로 동작
    """
    로봇의 영상 프레임을 수신하고, AI서버와 Merger로 분배하는 클래스.
    threading.Thread를 상속받아 독립적인 작업 단위로 동작.
    """
    BUFFER_SIZE = 65535  # UDP 패킷 수신을 위한 버퍼 크기 (최대 UDP 데이터그램 크기)

    def __init__(self, listen_port, ai_server_addr, output_queue): # 생성자 정의
        super().__init__() # 부모 클래스(threading.Thread)의 생성자 호출
        self.listen_port = listen_port              # 로봇으로부터 UDP 패킷을 수신 대기할 포트 번호.
        self.ai_server_addr = ai_server_addr        # AI 서버의 주소 (host, port)
        self.output_queue = output_queue            # ImageManager가 원본 이미지를 Merger로 보내기 위한 큐

        self.running = False # 스레드 실행 상태를 나타내는 플래그 초기화

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)    # UDP 통신을 위한 소켓 객체 생성 (IPv4, UDP)

        self.name = "ImageManagerThread"  # 스레드 이름 지정 (디버깅에 유용)

    def run(self): # 스레드가 시작될 때 실행되는 메인 작업 루프
        """
        .start() 메서드가 호출되면 스레드에서 실제 실행되는 메인 작업 루프.
        """
        self.running = True # 스레드 실행 상태를 True로 설정
        self.sock.bind(('0.0.0.0', self.listen_port)) # 모든 IP에서 지정된 포트로 소켓 바인딩
        print(f"{self.name}: Listening on UDP port {self.listen_port}") # 수신 대기 메시지 출력

        while self.running: # stop() 메서드가 호출되기 전까지 무한 반복
            try:
                # 로봇으로 부터 UDP 데이터 수신 대기
                data, robot_addr = self.sock.recvfrom(self.BUFFER_SIZE) # 로봇으로부터 UDP 데이터 수신

                # 1. 데이터를 먼저 분리하고 JSON을 한 번만 파싱합니다.
                json_part, image_part = data.split(b'|', 1) # 수신 데이터에서 '|'를 기준으로 JSON과 이미지 부분 분리
                meta_data = json.loads(json_part.decode('utf-8')) # JSON 부분을 UTF-8로 디코딩 후 파싱
                frame_id = meta_data.get('frame_id') # 메타데이터에서 frame_id 추출

                # 2. 파싱된 'meta_data' 변수를 사용하여 모든 작업을 처리합니다.
                print(f"[✅ 수신] 1. Robot -> ImageManager: frame_id {meta_data.get('frame_id')}, timestamp {meta_data.get('timestamp')}, size {len(data)} bytes (from {robot_addr})") # 수신 로그 출력

                # [임무 1] AI 서버로 데이터 즉시 전달
                print(f"[✈️ 전달] 2. ImageManager -> AI_Server: frame_id {meta_data.get('frame_id')}, timestamp {meta_data.get('timestamp')}, size {len(data)} bytes") # AI 서버 전달 로그 출력
                self.sock.sendto(data, self.ai_server_addr) # 수신된 원본 데이터를 AI 서버로 전송
                
                # [임무 2] Merger를 위해 큐에 데이터 저장
                print(f"[➡️ 큐 입력] 4a. ImageManager -> DataMerger: frame_id {meta_data.get('frame_id')}, timestamp {meta_data.get('timestamp')}, image_size {len(image_part)} bytes") # Merger 큐 입력 로그 출력
                # 'meta_data'에서 timestamp도 가져옵니다.
                timestamp = meta_data.get('timestamp') # 메타데이터에서 timestamp 추출
                # 큐에 frame_id, image_binary, timestamp 세 가지를 모두 넣어줍니다.
                self.output_queue.put((frame_id, image_part, timestamp)) # 프레임 ID, 이미지 바이너리, 타임스탬프를 큐에 저장

            except socket.error as e: # 소켓 관련 오류 발생 시
                # self.sock.close()에 의해 정상적으로 발생하는 소켓 에러는 무시
                if self.running: # 스레드가 여전히 실행 중이라면
                    print(f"{self.name}: Socket error: {e}") # 소켓 오류 메시지 출력
                break # 루프 탈출

            except Exception as e: # 그 외 모든 예외 발생 시
                print(f"{self.name}: Critical error: {e}") # 치명적인 오류 메시지 출력
                break # 루프 탈출
        
        print(f"{self.name}: Thread loop finished.") # 스레드 루프 종료 메시지 출력
        
        
    def stop(self): # 스레드를 안전하게 중지시키는 메서드
        """
        스레드를 안전하게 중지시키기 위해 running 플래그를 False로 설정합니다.
        run() 메서드의 루프는 이 플래그를 확인하고 종료 절차를 시작합니다.
        """
        print(f"{self.name}: Stop requested.") # 종료 요청 수신 메시지 출력
        self.running = False # 스레드 실행 상태를 False로 설정하여 루프 종료 유도
        self.sock.close() # 소켓 닫기 (recvfrom 대기를 중단시켜 루프 탈출 유도)