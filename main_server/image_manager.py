# =====================================================================================
# FILE: main_server/image_manager.py (수정 완료)
#
# PURPOSE:
#   - 로봇(Image Sender)으로부터 영상 프레임을 수신하는 시스템의 첫 관문.
#   - 시스템의 전체 상태(robot_status)에 따라 자신의 역할을 동적으로 변경하는
#     '상태 기반 실행자(Stateful Actor)'로 동작.
#   - 수신 데이터: JSON 헤더(frame_id, timestamp)와 JPEG 이미지 바이너리가 '|'로 구분된 UDP 패킷.
#
# 주요 로직:
#   1. 상태 분기 로직 (_receive_and_forward_thread):
#      - SystemManager로부터 공유받은 robot_status['state'] 값을 매 순간 확인.
#      - 'idle' 상태: AI 분석 없이 순수 이미지만 DataMerger로 전송.
#      - 'moving' 상태: ArUco 마커를 탐지하고, 제어용 결과와 시각화용 영상을 각각 전송.
#      - 'patrolling' 상태: AI 서버로 이미지를 보내 분석을 요청하고, 원본 이미지도 DataMerger로 전송.
#
#   2. 'moving' 상태 로직 (_process_aruco_mode):
#      - 수신한 영상에서 ArUco 마커를 탐지하고 거리 등을 계산.
#      - [흐름 A - 제어용]: 탐지 결과(ID, 거리)를 RobotCommander로 전송.
#      - [흐름 B - 시각화용]: 원본 영상에 마커를 그린 '수정된 영상'을 DataMerger로 전송.
#
#   3. 'patrolling' 상태 로직 (_process_patrolling_mode):
#      - AI Server로 원본 패킷을 전달하여 객체 탐지 분석을 요청.
#      - 원본 이미지를 DataMerger로 전달하여 AI 분석 결과와 병합할 수 있도록 준비.
# =====================================================================================

# -------------------------------------------------------------------------------------
# [섹션 1] 모듈 임포트
# -------------------------------------------------------------------------------------
import socket
import threading
import queue
import json
import pickle
import cv2
import numpy as np

