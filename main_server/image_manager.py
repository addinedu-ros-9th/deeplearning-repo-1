# main_server/image_manager.py (녹화 기능이 DataMerger로 이전된 버전)

import socket
import threading
import queue
import json
import pickle
import cv2
import numpy as np

class ImageManager(threading.Thread):
    """
    로봇으로부터 영상 프레임을 UDP로 수신하여 시스템의 현재 상태('state')에 따라
    AI 서버로 전달하거나 DataMerger로 직접 보내는 역할을 담당합니다.
    - 'moving' 상태: ArUco 마커를 탐지하여 RobotCommander로 거리 정보를 전송합니다.
    - 'patrolling'/'detected' 상태: AI 서버로 이미지를 전달하여 분석을 요청합니다.
    - 'idle' 상태: 이미지를 DataMerger로 바로 전달하여 GUI에 표시합니다.
    
    [변경 사항]
    - Bounding Box가 그려진 영상을 저장하기 위해, 기존에 있던 녹화(VideoWriter) 및
      파일 저장 관련 기능은 모두 DataMerger 클래스로 이전되었습니다.
    - 이에 따라 ImageManager는 더 이상 파일 시스템에 직접 접근하지 않으며,
      오직 데이터 수신 및 전달의 역할만 수행하여 책임과 역할이 명확해졌습니다.
    """
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

        # ArUco 마커 탐지 관련 설정
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_250)
        self.aruco_params = cv2.aruco.DetectorParameters()
        self.aruco_detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.aruco_params)

        # 카메라 캘리브레이션 데이터 로드
        calibration_file_path = 'shared/camera_calibration.pkl'
        self.camera_matrix, self.dist_coeffs = self._load_calibration_data(calibration_file_path)
        if self.camera_matrix is None or self.dist_coeffs is None:
            print(f"[{self.name}] 치명적 오류: 카메라 보정 파일 로드 실패.")
            self.running = False
        
        print(f"[{self.name}] 초기화 완료.")

    def _load_calibration_data(self, pkl_path):
        """카메라 캘리브레이션 데이터를 pkl 파일에서 로드합니다."""
        try:
            with open(pkl_path, 'rb') as f:
                data = pickle.load(f)
                return np.array(data['camera_matrix']), np.array(data['dist_coeffs'])
        except Exception as e:
            print(f"[{self.name}] 보정 파일 로드 오류: {e}")
            return None, None

    def _parse_udp_packet(self, data):
        """수신한 UDP 패킷을 JSON 헤더와 이미지 바이너리로 분리합니다."""
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
            try:
                data, addr = self.udp_socket.recvfrom(65535)
                header_json, image_binary = self._parse_udp_packet(data)
                if not header_json: continue

                frame_id = header_json.get('frame_id')
                timestamp = header_json.get('timestamp')

                print("-----------------------------------------------------")
                print(f"[✅ UDP 수신] 1. Robot -> {self.name}: frame_id={frame_id}, timestamp={timestamp}, size={len(data)} bytes")

                current_state = self.robot_status.get('state', 'idle')

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

        print(f"[{self.name}] 스레드 종료.")

    def _process_aruco_mode(self, header_json, image_binary):
        """'moving' 상태일 때 ArUco 마커를 탐지하고 거리 정보를 전송합니다."""
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
                    
                    # GUI 표시용으로 마커가 그려진 이미지를 생성
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
        """'patrolling' 또는 'detected' 상태일 때 이미지를 AI 서버와 DataMerger로 전송합니다."""
        frame_id = header_json.get('frame_id')
        timestamp = header_json.get('timestamp')
        try:
            # 1. AI 서버로 전체 UDP 패킷 전달
            print(f"[✈️ UDP 전송] 2c-1. {self.name} -> AI_Server: (patrolling/detected) frame_id={frame_id}")
            self.udp_socket.sendto(original_data, self.ai_server_addr)

            # 2. DataMerger로 원본 이미지 데이터 전달 (나중에 AI 결과와 병합하기 위함)
            print(f"[➡️ 큐 입력] 2c-2. {self.name} -> DataMerger: (patrolling/detected) frame_id={frame_id}")
            self.image_for_merger_queue.put((frame_id, timestamp, image_binary))
        except Exception as e:
            print(f"[{self.name}] 패트롤링 데이터 전송 오류: {e}")

    def stop(self):
        """스레드를 안전하게 종료합니다."""
        self.running = False
        self.udp_socket.close()
        print(f"\n[{self.name}] 종료 요청 수신.")