# =====================================================================================
# FILE: main_server/data_merger.py
#
# PURPOSE:
#   - 시스템의 '데이터 최종 조립 공장' 및 '녹화 스튜디오' 역할.
#   - ImageManager로부터 받은 이미지 데이터와 EventAnalyzer로부터 받은 AI 분석 결과를
#     프레임 ID를 기준으로 병합.
#   - 칼만 필터(Kalman Filter)를 이용한 객체 추적(Object Tracking) 알고리즘을 구현하여,
#     단순 탐지를 넘어 각 객체에 고유 ID를 부여하고 움직임을 부드럽게 추적.
#   - EventAnalyzer가 판단한 이벤트의 종류('case_type')에 따라 탐지된 객체의
#     바운딩 박스 색상을 다르게 시각화.
#   - 로봇 상태가 'detected'가 되면 영상 녹화를 시작하고, DBManager로부터 신호를 받아
#     녹화를 종료하며 최종 파일을 저장하는 전체 녹화 라이프사이클을 관리.
#   - 최종적으로 병합되고 시각화된 데이터를(JSON + 이미지) GUI 클라이언트로 전송.
#
# 주요 로직:
#   1. TrackedObject 클래스:
#      - 추적되는 개별 객체를 나타내는 클래스.
#      - 각 객체는 고유한 track_id와 칼만 필터(KalmanFilter) 인스턴스를 가짐.
#      - 칼만 필터는 객체의 다음 위치를 예측하고, 새로운 탐지 결과로 상태를 보정하여
#        부드러운 추적 궤적을 생성.
#      - 객체의 레이블, 신뢰도, 그리고 이벤트 종류('case_type')를 함께 저장.
#   2. DataMerger 클래스 (메인 처리 로직):
#      - 데이터 수신 및 버퍼링: 별도 스레드에서 ImageManager와 EventAnalyzer로부터 오는
#        데이터를 각각의 큐에서 꺼내 프레임 ID 기반의 버퍼에 저장.
#      - 데이터 병합 (_merge_and_record_thread):
#        - 이미지 버퍼와 이벤트 버퍼에 공통으로 존재하는 프레임 ID를 찾아 병합 처리.
#        - AI 결과가 없는 이미지 프레임도 GUI에 부드러운 영상 스트림을 제공하기 위해 별도 처리.
#      - 객체 추적 (_update_tracks):
#        - (1) 예측: 현재 추적 중인 모든 객체의 다음 위치를 칼만 필터로 예측.
#        - (2) 매칭: 예측된 위치와 새로 들어온 AI 탐지 결과를 IoU(Intersection over Union)로 비교하여 최적의 쌍을 찾음.
#        - (3) 업데이트: 매칭된 객체는 정보를 업데이트하고, 매칭되지 않은 새로운 탐지는 신규 객체로 등록.
#      - 시각화 (_draw_detections_and_get_frame):
#        - 추적된 객체의 바운딩 박스를 프레임에 그림.
#        - 이 때, 객체의 'case_type'에 따라 박스 색상을 다르게 설정 (danger:빨강, illegal:파랑 등).
#      - 녹화 관리 (_handle_recording, _start_recording, _stop_recording):
#        - robot_status가 'detected'가 되면 _start_recording을 호출하여 임시 파일로 녹화 시작.
#        - DBManager가 로그 저장 후 `robot_status['recording_stop_signal']`에 신호를 보내면,
#          _stop_recording이 호출되어 녹화를 중단하고 임시 파일의 이름을 최종 이름으로 변경.
#      - GUI 전송 (_gui_send_thread):
#        - 최종 처리된 데이터(JSON + 이미지)를 큐에서 꺼내 GUI로 전송.
# =====================================================================================

# -------------------------------------------------------------------------------------
# [섹션 1] 모듈 임포트
# -------------------------------------------------------------------------------------
import threading
import queue
import socket
import json
import struct
import time
import os
import cv2
import numpy as np
from datetime import datetime, timedelta
from collections import deque
# 객체 추적을 위한 칼만 필터 관련 라이브러리
from filterpy.kalman import KalmanFilter
from filterpy.common import Q_discrete_white_noise

