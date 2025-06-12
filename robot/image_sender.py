import cv2
import socket
import json
import time
from datetime import datetime, timezone

# 수신 측(같은 네트워크 상) 와이파이 IP
SERVER_IP = '192.168.0.3'     # ← 수신기 와이파이 IP로 교체
SERVER_PORT = 5005

# UDP 소켓 생성
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# 카메라 초기화
cap = cv2.VideoCapture(0)
frame_id = 0

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    #웹캠 이미지 해상도 축소
    frame = cv2.resize(frame, (640, 480)) #이거만 해도 용량문제로 전송안됨
    

    # 1. JPEG 인코딩
    # success, encoded_img = cv2.imencode('.jpg', frame)
   

    #2. JPEG 압축률 조절 후 인코딩
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 60] # 60% 압축
    success, encoded_img = cv2.imencode('.jpg', frame, encode_param)

    if not success:
        print("encoding failed") #인코딩 실패여부 확인
        continue
    jpeg_bytes = encoded_img.tobytes()



    # JSON 헤더 구성
    header_dict = {
        "frame_id": frame_id,
        # "timestamp": datetime.utcnow().isoformat() 곧삭제될 utcnow()
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    json_bytes = json.dumps(header_dict).encode('utf-8')  # JSON을 바이트로 변환

    # 패킷 구성: [JSON] + b'|' + [JPEG] + b'\n'
    packet = json_bytes + b'|' + jpeg_bytes + b'\n'

    # UDP 전송
    if len(packet) > 65000:
        print(f"⚠️ Frame {frame_id} too large to send via UDP ({len(packet)} bytes)")
    else:
        sock.sendto(packet, (SERVER_IP, SERVER_PORT))
        print(f"📥 Frame {frame_id}")

    frame_id += 1
    time.sleep(1 / 30)  # 30FPS 제한

# 정리
cap.release()
sock.close()
