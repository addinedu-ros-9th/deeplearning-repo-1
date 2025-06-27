import cv2
import socket
import json
import time
import sys
import subprocess
from datetime import datetime, timedelta, timezone
KST = timezone(timedelta(hours=9))  # 한국시간으로 변경

#/home/robolee/venv/dl_venv/bin/python3 /home/robolee/dev_ws/deeplearning-repo-1/robot/image_sender.py

# ✅ 설정: 수신기 IP 및 포트
SERVER_IP = '192.168.0.6'   # 수신기 (메인서버) IP
SERVER_PORT = 9001

# ✅ 현재 로컬 IP 확인
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
    finally:
        s.close()
    return local_ip

# ✅ 수신기 ping 체크
def can_ping(ip: str, timeout=1):
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return result.returncode == 0
    except Exception:
        return False

# ✅ 송신 전 네트워크 상태 점검
local_ip = get_local_ip()
print(f"📡 현재 송신기 IP: {local_ip}")

if not local_ip.startswith("192.168.0."):
    print(f"❌ 의도한 공유기에 연결되어 있지 않습니다. 현재 IP: {local_ip}")
    sys.exit(1)

if not can_ping(SERVER_IP):
    print(f"❌ 수신 대상 {SERVER_IP} 에 ping 불가. 송신 중단.")
    sys.exit(1)

print(f"✅ 네트워크 연결 상태 확인됨. 전송을 시작합니다.\n")

# ✅ UDP 소켓 생성 및 카메라 초기화
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# Try camera index 2 first, fallback to 0 if not available
cap = None
for camera_idx in [2, 0]:
    cap = cv2.VideoCapture(camera_idx)
    if cap.isOpened():
        print(f"✅ 카메라 {camera_idx}번 연결됨")
        break
    else:
        print(f"❌ 카메라 {camera_idx}번 연결 실패")

if not cap or not cap.isOpened():
    print("❌ 사용 가능한 카메라가 없습니다. 프로그램을 종료합니다.")
    sys.exit(1)
    
frame_id = 0

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    # ✅ 해상도 축소
    frame = cv2.resize(frame, (640, 480))


        # ✅ [여기 추가] 화면에 프레임 표시
    cv2.imshow("Sending Frame", frame)
    if cv2.waitKey(1) & 0xFF == 27:  # ESC 키 누르면 종료
        break

    # ✅ JPEG 압축률 조절
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 60]
    success, encoded_img = cv2.imencode('.jpg', frame, encode_param)

    if not success:
        print("⚠️ JPEG 인코딩 실패")
        continue

    jpeg_bytes = encoded_img.tobytes()

    # ✅ JSON 헤더 구성
    header_dict = {
        "frame_id": frame_id,
        "timestamp": datetime.now(KST).isoformat()
    }
    
    json_bytes = json.dumps(header_dict).encode('utf-8')




    # ✅ 패킷 구성: JSON | JPEG \n
    packet = json_bytes + b'|' + jpeg_bytes + b'\n'

    # prefix = b'\x00\x00\x00\xe5' # 메시지 크기 디버깅1
    # print(f"📏 prefix (int): {int.from_bytes(prefix, 'big')}")  #패킷 크기 디버깅

    # ✅ UDP 전송
    if len(packet) > 65000:
        print(f"⚠️ Frame {frame_id} too large to send ({len(packet)} bytes)")
    else:
        sock.sendto(packet, (SERVER_IP, SERVER_PORT))
        print(f" Frame {frame_id} 전송됨")
        print(f" JSON Header: {json_bytes.decode('utf-8')}")
        print(f"size = {len(packet)} bytes")

    frame_id += 1
    time.sleep(1 / 30)

# ✅ 종료 처리
cap.release()
sock.close()


# import cv2
# import socket
# import json
# import time
# from datetime import datetime, timezone

# # 수신 측(같은 네트워크 상) 와이파이 IP
# SERVER_IP = '192.168.0.10'     # ← 메인서버측 아이피
# SERVER_PORT = 9001

# # UDP 소켓 생성
# sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# # 카메라 초기화
# cap = cv2.VideoCapture(0)
# frame_id = 0

# while cap.isOpened():
#     ret, frame = cap.read()
#     if not ret:
#         break

#     #웹캠 이미지 해상도 축소
#     frame = cv2.resize(frame, (640, 480)) #이거만 해도 용량문제로 전송안됨
    

#     # 1. JPEG 인코딩
#     # success, encoded_img = cv2.imencode('.jpg', frame)
   

#     #2. JPEG 압축률 조절 후 인코딩
#     encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 60] # 60% 압축
#     success, encoded_img = cv2.imencode('.jpg', frame, encode_param)

#     if not success:
#         print("encoding failed") #인코딩 실패여부 확인
#         continue
#     jpeg_bytes = encoded_img.tobytes()



#     # JSON 헤더 구성
#     header_dict = {
#         "frame_id": frame_id,
#         # "timestamp": datetime.utcnow().isoformat() 곧삭제될 utcnow()
#         "timestamp": datetime.now(timezone.utc).isoformat()
#     }
#     json_bytes = json.dumps(header_dict).encode('utf-8')  # JSON을 바이트로 변환

#     # 패킷 구성: [JSON] + b'|' + [JPEG] + b'\n'
#     packet = json_bytes + b'|' + jpeg_bytes + b'\n'

#     # UDP 전송
#     if len(packet) > 65000:
#         print(f"⚠️ Frame {frame_id} too large to send via UDP ({len(packet)} bytes)")
#     else:
#         sock.sendto(packet, (SERVER_IP, SERVER_PORT))
#         print(f"📥 Frame {frame_id}")
#         print(f"🧾 JSON Header: {json_bytes.decode('utf-8')}")

#     frame_id += 1
#     time.sleep(1 / 30)  # 30FPS 제한

# # 정리
# cap.release()
# sock.close()