# -------------------------------------------------------------------------------------
# [섹션 2] ImageManager 클래스 정의
# -------------------------------------------------------------------------------------
class ImageManager(threading.Thread):
    """
    로봇의 영상 프레임을 수신하고, 시스템 상태에 따라 ArUco 탐지 또는 AI 서버로 전달하는 클래스.
    """
    # ==================== 초기화 메서드 ====================
    def __init__(self, listen_port, ai_server_addr, image_for_merger_queue, robot_status, aruco_result_queue):
        super().__init__()
        self.name = "ImageManagerThread"
        self.running = True

        # --- 공유 자원 및 큐 연결 ---
        self.robot_status = robot_status
        self.aruco_result_queue = aruco_result_queue
        self.image_for_merger_queue = image_for_merger_queue

        # --- 네트워크 설정 ---
        self.ai_server_addr = ai_server_addr
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.bind(('0.0.0.0', listen_port))
        self.udp_socket.settimeout(1.0)
        print(f"[{self.name}] 로봇 이미지 수신 대기 중... (Port: {listen_port})")

        # --- ArUco 탐지 설정 ---
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_250)
        self.aruco_params = cv2.aruco.DetectorParameters()
        self.aruco_detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.aruco_params)

        # --- 카메라 보정 데이터 로드 ---
        calibration_file_path = 'shared/camera_calibration.pkl'
        self.camera_matrix, self.dist_coeffs = self._load_calibration_data(calibration_file_path)
        if self.camera_matrix is None or self.dist_coeffs is None:
            print(f"[{self.name}] 치명적 오류: 카메라 보정 파일 로드 실패. 스레드를 시작할 수 없습니다.")
            self.running = False

    # ==================== 메인 실행 메서드 ====================
    def run(self):
        """스레드가 시작될 때 호출되는 메인 메서드."""
        if not self.running:
            return
        self._receive_and_forward_thread()
        print(f"[{self.name}] 스레드 종료.")

    # ==================== 내부 헬퍼 메서드 ====================
    def _load_calibration_data(self, pkl_path):
        """지정된 경로의 .pkl 파일에서 카메라 보정 데이터를 로드합니다."""
        try:
            with open(pkl_path, 'rb') as f:
                calibration_data = pickle.load(f)
                camera_matrix = np.array(calibration_data['camera_matrix'])
                dist_coeffs = np.array(calibration_data['dist_coeffs'])
                print(f"[{self.name}] 카메라 보정 데이터를 '{pkl_path}'에서 성공적으로 로드했습니다.")
                return camera_matrix, dist_coeffs
        except Exception as e:
            print(f"[{self.name}] 오류: 보정 파일({pkl_path}) 로드 중 에러 발생 - {e}")
            return None, None

    def _parse_udp_packet(self, data):
        """UDP 패킷에서 '|'를 기준으로 JSON 헤더와 이미지 바이너리를 분리합니다."""
        try:
            delimiter_pos = data.find(b'|')
            if delimiter_pos == -1: return None, None
            header_bytes = data[:delimiter_pos]
            image_binary = data[delimiter_pos+1:]
            header_json = json.loads(header_bytes.decode('utf-8'))
            return header_json, image_binary
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"[{self.name}] UDP 패킷 파싱 오류: {e}")
            return None, None

    # ==================== 핵심 로직: 수신 및 상태별 분기 ====================
    def _receive_and_forward_thread(self):
        """UDP 소켓으로 로봇의 이미지를 계속 수신하고 상태에 따라 처리합니다."""
        while self.running:
            try:
                # 1. UDP 소켓으로부터 데이터 수신
                data, addr = self.udp_socket.recvfrom(65535)

                # 2. 수신 데이터 파싱
                header_json, image_binary = self._parse_udp_packet(data)
                if not header_json: continue

                frame_id = header_json.get('frame_id')
                timestamp = header_json.get('timestamp')
                print(f"[✅ UDP 수신] 1. Robot -> ImageManager : frame_id {frame_id}")

                # 3. 로봇 상태에 따른 분기 처리
                current_state = self.robot_status.get('state', 'idle')

                if current_state == 'idle':
                    print(f"[➡️ 큐 입력] 2a. ImageManager -> DataMerger : (idle) frame_id {frame_id}")
                    self.image_for_merger_queue.put((frame_id, timestamp, image_binary))

                elif current_state == 'moving':
                    self._process_aruco_mode(header_json, image_binary)

                elif current_state == 'patrolling':
                    self._process_patrolling_mode(data, header_json, image_binary)

            except socket.timeout:
                continue
            except Exception as e:
                print(f"[{self.name}] UDP 수신/처리 오류: {e}")

    # ==================== 상태별 처리 메서드 ====================
    def _process_aruco_mode(self, header_json, image_binary):
        """'moving' 상태: ArUco 마커를 탐지하고 결과를 각 목적지로 보냅니다."""
        try:
            frame_id = header_json.get('frame_id')
            timestamp = header_json.get('timestamp')

            # --- ArUco 탐지 및 이미지 처리 ---
            image_np = np.frombuffer(image_binary, dtype=np.uint8)
            frame = cv2.imdecode(image_np, cv2.IMREAD_COLOR)
            corners, ids, _ = self.aruco_detector.detectMarkers(frame)

            if ids is not None:
                cv2.aruco.drawDetectedMarkers(frame, corners, ids)
                rvecs, tvecs, _ = cv2.aruco.estimatePoseSingleMarkers(corners, 0.05, self.camera_matrix, self.dist_coeffs)
                for i, marker_id in enumerate(ids):
                    distance_z = tvecs[i][0][2]
                    aruco_result = {'id': int(marker_id[0]), 'distance': distance_z}

                    # --- [흐름 A] 제어용 데이터 전송 (to RobotCommander) ---
                    print(f"[➡️ 큐 입력] 2b-1. ImageManager -> RobotCommander : (moving) ArUco id={aruco_result['id']}, dist={distance_z:.2f}")
                    self.aruco_result_queue.put(aruco_result)

                    # --- 이미지에 거리 정보 그리기 ---
                    top_left = corners[i][0][0]
                    cv2.putText(frame, f"Dist: {distance_z:.2f}m", (int(top_left[0]), int(top_left[1]) - 15),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            # --- [흐름 B] 시각화용 데이터 전송 (to DataMerger) ---
            _, annotated_image_binary = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            print(f"[➡️ 큐 입력] 2b-2. ImageManager -> DataMerger : (moving) frame_id {frame_id} (annotated)")
            self.image_for_merger_queue.put((frame_id, timestamp, annotated_image_binary.tobytes()))

        except Exception as e:
            print(f"[{self.name}] ArUco 처리 오류: {e}")

    def _process_patrolling_mode(self, original_data, header_json, image_binary):
        """'patrolling' 상태: AI 서버와 DataMerger 양쪽으로 데이터를 보냅니다."""
        try:
            frame_id = header_json.get('frame_id')
            timestamp = header_json.get('timestamp')

            # --- [흐름 A] AI 분석용 데이터 전송 (to AI Server) ---
            print(f"[✈️ UDP 전송] 2c-1. ImageManager -> AI_Server : (patrolling) frame_id {frame_id}")
            self.udp_socket.sendto(original_data, self.ai_server_addr)

            # --- [흐름 B] 병합용 원본 이미지 전송 (to DataMerger) ---
            print(f"[➡️ 큐 입력] 2c-2. ImageManager -> DataMerger : (patrolling) frame_id {frame_id}")
            self.image_for_merger_queue.put((frame_id, timestamp, image_binary))
        except Exception as e:
            print(f"[{self.name}] 패트롤링 데이터 전송 오류: {e}")

    # ==================== 종료 메서드 ====================
    def stop(self):
        """스레드를 안전하게 종료합니다."""
        self.running = False
        self.udp_socket.close()
        print(f"[{self.name}] 종료 요청 수신.")