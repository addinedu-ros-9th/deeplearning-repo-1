# main_server/data_merger.py (case_type 처리 기능이 수정된 최종 버전)

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

from filterpy.kalman import KalmanFilter
from filterpy.common import Q_discrete_white_noise

# --- 유틸리티 함수 (기존과 동일) ---
def iou(boxA, boxB):
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])
    interArea = max(0, xB - xA) * max(0, yB - yA)
    boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    return interArea / float(boxAArea + boxBArea - interArea)

def convert_bbox_to_z(bbox):
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = bbox[0] + w / 2.
    y = bbox[1] + h / 2.
    return np.array([x, y, w, h]).reshape(4, 1)

def convert_x_to_bbox(x):
    w = x[2]
    h = x[3]
    return np.array([x[0] - w / 2., x[1] - h / 2., x[0] + w / 2., x[1] + h / 2.]).flatten()


# 1. TrackedObject 클래스 수정
class TrackedObject:
    """ 추적되는 각 객체의 정보를 담는 클래스 """
    next_id = 0
    # ✨ [수정 1] __init__ 메소드에 case_type 파라미터 추가
    def __init__(self, initial_bbox, label, confidence, case_type):
        self.id = TrackedObject.next_id
        TrackedObject.next_id += 1
        
        self.label = label
        self.confidence = confidence
        self.case_type = case_type  # ✨ case_type 저장
        self.last_updated = time.time()
        self.missed_frames = 0
        
        # --- 칼만 필터 설정 (상수 속도 모델) ---
        self.kf = KalmanFilter(dim_x=8, dim_z=4)
        dt = 1.0
        self.kf.F = np.array([[1,0,0,0,dt,0,0,0], 
                              [0,1,0,0,0,dt,0,0], 
                              [0,0,1,0,0,0,dt,0], 
                              [0,0,0,1,0,0,0,dt],
                              [0,0,0,0,1,0,0,0], 
                              [0,0,0,0,0,1,0,0], 
                              [0,0,0,0,0,0,1,0], 
                              [0,0,0,0,0,0,0,1]], dtype=float)
        self.kf.H = np.array([[1,0,0,0,0,0,0,0], 
                              [0,1,0,0,0,0,0,0], 
                              [0,0,1,0,0,0,0,0], 
                              [0,0,0,1,0,0,0,0]], dtype=float)
        # [튜닝 포인트 1] 측정 노이즈 (R)
        # AI 탐지 결과를 얼마나 신뢰할지 결정합니다.
        # - 값을 '낮추면': AI 탐지 결과를 더 신뢰하게 되어, 객체가 갑자기 크게 움직여도 필터가 빠르게 따라갑니다. (단, 탐지 결과가 불안정하면 트랙이 튈 수 있음)
        # - 값을 '높이면': 예측값을 더 신뢰하게 되어, 추적이 더 부드러워집니다. (기본값)
        self.kf.R *= 5.  # 현재 값. 아주 빠른 추적을 원하면 1. ~ 5. 사이로 낮춰보세요.
        # [튜닝 포인트 2] 프로세스 노이즈 (Q)
        # 객체의 움직임(가속도)이 얼마나 불확실한지 결정합니다. 이 값이 가장 중요합니다.
        # - 값을 '높이면': 객체의 속도가 갑자기 변할 것이라고 가정하므로, 매우 빠른 움직임이나 방향 전환에 더 잘 반응합니다.
        # - 값을 '낮추면': 객체가 등속도로 움직일 것이라고 가정하므로, 움직임이 부드러워집니다.
        q_val = 0.1  # 현재 값. 아주 빠른 추적을 원하면 이 값을 1.0, 5.0, 10.0 등으로 점차 높여보세요.
        
        self.kf.Q = Q_discrete_white_noise(dim=2, dt=1.0, var=q_val, block_size=4, order_by_dim=False)
        
        self.kf.P *= 100.
        initial_state = convert_bbox_to_z(initial_bbox).flatten()
        self.kf.x = np.array([initial_state[0], initial_state[1], initial_state[2], initial_state[3], 0, 0, 0, 0]).T

    def predict(self):
        self.confidence *= 0.95 
        self.kf.predict()
        return self.kf.x
    
    # ✨ [수정 2] update 메소드에 case_type 파라미터 추가 (필요시 사용)
    def update(self, bbox, confidence, case_type):
        self.kf.update(convert_bbox_to_z(bbox))
        self.confidence = confidence
        self.case_type = case_type # case_type도 업데이트
        self.last_updated = time.time()
        self.missed_frames = 0


