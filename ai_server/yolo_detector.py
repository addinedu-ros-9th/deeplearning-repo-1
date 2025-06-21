import base64
import json
import cv2
import numpy as np
from ultralytics import YOLO
# ✅ PyTorch 2.6 보안 우회 등록
from torch.nn import ConvTranspose2d
from torch.serialization import add_safe_globals
from ultralytics.nn.tasks import DetectionModel, SegmentationModel
from ultralytics.nn.modules.conv import Conv, Concat
from ultralytics.nn.modules.block import C2f, C3, C3x
from ultralytics.nn.modules.head import Detect, Classify, Segment
# from ultralytics.nn.modules.conv import SPPF
from torch.nn import Sequential, Conv2d  # ← Conv2d 추가
from torch.nn import BatchNorm2d
from torch.nn import SiLU 
from torch.nn import ModuleList
from ultralytics.nn.modules.block import Bottleneck 
from ultralytics.nn.modules.block import SPPF  # ✅ 정확한 경로
from torch.nn import MaxPool2d
from torch.nn import Upsample
from ultralytics.nn.modules.block import DFL
from ultralytics.nn.modules.block import Proto


add_safe_globals({
    DFL: DFL, 
    DetectionModel: DetectionModel,
    SegmentationModel: SegmentationModel,
    Conv: Conv,
    C2f: C2f,
    C3: C3,
    C3x: C3x,
    Detect: Detect,
    Classify: Classify,
    Segment: Segment,
    Concat: Concat,
    SPPF: SPPF,
    Sequential: Sequential,
    Conv2d: Conv2d , # ✅ NEW!
    BatchNorm2d: BatchNorm2d,
    SiLU: SiLU,
    ModuleList: ModuleList,
    Bottleneck: Bottleneck,
    MaxPool2d: MaxPool2d,
    Upsample: Upsample,
    Proto: Proto,
    ConvTranspose2d: ConvTranspose2d,
})



class YOLODetector:
    # def __init__(self, model_path='yolov8n-seg.pt'):
    def __init__(self, model_path='best_gun_knife.pt'):
        self.model = YOLO(model_path)
        print("[YOLODetector] 모델 로드 완료")

    def predict_raw(self, frame_id, timestamp, jpeg_bytes, conf_thresh=0.5):
        try:
            # JPEG → 이미지
            nparr = np.frombuffer(jpeg_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            result = self.model(frame, verbose=False)[0]
            # result = self.model.predict(source=frame, verbose=False)[0]
            # print(f"[디버그] 모델 예측 결과 result: {result}")
            # print(f"[디버그] result.boxes: {result.boxes}")



            detections = []
            for box in result.boxes:
                conf = round(float(box.conf[0]), 2)
                if conf < conf_thresh:
                    continue  # 일정 conf 미만은 제외
                
                cls_id = int(box.cls[0])
                label = self.model.names[cls_id]
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
            # print("[YOLODetector] 예측 오류:", e)
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
