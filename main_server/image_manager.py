# main_server/image_manager.py (디버깅 로그 복원 완료)

import socket
import threading
import queue
import json
import pickle
import cv2
import numpy as np
import os
from datetime import datetime

class ImageManager(threading.Thread):
    def __init__(self, listen_port, ai_server_addr, image_for_merger_queue, robot_status, aruco_result_queue):
        super().__init__()
        self.name = "ImageManager"
        self.running = True

        self.robot_status = robot_status
        self.aruco_result_queue = aruco_result_queue
        self.image_for_merger_queue = image_for_merger_queue

        self.ai_server_addr = ai_server_addr
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.bind(('0.0.0.0', listen_port))
        self.udp_socket.settimeout(1.0)
        print(f"[{self.name}] 로봇 이미지 수신 대기 중... (Port: {listen_port})")

        self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_250)
        self.aruco_params = cv2.aruco.DetectorParameters()
        self.aruco_detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.aruco_params)

        calibration_file_path = 'shared/camera_calibration.pkl'
        self.camera_matrix, self.dist_coeffs = self._load_calibration_data(calibration_file_path)
        if self.camera_matrix is None or self.dist_coeffs is None:
            print(f"[{self.name}] 치명적 오류: 카메라 보정 파일 로드 실패.")
            self.running = False

        self.is_recording = False
        self.video_writer = None
        self.temp_img_path = None
        self.temp_video_path = None
        self.base_dir = 'main_server'
        os.makedirs(os.path.join(self.base_dir, 'images'), exist_ok=True)
        os.makedirs(os.path.join(self.base_dir, 'videos'), exist_ok=True)
        print(f"[{self.name}] 녹화 기능 초기화. 저장 폴더: {self.base_dir}/(images, videos)")

    def _load_calibration_data(self, pkl_path):
        try:
            with open(pkl_path, 'rb') as f:
                data = pickle.load(f)
                return np.array(data['camera_matrix']), np.array(data['dist_coeffs'])
        except Exception as e:
            print(f"[{self.name}] 보정 파일 로드 오류: {e}")
            return None, None

    def _parse_udp_packet(self, data):
        try:
            delimiter_pos = data.find(b'|')
            if delimiter_pos == -1: return None, None
            header_bytes = data[:delimiter_pos]
            image_binary = data[delimiter_pos+1:].rstrip(b'\n')
            header_json = json.loads(header_bytes.decode('utf-8'))
            return header_json, image_binary
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None, None

    def run(self):
        if not self.running: return
        print(f"[{self.name}] 스레드 시작.")

        while self.running:
            stop_signal = self.robot_status.get('recording_stop_signal')
            if self.is_recording and stop_signal is not None:
                self._stop_recording(stop_signal)
                self.robot_status['recording_stop_signal'] = None

            try:
                data, addr = self.udp_socket.recvfrom(65535)
                header_json, image_binary = self._parse_udp_packet(data)
                if not header_json: continue

                frame_id = header_json.get('frame_id')
                timestamp = header_json.get('timestamp')

                # [수정] 사용자 요청에 따라 상세 디버깅 로그 복원
                print("-----------------------------------------------------")
                print(f"[✅ UDP 수신] 1. Robot -> {self.name}: frame_id={frame_id}, timestamp={timestamp}, size={len(data)} bytes")

                current_state = self.robot_status.get('state', 'idle')

                if current_state == 'detected':
                    if not self.is_recording:
                        self._start_recording()
                    if self.is_recording:
                        self._write_frame(image_binary)
                
                if current_state == 'idle':
                    print(f"[➡️ 큐 입력] 2a. {self.name} -> DataMerger: (idle) frame_id={frame_id}")
                    self.image_for_merger_queue.put((frame_id, timestamp, image_binary))
                elif current_state == 'moving':
                    self._process_aruco_mode(header_json, image_binary)
                elif current_state in ['patrolling', 'detected']:
                    self._process_patrolling_mode(data, header_json, image_binary)

            except socket.timeout:
                continue
            except Exception as e:
                print(f"[{self.name}] UDP 수신/처리 오류: {e}")

        if self.is_recording:
            shutdown_paths = {'final_image_path': 'images/shutdown.jpg', 'final_video_path': 'videos/shutdown.mp4'}
            self._stop_recording(shutdown_paths)
        print(f"[{self.name}] 스레드 종료.")

    def _process_aruco_mode(self, header_json, image_binary):
        frame_id = header_json.get('frame_id')
        timestamp = header_json.get('timestamp')
        try:
            image_np = np.frombuffer(image_binary, dtype=np.uint8)
            frame = cv2.imdecode(image_np, cv2.IMREAD_COLOR)
            corners, ids, _ = self.aruco_detector.detectMarkers(frame)

            if ids is not None:
                rvecs, tvecs, _ = cv2.aruco.estimatePoseSingleMarkers(corners, 0.05, self.camera_matrix, self.dist_coeffs)
                for i, marker_id in enumerate(ids):
                    distance_z = tvecs[i][0][2]
                    aruco_result = {'id': int(marker_id[0]), 'distance': distance_z}
                    
                    print(f"[➡️ 큐 입력] 2b-1. {self.name} -> RobotCommander: (moving) ArUco id={aruco_result['id']}, dist={distance_z:.2f}")
                    self.aruco_result_queue.put(aruco_result)
                    
                    cv2.aruco.drawDetectedMarkers(frame, corners, ids)
                    top_left = corners[i][0][0]
                    cv2.putText(frame, f"Dist: {distance_z:.2f}m", (int(top_left[0]), int(top_left[1]) - 15),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            _, annotated_image_binary = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            print(f"[➡️ 큐 입력] 2b-2. {self.name} -> DataMerger: (moving) frame_id={frame_id} (annotated)")
            self.image_for_merger_queue.put((frame_id, timestamp, annotated_image_binary.tobytes()))
        except Exception as e:
            print(f"[{self.name}] ArUco 처리 오류: {e}")

    def _process_patrolling_mode(self, original_data, header_json, image_binary):
        frame_id = header_json.get('frame_id')
        timestamp = header_json.get('timestamp')
        try:
            print(f"[✈️ UDP 전송] 2c-1. {self.name} -> AI_Server: (patrolling/detected) frame_id={frame_id}")
            self.udp_socket.sendto(original_data, self.ai_server_addr)

            print(f"[➡️ 큐 입력] 2c-2. {self.name} -> DataMerger: (patrolling/detected) frame_id={frame_id}")
            self.image_for_merger_queue.put((frame_id, timestamp, image_binary))
        except Exception as e:
            print(f"[{self.name}] 패트롤링 데이터 전송 오류: {e}")

    def _start_recording(self):
        print(f"[{self.name}] 상태 'detected' 감지. 임시 파일로 녹화 시작.")
        self.is_recording = True
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.temp_img_path = os.path.join(self.base_dir, 'images', f"temp_{timestamp_str}.jpg")
        self.temp_video_path = os.path.join(self.base_dir, 'videos', f"temp_{timestamp_str}.mp4")

    def _write_frame(self, jpeg_binary):
        try:
            np_arr = np.frombuffer(jpeg_binary, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None: return

            if self.video_writer is None:
                h, w, _ = frame.shape
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                self.video_writer = cv2.VideoWriter(self.temp_video_path, fourcc, 20.0, (w, h))
                cv2.imwrite(self.temp_img_path, frame)
                print(f"[{self.name}] 첫 프레임 임시 이미지 저장: {self.temp_img_path}")

            self.video_writer.write(frame)
        except Exception as e:
            print(f"[{self.name}] 프레임 쓰기 오류: {e}")
            self.is_recording = False

    def _stop_recording(self, stop_signal: dict):
        final_img_path = stop_signal.get('final_image_path')
        final_video_path = stop_signal.get('final_video_path')
        print(f"[{self.name}] 녹화 종료 신호 수신. 최종 파일명: {final_video_path}")
        
        if self.video_writer:
            self.video_writer.release()
            print(f"[{self.name}] 임시 비디오 파일 저장 완료: {self.temp_video_path}")

        try:
            if self.temp_img_path and os.path.exists(self.temp_img_path) and final_img_path:
                os.rename(self.temp_img_path, os.path.join(self.base_dir, final_img_path))
                print(f"[{self.name}] 최종 이미지 파일 저장: {os.path.join(self.base_dir, final_img_path)}")
            
            if self.temp_video_path and os.path.exists(self.temp_video_path) and final_video_path:
                os.rename(self.temp_video_path, os.path.join(self.base_dir, final_video_path))
                print(f"[{self.name}] 최종 비디오 파일 저장: {os.path.join(self.base_dir, final_video_path)}")
        except Exception as e:
            print(f"[{self.name}] 파일 이름 변경 중 오류: {e}")
        
        self.is_recording = False
        self.video_writer = None
        self.temp_img_path = None
        self.temp_video_path = None

    def stop(self):
        self.running = False
        self.udp_socket.close()
        print(f"\n[{self.name}] 종료 요청 수신.")