class DataMerger(threading.Thread):
    def __init__(self, image_queue, event_queue, gui_listen_addr, robot_status):
        super().__init__()
        self.name = "DataMerger"
        self.running = True
        self.image_queue = image_queue
        self.event_queue = event_queue
        self.gui_send_queue = queue.Queue(maxsize=100)
        self.robot_status = robot_status
        self.image_buffer = {}
        self.event_buffer = {}
        self.buffer_lock = threading.Lock()
        self.gui_listen_addr = gui_listen_addr
        self.gui_server_socket = None
        self.gui_client_socket = None
        self.tracked_objects = {}
        self.iou_threshold = 0.3
        self.max_missed_frames = 10
        self.is_recording = False
        self.video_writer = None
        self.temp_img_path = None
        self.temp_video_path = None
        self.base_dir = 'main_server'
        os.makedirs(os.path.join(self.base_dir, 'images'), exist_ok=True)
        os.makedirs(os.path.join(self.base_dir, 'videos'), exist_ok=True)
        print(f"[{self.name}] 초기화 완료 (객체 추적 칼만 필터 적용).")

    # --- run, _gui_... 쓰레드, _process_... 프레임 관련 메소드 등은 기존과 동일 ---
    # ... (기존 코드 생략) ...
    def run(self):
        print(f"[{self.name}] 스레드 시작.")
        threads = [
            threading.Thread(target=self._gui_accept_thread, daemon=True),
            threading.Thread(target=self._gui_send_thread, daemon=True),
            threading.Thread(target=self._image_receive_thread, daemon=True),
            threading.Thread(target=self._event_receive_thread, daemon=True),
            threading.Thread(target=self._merge_and_record_thread, daemon=True) # 메인 로직 스레드
        ]
        for t in threads: t.start()
        
        # 메인 스레드는 여기서 모든 자식 스레드가 끝날 때까지 대기
        for t in threads: t.join() 
        
        print(f"[{self.name}] 스레드 종료.")

    # --- 기존 _gui_accept_thread, _gui_send_thread, _image_receive_thread, _event_receive_thread 코드는 변경 없음 ---
    # (생략)
    def _gui_accept_thread(self):
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
        while self.running:
            try:
                frame_id, timestamp, jpeg_binary = self.image_queue.get(timeout=1)
                print(f"[⬅️ 큐 출력] 5a. {self.name} <- ImageManager: Image for frame_id={frame_id}, timestamp={timestamp}")
                with self.buffer_lock:
                    self.image_buffer[frame_id] = (jpeg_binary, timestamp, datetime.now())
            except queue.Empty:
                continue

    def _event_receive_thread(self):
        while self.running:
            try:
                event_data = self.event_queue.get(timeout=1)
                frame_id = event_data['frame_id']
                timestamp = event_data.get('timestamp')
                print(f"[⬅️ 큐 출력] 5b. {self.name} <- EventAnalyzer: Event for frame_id={frame_id}, timestamp={timestamp}")
                with self.buffer_lock:
                    self.event_buffer[frame_id] = (event_data, datetime.now())
            except queue.Empty:
                continue

    def _gui_send_thread(self):
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

                frame_id = json_data.get('frame_id')
                timestamp = json_data.get('timestamp')
                state = json_data.get('robot_status')
                print(f"[✈️ GUI 전송] 7. {self.name} -> GUI: frame_id={frame_id}, timestamp={timestamp}, state={state}, size={len(header)+len(payload)}")

            except queue.Empty:
                continue
            except (BrokenPipeError, ConnectionResetError, socket.error) as e:
                print(f"[{self.name}] GUI 연결 끊어짐: {e}.")
                if self.gui_client_socket: self.gui_client_socket.close()
                self.gui_client_socket = None
    # --- 여기까지 변경 없음 ---


    def _merge_and_record_thread(self):
        """ 데이터를 병합하고, 상태에 따라 녹화 및 객체 추적을 수행하는 메인 스레드 """
        while self.running:
            stop_signal = self.robot_status.get('recording_stop_signal')
            if self.is_recording and stop_signal:
                self._stop_recording(stop_signal)
                self.robot_status['recording_stop_signal'] = None
                
            processed_ids = set()
            with self.buffer_lock:
                common_ids = self.image_buffer.keys() & self.event_buffer.keys()
                for fid in common_ids:
                    if fid not in self.image_buffer or fid not in self.event_buffer: continue
                    jpeg_binary, timestamp, _ = self.image_buffer[fid]
                    event_data, _ = self.event_buffer[fid]
                    self._process_merged_frame(fid, timestamp, jpeg_binary, event_data)
                    processed_ids.add(fid)

                timeout = timedelta(seconds=0.4)
                now = datetime.now()
                old_image_ids = {fid for fid, (_, _, ts) in self.image_buffer.items() if now - ts > timeout}
                for fid in old_image_ids:
                    if fid in processed_ids: continue
                    if fid not in self.image_buffer: continue
                    jpeg_binary, timestamp, _ = self.image_buffer[fid]
                    current_state = self.robot_status.get('state', 'idle')
                    self._process_unmerged_frame(fid, timestamp, jpeg_binary, current_state)
                    processed_ids.add(fid)
                    
                for fid in processed_ids:
                    self.image_buffer.pop(fid, None)
                    self.event_buffer.pop(fid, None)

            # --- 오래된 추적 객체 제거 ---
            self._cleanup_tracks()
            time.sleep(0.03)

    def _process_merged_frame(self, frame_id, timestamp, jpeg_binary, event_data):
        """ AI 분석 결과와 병합된 프레임을 처리 (객체 추적, 녹화, GUI 전송) """
        raw_detections = event_data.get('detections', [])
        
        # --- 칼만 필터 기반 객체 추적 수행 ---
        filtered_detections = self._update_tracks(raw_detections)

        annotated_frame = self._draw_detections_and_get_frame(jpeg_binary, filtered_detections)
        if annotated_frame is None: return

        self._handle_recording(annotated_frame)
        
        if self.gui_send_queue.full(): return
        _, annotated_jpeg_binary = cv2.imencode('.jpg', annotated_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])

        merged_json = {
            "frame_id": frame_id,
            "timestamp": timestamp,
            "detections": filtered_detections, # 필터링된 탐지 결과 전송
            "robot_status": self.robot_status.get('state', 'detected'),
            "location": self.robot_status.get('current_location', 'unknown')
        }
        self.gui_send_queue.put((merged_json, annotated_jpeg_binary.tobytes()))
    def _update_tracks(self, new_detections):
        # ... (기존 예측, 매칭 단계는 동일) ...
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
            
            # 가장 IoU가 높은 쌍부터 매칭
            while iou_matrix.max() > self.iou_threshold:
                t, d = np.unravel_index(np.argmax(iou_matrix), iou_matrix.shape)
                matched_pairs.append((track_ids[t], d))
                if d in unmatched_detections:
                    unmatched_detections.remove(d)
                iou_matrix[t, :] = -1
                iou_matrix[:, d] = -1

        # 3. 업데이트 단계
        # ✨ [수정 3] 매칭된 객체 업데이트 시 case_type도 전달
        for track_id, det_idx in matched_pairs:
            det = new_detections[det_idx]
            self.tracked_objects[track_id].update(
                det['box'],
                det.get('confidence', 0.9),
                det.get('case', 'unknown') # case_type 전달
            )

        # ✨ [수정 4] 새로운 객체 생성 시 case_type도 전달
        for det_idx in unmatched_detections:
            det = new_detections[det_idx]
            new_tracker = TrackedObject(
                det['box'],
                det['label'],
                det.get('confidence', 0.9),
                det.get('case', 'unknown') # case_type 전달
            )
            self.tracked_objects[new_tracker.id] = new_tracker
            print(f"[{self.name}] 새로운 객체 추적 시작: ID {new_tracker.id} ({det['label']})")

        # ✨ [수정 5] 최종 결과 생성 시 case_type 포함
        final_detections = []
        for track_id, tracker in self.tracked_objects.items():
            if tracker.missed_frames < 2:
                final_detections.append({
                    'track_id': track_id,
                    'label': tracker.label,
                    'case': tracker.case_type, # case_type 포함
                    'box': convert_x_to_bbox(tracker.kf.x).tolist(),
                    'confidence': tracker.confidence
                })
        return final_detections
    def _cleanup_tracks(self):
        """ 오래 추적되지 않은 객체를 제거합니다. """
        dead_tracks = [tid for tid, t in self.tracked_objects.items() if t.missed_frames > self.max_missed_frames]
        for tid in dead_tracks:
            print(f"[{self.name}] 객체 추적 종료: ID {tid} ({self.tracked_objects[tid].label})")
            del self.tracked_objects[tid]

    def _draw_detections_and_get_frame(self, jpeg_binary, detections):
        """ JPEG 바이너리를 디코드하고 Bounding Box와 추적 ID 및 case type에 따라 색상을 입힌 뒤, OpenCV 프레임 객체를 반환 """
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

                    color = (0, 255, 0)  # 기본 초록색 (emergency)
                    if case_type == 'danger':
                        color = (0, 0, 255)  # 빨간색
                    elif case_type == 'illegal':
                        color = (255, 0, 0)  # 파란색

                    # 추적 ID, 레이블 및 신뢰도 표시
                    label = det.get('label', 'unknown')
                    confidence = det.get('confidence', 0.0)
                    text = f"{label}: {confidence:.2f}"

                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(frame, text, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

            return frame
        except Exception as e:
            print(f"[{self.name}] 이미지 드로잉 오류: {e}")
            return None

    def _process_unmerged_frame(self, frame_id, timestamp, jpeg_binary, current_state):
        """병합되지 않은 프레임 처리 (녹화 및 GUI 전송)"""
        if current_state in ['patrolling', 'detected'] and self.is_recording:
             # 녹화 중일 때는 AI 결과가 없더라도 프레임을 디코딩하여 녹화
            np_arr = np.frombuffer(jpeg_binary, np.uint8)
            raw_frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if raw_frame is not None:
                self._handle_recording(raw_frame)
        
        # GUI 전송 준비
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
        """주어진 프레임에 대해 녹화 시작 또는 프레임 쓰기를 수행"""
        current_state = self.robot_status.get('state')
        if current_state == 'detected':
            if not self.is_recording:
                self._start_recording(frame)
            
            if self.video_writer:
                self.video_writer.write(frame)
    
    def _start_recording(self, first_frame):
        """첫 프레임을 받아 녹화를 시작하고 임시 썸네일을 저장"""
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
            print(f"[{self.name}] 첫 프레임 임시 이미지 저장: {self.temp_img_path}")
            # 첫 프레임도 비디오에 쓰기
            self.video_writer.write(first_frame)

        except Exception as e:
            print(f"[{self.name}] 녹화 시작 오류: {e}")
            self.is_recording = False

    def _stop_recording(self, stop_signal: dict):
        """녹화를 중지하고 임시 파일의 이름을 최종 파일명으로 변경"""
        final_img_path = stop_signal.get('final_image_path')
        final_video_path = stop_signal.get('final_video_path')
        print(f"[{self.name}] 녹화 종료 신호 수신. 최종 파일명: {final_video_path}")
        
        self.is_recording = False
        if self.video_writer:
            self.video_writer.release()
            print(f"[{self.name}] 임시 비디오 파일 저장 완료: {self.temp_video_path}")

        try:
            if self.temp_img_path and os.path.exists(self.temp_img_path) and final_img_path:
                final_full_path = os.path.join(self.base_dir, final_img_path)
                os.rename(self.temp_img_path, final_full_path)
                print(f"[{self.name}] 최종 이미지 파일 저장: {final_full_path}")
            
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
        """스레드를 안전하게 종료"""
        print(f"\n[{self.name}] 종료 요청 수신.")
        self.running = False
        if self.gui_client_socket: self.gui_client_socket.close()
        if self.gui_server_socket: self.gui_server_socket.close()