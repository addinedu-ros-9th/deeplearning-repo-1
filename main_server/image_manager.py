# =====================================================================================
# FILE: main_server/image_manager.py
#
# PURPOSE:
#   - 로봇(image_sender)으로부터 UDP 영상 패킷을 실시간으로 수신하는 역할.
#   - 수신한 데이터를 두 경로로 동시에 분배:
#     1. AI 서버(detector_manager)로 즉시 전달하여 영상 분석 요청.
#     2. 내부의 Merger가 사용할 수 있도록 원본 데이터를 공유 큐에 저장.
#   - SystemManager에 의해 스레드로 생성되고 관리됨.
# =====================================================================================

# -------------------------------------------------------------------------------------
# [섹션 1] 모듈 임포트 (Module Imports)
# -------------------------------------------------------------------------------------
import socket
import threading
import queue
import json

# -------------------------------------------------------------------------------------
# [섹션 2] ImageManager 클래스 정의
# -------------------------------------------------------------------------------------
class ImageManager(threading.Thread):
    """
    로봇의 영상 프레임을 수신하고, AI서버와 Merger로 분배하는 클래스.
    threading.Thread를 상속받아 독립적인 작업 단위로 동작.
    """
    BUFFER_SIZE = 65535  # UDP 패킷 수신을 위한 버퍼 크기

    def __init__(self, listen_port, ai_server_addr, output_queue):
        super().__init__()
        self.listen_port = listen_port              # 로봇으로부터 UDP 패킷을 수신 대기할 포트 번호.
        self.ai_server_addr = ai_server_addr        # AI 서버의 주소 (host, port)
        self.output_queue = output_queue            # ImageManager가 원본 이미지를 Merger로 보내기 위한 큐

        self.running = False

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)    # UDP 통신을 위한 소켓 객체 생성

        self.name = "ImageManagerThread"  # 스레드 이름 지정 (디버깅에 유용)

    def run(self):
        """
        .start() 메서드가 호출되면 스레드에서 실제 실행되는 메인 작업 루프.
        """
        self.running = True
        self.sock.bind(('0.0.0.0', self.listen_port))
        print(f"{self.name}: Listening on UDP port {self.listen_port}")

        while self.running: # stop() 메서드가 호출되기 전까지 무한 반복
            try:
                # 로봇으로 부터 UDP 데이터 수신 대기
                data, robot_addr = self.sock.recvfrom(self.BUFFER_SIZE)

                # 1. 데이터를 먼저 분리하고 JSON을 한 번만 파싱합니다.
                json_part, image_part = data.split(b'|', 1)
                meta_data = json.loads(json_part.decode('utf-8'))
                frame_id = meta_data.get('frame_id')

                # 2. 파싱된 'meta_data' 변수를 사용하여 모든 작업을 처리합니다.
                print(f"[✅ 수신] 1. Robot -> ImageManager: frame_id {meta_data.get('frame_id')}, timestamp {meta_data.get('timestamp')}, size {len(data)} bytes (from {robot_addr})")

                # [임무 1] AI 서버로 데이터 즉시 전달
                print(f"[✈️ 전달] 2. ImageManager -> AI_Server: frame_id {meta_data.get('frame_id')}, timestamp {meta_data.get('timestamp')}, size {len(data)} bytes")
                self.sock.sendto(data, self.ai_server_addr)
                
                # [임무 2] Merger를 위해 큐에 데이터 저장
                print(f"[➡️ 큐 입력] 4a. ImageManager -> DataMerger: frame_id {meta_data.get('frame_id')}, timestamp {meta_data.get('timestamp')}, image_size {len(image_part)} bytes")
                # 'meta_data'에서 timestamp도 가져옵니다.
                timestamp = meta_data.get('timestamp')
                # 큐에 frame_id, image_binary, timestamp 세 가지를 모두 넣어줍니다.
                self.output_queue.put((frame_id, image_part, timestamp))

            except socket.error as e:
                # self.sock.close()에 의해 정상적으로 발생하는 소켓 에러는 무시
                if self.running:
                    print(f"{self.name}: Socket error: {e}")
                break # 루프 탈출

            except Exception as e:
                print(f"{self.name}: Critical error: {e}")
                break # 루프 탈출
        
        print(f"{self.name}: Thread loop finished.")
        
        
    def stop(self):
        """
        스레드를 안전하게 중지시키기 위해 running 플래그를 False로 설정합니다.
        run() 메서드의 루프는 이 플래그를 확인하고 종료 절차를 시작합니다.
        """
        print(f"{self.name}: Stop requested.")
        self.running = False
        self.sock.close()