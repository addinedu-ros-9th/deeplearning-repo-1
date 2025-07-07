# yolo_pose_detector.py
from ultralytics import YOLO
import numpy as np
import cv2

class YOLOPoseDetector:
    def __init__(self, model_path="best_pose.pt"):
        self.model = YOLO(model_path)
        self.names = self.model.names  # 클래스 이름 저장

        self.box_model = YOLO("best_cigar.pt")  # box 탐지용 모델
        self.box_names = self.box_model.names

        print(f"[YOLOPoseDetector] 모델 로드 완료: {model_path}")

    def predict_raw(self, frame_id, timestamp, jpeg_bytes, conf_thresh=0.5):
        try:
            """
            이미지에서 사람을 탐지하고, 바운딩 박스와 라벨을 반환합니다.
            반환 형식: [{'label': 'person', 'bbox': [x1, y1, x2, y2]}]
            """
            # JPEG → 이미지
            nparr = np.frombuffer(jpeg_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            results = self.model.predict(frame, conf=conf_thresh, verbose=False)
            detections = []

            if len(results) == 0:
                return detections


            # 박스 감지 결과 추가
            box_results = self.box_model.predict(frame, conf=0.5, verbose=False)
            if len(box_results) > 0:
                for r in box_results:
                    for box in r.boxes:
                        conf = float(box.conf[0].item())
                        if conf < conf_thresh:
                            continue  # 일정 conf 이하 필터링

                        cls_id = int(box.cls[0].item()) # 클래스 ID
                        label = self.box_names[cls_id] # 클레스 이름
                        x1, y1, x2, y2 = box.xyxy[0].tolist()  # 바운딩 박스 좌표

                        detections.append({
                            'label': label,
                            'box': [x1, y1, x2, y2],
                            'confidence': conf
                        })

            # 포즈
            for r in results:
                boxes = r.boxes
                for i in range(len(boxes)):
                    box = boxes[i]
                    conf = float(box.conf[0].item())
                    if conf < conf_thresh:
                            continue  # 일정 conf 이하 필터링
                    
                    
                    cls_id = int(box.cls[0].item()) # 클래스 ID
                    label = self.names[cls_id]  # 클레스 이름, lying_down, fall_down, 현재는 lying_down만 사용
                    if label not in ["lying_down", "fall_down"]:
                        continue  # 이외의 포즈는 무시
                    x1, y1, x2, y2 = box.xyxy[0].tolist()  # 바운딩 박스 좌표


                    detections.append({
                        'label': label,  
                        'box': [x1, y1, x2, y2],
                        'confidence': conf
                    })

            return {
                    "frame_id": frame_id,
                    "timestamp": timestamp,
                    "detections": detections
                }
    
        except Exception as e:
            # 예측 중 오류 발생 시 빈 결과 반환
            # print("[YOLODetector] 예측 오류:", e)
            return {
                "frame_id": frame_id,
                "timestamp": timestamp,
                "detections": []
            }
