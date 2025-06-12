import base64
import json
import cv2
import numpy as np
from ultralytics import YOLO

class YOLODetector:
    def __init__(self, model_path='yolov8n-seg.pt'):
        self.model = YOLO(model_path)
        print("[YOLODetector] 모델 로드 완료")

    def predict_raw(self, frame_id, timestamp, jpeg_bytes):
        try:
            # JPEG → 이미지
            nparr = np.frombuffer(jpeg_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            result = self.model(frame, verbose=False)[0]
            # result = self.model.predict(source=frame, verbose=False)[0]

            detections = []
            for box in result.boxes:
                cls_id = int(box.cls[0])
                label = self.model.names[cls_id]
                conf = round(float(box.conf[0]), 2)
                x1, y1, x2, y2 = map(int, box.xyxy[0])

                detections.append({
                    "label": label,
                    "confidence": conf,
                    "box": [x1, y1, x2, y2]
                })

            return {
                "frame_id": frame_id,
                "timestamp": timestamp,
                "detections": detections
            }
        except Exception as e:
            print("[YOLODetector] 예측 오류:", e)
            return {
                "frame_id": frame_id,
                "timestamp": timestamp,
                "detections": []
            }


# 아래는 독립 실행용 테스트 코드입니다. detector_manager 통합 시 제거 가능
if __name__ == "__main__":
    import socket
    import threading

    HOST = '0.0.0.0'
    PORT = 9101

    detector = YOLODetector()

    def handle_client(conn, addr):
        print(f"[클라이언트 연결됨] {addr}")
        buffer = b""
        while True:
            try:
                data = conn.recv(4096)
                if not data:
                    break
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    request = json.loads(line.decode())
                    response = detector.predict(
                        frame_id=request.get("frame_id"),
                        timestamp=request.get("timestamp"),
                        image_b64=request.get("image")
                    )
                    conn.sendall((json.dumps(response) + "\n").encode())
                    print(f"[예측 전송 완료] frame_id={response['frame_id']}, 객체={len(response['detections'])}건")
            except Exception as e:
                print("[핸들 오류]", e)
                break
        conn.close()
        print(f"[클라이언트 연결 종료] {addr}")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(5)
    print(f"[YOLO TCP 서버 대기 중] {HOST}:{PORT}")

    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
