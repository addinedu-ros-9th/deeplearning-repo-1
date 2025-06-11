# =====================================================================================
# FILE: main_server/image_manager.py
#
# PURPOSE: (초기 연동 테스트용)
#   - 로봇(image_sender)으로부터 들어오는 UDP 이미지 패킷을 수신.
#   - 수신한 패킷을 **그대로** AI 서버(detector_manager)로 UDP 전송 (패스스루).
#   - 동시에, 수신한 원본 이미지를 내부의 Merger가 사용할 수 있도록 공유 큐에 저장.
# =====================================================================================


# -------------------------------------------------------------------------------------
# [섹션 1] 모듈 임포트
# -------------------------------------------------------------------------------------
# - socket: UDP 통신용
# - threading: 독립적인 실행을 위한 스레드 클래스 상속
# - json: 메타데이터 파싱용
# - queue: SystemManager로부터 받은 공유 큐


# -------------------------------------------------------------------------------------
# [섹션 2] ImageManager 클래스 정의 (threading.Thread 상속)
# -------------------------------------------------------------------------------------

# class ImageManager(threading.Thread):
#   """
#   로봇의 영상 프레임을 수신하고 AI 서버와 Merger로 분배하는 클래스.
#   """

#   # def __init__(self, listen_port, ai_server_addr, output_queue):
#     # """
#     # ImageManager 초기화.
#     # - listen_port: 로봇의 이미지를 수신할 포트 번호
#     # - ai_server_addr: 이미지를 전달할 AI 서버의 (IP, 포트) 튜플
#     # - output_queue: 원본 이미지를 Merger에 전달하기 위한 공유 큐
#     # """
#     # - self.listen_port = listen_port
#     # - self.ai_server_addr = ai_server_addr
#     # - self.output_queue = output_queue
#     # - self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
#     # - self.running = False

#   # def run(self):
#     # """
#     # 스레드가 시작되면 실행되는 메인 루프.
#     # """
#     # - self.running = True
#     # - 소켓을 listen_port에 바인딩
#     # - while self.running:
#       # - # 1. 로봇으로부터 UDP 데이터 수신
#       # - data, robot_addr = self.sock.recvfrom(65535)

#       # - # 2. (핵심 임무 1) AI 서버로 즉시 전달 (패스스루)
#       # - #    수신한 데이터를 아무런 가공 없이 그대로 AI 서버 주소로 전송.
#       # - self.sock.sendto(data, self.ai_server_addr)
#       # - print(f"{self.ai_server_addr}로 이미지 전달 완료")

#       # - # 3. (핵심 임무 2) Merger를 위해 내부 큐에 데이터 저장
#       # - #    메시지 명세에 따라 JSON과 이미지 데이터 분리 
#       # - try:
#       # -   json_part, image_part = data.split(b'|', 1)
#       # -   meta_data = json.loads(json_part.decode('utf-8'))
#       # -   frame_id = meta_data.get('frame_id')
#
#       # -   # Merger가 frame_id를 기준으로 데이터를 합칠 수 있도록
#       # -   # (frame_id, 이미지 바이너리) 형태의 튜플로 만들어 큐에 넣는다.
#       # -   if frame_id is not None:
#       # -     self.output_queue.put((frame_id, image_part))
#       # -     print(f"Frame {frame_id}를 Merger용 큐에 저장")
#       # - except Exception as e:
#       # -   print(f"데이터 파싱 또는 큐 저장 오류: {e}")

#   # def stop(self):
#     # # 루프를 중지하고 소켓을 닫는 정리 코드