# -------------------------------------------------------------------------------------
# [섹션 2] 유틸리티 함수
# -------------------------------------------------------------------------------------
def iou(boxA, boxB):
    """ 두 바운딩 박스 간의 IoU(Intersection over Union)를 계산. """
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])
    interArea = max(0, xB - xA) * max(0, yB - yA)
    boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    iou_val = interArea / float(boxAArea + boxBArea - interArea)
    return iou_val

def convert_bbox_to_z(bbox):
    """ [x1, y1, x2, y2] 형식의 바운딩 박스를 칼만 필터의 측정값 [cx, cy, w, h]으로 변환. """
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = bbox[0] + w / 2.
    y = bbox[1] + h / 2.
    return np.array([x, y, w, h]).reshape(4, 1)

def convert_x_to_bbox(x):
    """ 칼만 필터의 상태값 [cx, cy, w, h, ...]에서 바운딩 박스 [x1, y1, x2, y2]를 추출. """
    w = x[2]
    h = x[3]
    return np.array([x[0] - w / 2., x[1] - h / 2., x[0] + w / 2., x[1] + h / 2.]).flatten()

# -------------------------------------------------------------------------------------
# [섹션 3] TrackedObject 클래스
# -------------------------------------------------------------------------------------
class TrackedObject:
    """ 추적되는 각 객체의 상태와 칼만 필터를 관리하는 클래스. """
    next_id = 0 # 모든 객체에 고유 ID를 할당하기 위한 클래스 변수
    def __init__(self, initial_bbox, label, confidence, case_type):
        self.id = TrackedObject.next_id # 고유 ID 할당
        TrackedObject.next_id += 1
        
        # 객체의 속성 정보
        self.label = label
        self.confidence = confidence
        self.case_type = case_type # 이벤트 종류 (danger, illegal, emergency)
        self.last_updated = time.time() # 마지막으로 업데이트된 시간
        self.missed_frames = 0 # 연속으로 탐지되지 않은 프레임 수
        
        # --- 칼만 필터 설정 (8차원 상태, 4차원 측정) ---
        # 상태 변수 (x): [cx, cy, w, h, vx, vy, vw, vh] (중심점, 크기, 각 속도)
        self.kf = KalmanFilter(dim_x=8, dim_z=4)
        dt = 1.0 # 시간 간격
        # 상태 전이 행렬 (F): 이전 상태가 현재 상태에 어떻게 영향을 미치는지 정의
        self.kf.F = np.array([[1,0,0,0,dt,0,0,0], [0,1,0,0,0,dt,0,0], [0,0,1,0,0,0,dt,0], [0,0,0,1,0,0,0,dt],
                              [0,0,0,0,1,0,0,0], [0,0,0,0,0,1,0,0], [0,0,0,0,0,0,1,0], [0,0,0,0,0,0,0,1]], dtype=float)
        # 측정 행렬 (H): 실제 상태가 측정값으로 어떻게 나타나는지 정의
        self.kf.H = np.array([[1,0,0,0,0,0,0,0], [0,1,0,0,0,0,0,0], [0,0,1,0,0,0,0,0], [0,0,0,1,0,0,0,0]], dtype=float)
        # 측정 노이즈 공분산 (R): AI 탐지 결과(측정값)의 불확실성. 클수록 예측을 더 신뢰.
        self.kf.R *= 5.
        # 프로세스 노이즈 공분산 (Q): 모델 예측의 불확실성. 클수록 객체의 급격한 움직임에 잘 반응.
        q_val = 0.1
        self.kf.Q = Q_discrete_white_noise(dim=2, dt=1.0, var=q_val, block_size=4, order_by_dim=False)
        # 초기 오차 공분산 (P)
        self.kf.P *= 100.
        # 초기 상태 설정
        initial_state = convert_bbox_to_z(initial_bbox).flatten()
        self.kf.x = np.array([initial_state[0], initial_state[1], initial_state[2], initial_state[3], 0, 0, 0, 0]).T

    def predict(self):
        """ 칼만 필터를 사용해 객체의 다음 상태를 예측. """
        self.confidence *= 0.95 # 탐지되지 않을 때마다 신뢰도 감소
        self.kf.predict()
        return self.kf.x
    
    def update(self, bbox, confidence, case_type):
        """ 새로운 탐지 결과로 칼만 필터의 상태를 업데이트. """
        self.kf.update(convert_bbox_to_z(bbox))
        self.confidence = confidence
        self.case_type = case_type # case_type도 함께 업데이트
        self.last_updated = time.time()
        self.missed_frames = 0 # 탐지되었으므로 missed_frames 초기화


