# main_server/data_merger.py (녹화 기능이 추가된 최종 버전)

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

class DataMerger(threading.Thread):
    """
    ImageManager로부터 이미지 데이터를, EventAnalyzer로부터 AI 분석 결과를 받아
    하나의 데이터로 병합합니다.
    - 병합된 데이터(JSON + 이미지)를 GUI로 전송합니다.
    - 'detected' 상태가 되면 Bounding Box가 그려진 영상을 파일로 녹화하고 저장합니다.
    - DBManager로부터 녹화 종료 신호를 받아 파일명을 최종적으로 변경합니다.
    """
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

        # --- 녹화 기능 관련 변수 추가 ---
        self.is_recording = False
        self.video_writer = None
        self.temp_img_path = None
        self.temp_video_path = None
        self.base_dir = 'main_server'
        os.makedirs(os.path.join(self.base_dir, 'images'), exist_ok=True)
        os.makedirs(os.path.join(self.base_dir, 'videos'), exist_ok=True)
        
        print(f"[{self.name}] 초기화 완료. GUI 연결 대기 주소: {self.gui_listen_addr}")
        print(f"[{self.name}] 녹화 기능 초기화 완료. 저장 폴더: {self.base_dir}/(images, videos)")


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
        """
        데이터를 병합하고, 상태에 따라 녹화를 수행하는 메인 처리 스레드.
        """
        while self.running:
            # DBManager로부터 오는 녹화 종료 신호 확인
            stop_signal = self.robot_status.get('recording_stop_signal')
            if self.is_recording and stop_signal:
                self._stop_recording(stop_signal)
                self.robot_status['recording_stop_signal'] = None # 신호 처리 후 초기화

            processed_ids = set()
            with self.buffer_lock:
                # 1. 병합 (AI 결과 + 이미지)
                common_ids = self.image_buffer.keys() & self.event_buffer.keys()
                for fid in common_ids:
                    jpeg_binary, timestamp, _ = self.image_buffer[fid]
                    event_data, _ = self.event_buffer[fid]
                    
                    self._process_merged_frame(fid, timestamp, jpeg_binary, event_data)
                    processed_ids.add(fid)

                # 2. 타임아웃된 이미지 단독 처리 (순찰/탐지 상태 제외)
                # 부드러운 영상 저장을 위해 녹화 중일때는 이 로직도 녹화에 포함
                current_state = self.robot_status.get('state', 'idle')
                timeout = timedelta(seconds=0.1) if current_state not in ['patrolling', 'detected'] else timedelta(seconds=2.0)
                now = datetime.now()
                old_image_ids = {fid for fid, (_, _, ts) in self.image_buffer.items() if now - ts > timeout}

                for fid in old_image_ids:
                    if fid in processed_ids: continue
                    jpeg_binary, timestamp, _ = self.image_buffer[fid]

                    # 병합되지 않은 프레임 처리 (AI 결과 없음)
                    self._process_unmerged_frame(fid, timestamp, jpeg_binary, current_state)
                    processed_ids.add(fid)
                
                # 3. 버퍼 정리
                event_cleanup_timeout = timedelta(seconds=2.0)
                old_event_ids = {fid for fid, (_, ts) in self.event_buffer.items() if now - ts > event_cleanup_timeout}
                processed_ids.update(old_event_ids)

                for fid in processed_ids:
                    self.image_buffer.pop(fid, None)
                    self.event_buffer.pop(fid, None)

            time.sleep(0.03)

    def _process_merged_frame(self, frame_id, timestamp, jpeg_binary, event_data):
        """AI 분석 결과와 병합된 프레임을 처리 (녹화 및 GUI 전송)"""
        detections = event_data.get('detections', [])
        # Bounding Box가 그려진 OpenCV 프레임 객체를 받음
        annotated_frame = self._draw_detections_and_get_frame(jpeg_binary, detections)
        if annotated_frame is None: return

        # 녹화 로직
        self._handle_recording(annotated_frame)
        
        # GUI 전송 준비
        if self.gui_send_queue.full(): return
        _, annotated_jpeg_binary = cv2.imencode('.jpg', annotated_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])

        merged_json = {
            "frame_id": frame_id,
            "timestamp": timestamp,
            "detections": detections,
            "robot_status": self.robot_status.get('state', 'detected'),
            "location": self.robot_status.get('current_location', 'unknown')
        }
        self.gui_send_queue.put((merged_json, annotated_jpeg_binary.tobytes()))

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
    
    def _draw_detections_and_get_frame(self, jpeg_binary, detections):
        """JPEG 바이너리를 디코드하고 Bounding Box를 그린 뒤, OpenCV 프레임 객체를 반환"""
        try:
            np_arr = np.frombuffer(jpeg_binary, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None: return None

            if detections:
                for det in detections:
                    box = det.get('box')
                    if not box or len(box) != 4: continue
                    x1, y1, x2, y2 = map(int, box)
                    label = det.get('label', 'unknown')
                    text = f"{label}: {det.get('confidence', 0.0):.2f}"
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                    cv2.putText(frame, text, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
            
            return frame
        except Exception as e:
            print(f"[{self.name}] 이미지 드로잉 오류: {e}")
            return None

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