class DataMerger(threading.Thread):
    def __init__(self, image_queue, event_queue, gui_listen_addr, robot_status):
        super().__init__()
        self.name = "DataMerger"
        self.running = True

        # --- 공유 자원 및 외부 설정 ---
        self.image_queue = image_queue
        self.event_queue = event_queue
        self.gui_send_queue = queue.Queue(maxsize=100)
        self.robot_status = robot_status
        
        # --- 내부 버퍼 및 잠금 ---
        self.image_buffer = {}
        self.event_buffer = {}
        self.buffer_lock = threading.Lock()

        # --- GUI 통신 설정 ---
        self.gui_listen_addr = gui_listen_addr
        self.gui_server_socket = None
        self.gui_client_socket = None

        # --- 객체 추적 관련 설정 ---
        self.tracked_objects = {} # 현재 추적중인 객체들을 저장하는 딕셔너리
        self.iou_threshold = 0.3 # 추적과 탐지를 매칭시키기 위한 IoU 임계값
        self.max_missed_frames = 10 # 객체 추적을 포기하기 전까지 놓칠 수 있는 최대 프레임 수

        # --- 녹화 관련 설정 ---
        self.is_recording = False
        self.video_writer = None
        self.temp_img_path = None
        self.temp_video_path = None
        self.base_dir = 'main_server'
        os.makedirs(os.path.join(self.base_dir, 'images'), exist_ok=True)
        os.makedirs(os.path.join(self.base_dir, 'videos'), exist_ok=True)
        
        print(f"[{self.name}] 초기화 완료 (객체 추적 칼만 필터 적용).")

    def run(self):
        """ DataMerger의 모든 서브 스레드를 시작하고 관리. """
        print(f"[{self.name}] 스레드 시작.")
        threads = [
            threading.Thread(target=self._gui_accept_thread, daemon=True),
            threading.Thread(target=self._gui_send_thread, daemon=True),
            threading.Thread(target=self._image_receive_thread, daemon=True),
            threading.Thread(target=self._event_receive_thread, daemon=True),
            threading.Thread(target=self._merge_and_record_thread, daemon=True)
        ]
        for t in threads: t.start()
        for t in threads: t.join()
        print(f"[{self.name}] 스레드 종료.")

    def _gui_accept_thread(self):
        """ GUI 클라이언트의 연결을 수락하는 스레드. """
        self.gui_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.gui_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.gui_server_socket.bind(self.gui_listen_addr)
        self.gui_server_socket.listen(1)
        print(f"[{self.name}] GUI 클라이언트 연결 대기 중... ({self.gui_listen_addr})")
        while self.running:
            try:
                conn, addr = self.gui_server_socket.accept()
                print(f"[{self.name}] GUI 클라이언트 연결됨: {addr}")
                if self.gui_client_socket: self.gui_client_socket.close()
                self.gui_client_socket = conn
            except socket.error:
                if not self.running: break

    def _image_receive_thread(self):
        """ image_queue에서 이미지 데이터를 받아와 image_buffer에 저장하는 스레드. """
        while self.running:
            try:
                frame_id, timestamp, jpeg_binary = self.image_queue.get(timeout=1)
                with self.buffer_lock:
                    self.image_buffer[frame_id] = (jpeg_binary, timestamp, datetime.now())
            except queue.Empty:
                continue

    def _event_receive_thread(self):
        """ event_queue에서 AI 분석 결과를 받아와 event_buffer에 저장하는 스레드. """
        while self.running:
            try:
                event_data = self.event_queue.get(timeout=1)
                frame_id = event_data['frame_id']
                with self.buffer_lock:
                    self.event_buffer[frame_id] = (event_data, datetime.now())
            except queue.Empty:
                continue

    def _gui_send_thread(self):
        """ gui_send_queue에서 최종 데이터를 꺼내 GUI 클라이언트로 전송하는 스레드. """
        while self.running:
            try:
                if not self.gui_client_socket:
                    time.sleep(0.5)
                    continue
                
                json_data, image_binary = self.gui_send_queue.get(timeout=1)
                
                json_part = json.dumps(json_data).encode('utf-8')
                payload = json_part + b'|' + image_binary
                header = struct.pack('>I', len(payload))
                
                self.gui_client_socket.sendall(header + payload)

            except queue.Empty:
                continue
            except (BrokenPipeError, ConnectionResetError, socket.error) as e:
                print(f"[{self.name}] GUI 연결 끊어짐: {e}.")
                if self.gui_client_socket: self.gui_client_socket.close()
                self.gui_client_socket = None

    def _merge_and_record_thread(self):
        """ 데이터를 병합하고, 상태에 따라 녹화 및 객체 추적을 수행하는 메인 로직 스레드. """
        while self.running:
            # DBManager로부터 녹화 종료 신호가 왔는지 확인
            stop_signal = self.robot_status.get('recording_stop_signal')
            if self.is_recording and stop_signal:
                self._stop_recording(stop_signal)
                self.robot_status['recording_stop_signal'] = None
                
            processed_ids = set()
            with self.buffer_lock:
                # 이미지와 이벤트가 모두 있는 프레임 처리
                common_ids = self.image_buffer.keys() & self.event_buffer.keys()
                for fid in common_ids:
                    if fid not in self.image_buffer or fid not in self.event_buffer: continue
                    jpeg_binary, timestamp, _ = self.image_buffer[fid]
                    event_data, _ = self.event_buffer[fid]
                    self._process_merged_frame(fid, timestamp, jpeg_binary, event_data)
                    processed_ids.add(fid)

                # AI 결과 없이 이미지만 있는 프레임 처리 (GUI 영상 부드럽게)
                timeout = timedelta(seconds=0.3)
                now = datetime.now()
                old_image_ids = {fid for fid, (_, _, ts) in self.image_buffer.items() if now - ts > timeout}
                for fid in old_image_ids:
                    if fid in processed_ids or fid not in self.image_buffer: continue
                    jpeg_binary, timestamp, _ = self.image_buffer[fid]
                    current_state = self.robot_status.get('state', 'idle')
                    self._process_unmerged_frame(fid, timestamp, jpeg_binary, current_state)
                    processed_ids.add(fid)
                    
                # 처리된 데이터 버퍼에서 제거
                for fid in processed_ids:
                    self.image_buffer.pop(fid, None)
                    self.event_buffer.pop(fid, None)

            # 오래된 추적 객체 정리
            self._cleanup_tracks()
            time.sleep(0.03)

    def _process_merged_frame(self, frame_id, timestamp, jpeg_binary, event_data):
        """ AI 분석 결과와 병합된 프레임을 처리 (객체 추적, 녹화, GUI 전송). """
        raw_detections = event_data.get('detections', [])
        
        # 칼만 필터 기반 객체 추적 수행
        filtered_detections = self._update_tracks(raw_detections)

        # 추적 결과를 이미지에 시각화
        annotated_frame = self._draw_detections_and_get_frame(jpeg_binary, filtered_detections)
        if annotated_frame is None: return

        # 녹화 처리
        self._handle_recording(annotated_frame)
        
        if self.gui_send_queue.full(): return
        _, annotated_jpeg_binary = cv2.imencode('.jpg', annotated_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])

        merged_json = {
            "frame_id": frame_id,
            "timestamp": timestamp,
            "detections": filtered_detections, # 추적된 객체 정보
            "robot_status": self.robot_status.get('state', 'detected'),
            "location": self.robot_status.get('current_location', 'unknown')
        }
        # GUI 전송 큐에 삽입
        self.gui_send_queue.put((merged_json, annotated_jpeg_binary.tobytes()))

    def _update_tracks(self, new_detections):
        """ 칼만 필터와 IoU를 사용하여 객체 추적을 업데이트. """
        # 1. 예측 단계: 모든 추적 객체의 다음 상태를 예측
        predicted_bboxes = {}
        for track_id, tracker in self.tracked_objects.items():
            predicted_state = tracker.predict()
            predicted_bboxes[track_id] = convert_x_to_bbox(predicted_state)
            tracker.missed_frames += 1

        # 2. 매칭 단계: 예측된 바운딩 박스와 새로운 탐지 결과를 IoU 기반으로 매칭
        unmatched_detections = list(range(len(new_detections)))
        matched_pairs = []

        if len(predicted_bboxes) > 0 and len(new_detections) > 0:
            iou_matrix = np.zeros((len(predicted_bboxes), len(new_detections)), dtype=float)
            track_ids = list(predicted_bboxes.keys())
            for t, track_id in enumerate(track_ids):
                for d, det in enumerate(new_detections):
                    iou_matrix[t, d] = iou(predicted_bboxes[track_id], det['box'])
            
            while iou_matrix.max() > self.iou_threshold:
                t, d = np.unravel_index(np.argmax(iou_matrix), iou_matrix.shape)
                matched_pairs.append((track_ids[t], d))
                if d in unmatched_detections:
                    unmatched_detections.remove(d)
                iou_matrix[t, :] = -1
                iou_matrix[:, d] = -1

        # 3. 업데이트 단계
        # 매칭된 객체 업데이트 (case_type 포함)
        for track_id, det_idx in matched_pairs:
            det = new_detections[det_idx]
            self.tracked_objects[track_id].update(det['box'], det.get('confidence', 0.9), det.get('case', 'unknown'))

        # 매칭되지 않은 새로운 객체 생성 (case_type 포함)
        for det_idx in unmatched_detections:
            det = new_detections[det_idx]
            new_tracker = TrackedObject(det['box'], det['label'], det.get('confidence', 0.9), det.get('case', 'unknown'))
            self.tracked_objects[new_tracker.id] = new_tracker

        # 4. 최종 결과 생성
        # 현재 유효한 추적 객체 목록을 생성하여 반환 (case_type 포함)
        final_detections = []
        for track_id, tracker in self.tracked_objects.items():
            if tracker.missed_frames < 2:
                final_detections.append({
                    'track_id': track_id,
                    'label': tracker.label,
                    'case': tracker.case_type,
                    'box': convert_x_to_bbox(tracker.kf.x).tolist(),
                    'confidence': tracker.confidence
                })
        return final_detections

    def _cleanup_tracks(self):
        """ 오래 추적되지 않은(missed_frames가 임계값을 초과한) 객체를 제거. """
        dead_tracks = [tid for tid, t in self.tracked_objects.items() if t.missed_frames > self.max_missed_frames]
        for tid in dead_tracks:
            del self.tracked_objects[tid]

    def _draw_detections_and_get_frame(self, jpeg_binary, detections):
        """ 추적된 객체들을 이미지에 그리고, case_type에 따라 다른 색상의 바운딩 박스를 적용. """
        try:
            np_arr = np.frombuffer(jpeg_binary, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None: return None

            if detections:
                for det in detections:
                    box = det.get('box')
                    case_type = det.get('case', 'unknown')
                    if not box or len(box) != 4: continue
                    x1, y1, x2, y2 = map(int, box)

                    # case_type에 따라 바운딩 박스 색상 결정
                    color = (0, 255, 0)  # default: green (emergency)
                    if case_type == 'danger': color = (0, 0, 255)  # red
                    elif case_type == 'illegal': color = (255, 0, 0)  # blue

                    label = det.get('label', 'unknown')
                    confidence = det.get('confidence', 0.0)
                    text = f"{det.get('track_id')} {label}: {confidence:.2f}"

                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(frame, text, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            return frame
        except Exception as e:
            print(f"[{self.name}] 이미지 드로잉 오류: {e}")
            return None

    def _process_unmerged_frame(self, frame_id, timestamp, jpeg_binary, current_state):
        """AI 분석 결과 없이 이미지만 있는 프레임을 처리 (녹화 및 GUI 전송)."""
        if current_state in ['patrolling', 'detected'] and self.is_recording:
            np_arr = np.frombuffer(jpeg_binary, np.uint8)
            raw_frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if raw_frame is not None:
                self._handle_recording(raw_frame)
        
        if self.gui_send_queue.full(): return
        image_only_json = {
            "frame_id": frame_id,
            "timestamp": timestamp,
            "detections": [],
            "robot_status": current_state,
            "location": self.robot_status.get('current_location', 'BASE')
        }
        self.gui_send_queue.put((image_only_json, jpeg_binary))

    def _handle_recording(self, frame):
        """주어진 프레임에 대해 녹화 시작 또는 프레임 쓰기를 수행."""
        current_state = self.robot_status.get('state')
        if current_state == 'detected':
            if not self.is_recording:
                self._start_recording(frame)
            if self.video_writer:
                self.video_writer.write(frame)
    
    def _start_recording(self, first_frame):
        """첫 프레임을 받아 녹화를 시작하고 임시 썸네일과 비디오 파일을 생성."""
        print(f"[{self.name}] 상태 'detected' 감지. 임시 파일로 녹화 시작.")
        self.is_recording = True
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.temp_img_path = os.path.join(self.base_dir, 'images', f"temp_{timestamp_str}.jpg")
        self.temp_video_path = os.path.join(self.base_dir, 'videos', f"temp_{timestamp_str}.mp4")

        try:
            h, w, _ = first_frame.shape
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.video_writer = cv2.VideoWriter(self.temp_video_path, fourcc, 20.0, (w, h))
            cv2.imwrite(self.temp_img_path, first_frame)
            self.video_writer.write(first_frame)
        except Exception as e:
            print(f"[{self.name}] 녹화 시작 오류: {e}")
            self.is_recording = False

    def _stop_recording(self, stop_signal: dict):
        """녹화를 중지하고, DBManager로부터 받은 최종 파일명으로 임시 파일의 이름을 변경."""
        final_img_path = stop_signal.get('final_image_path')
        final_video_path = stop_signal.get('final_video_path')
        print(f"[{self.name}] 녹화 종료 신호 수신. 최종 파일명: {final_video_path}")
        
        self.is_recording = False
        if self.video_writer:
            self.video_writer.release()
            print(f"[{self.name}] 임시 비디오 파일 저장 완료: {self.temp_video_path}")

        try:
            # 임시 이미지 파일 이름 변경
            if self.temp_img_path and os.path.exists(self.temp_img_path) and final_img_path:
                final_full_path = os.path.join(self.base_dir, final_img_path)
                os.rename(self.temp_img_path, final_full_path)
                print(f"[{self.name}] 최종 이미지 파일 저장: {final_full_path}")
            # 임시 비디오 파일 이름 변경
            if self.temp_video_path and os.path.exists(self.temp_video_path) and final_video_path:
                final_full_path = os.path.join(self.base_dir, final_video_path)
                os.rename(self.temp_video_path, final_full_path)
                print(f"[{self.name}] 최종 비디오 파일 저장: {final_full_path}")
        except Exception as e:
            print(f"[{self.name}] 파일 이름 변경 중 오류: {e}")
        
        self.video_writer = None
        self.temp_img_path = None
        self.temp_video_path = None

    def stop(self):
        """스레드를 안전하게 종료."""
        print(f"\n[{self.name}] 종료 요청 수신.")
        self.running = False
        if self.gui_client_socket: self.gui_client_socket.close()
        if self.gui_server_socket: self.gui_server_socket.close()