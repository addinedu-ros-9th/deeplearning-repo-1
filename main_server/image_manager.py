# =====================================================================================
# FILE: main_server/image_manager.py
#
# PURPOSE:
#   - 로봇(Image Sender)으로부터 실시간 영상 프레임을 UDP로 수신하는 첫 관문.
#   - 시스템의 중앙 상태 공유 객체('robot_status')를 지속적으로 감시하여, 로봇의 현재
#     상태('moving', 'patrolling', 'detected', 'idle')에 따라 데이터 처리 방식을 동적으로 변경하는
#     '이미지 교통 관제사' 역할을 수행함.
#   - ArUco 마커 거리 측정값의 노이즈를 줄이고 안정성을 높이기 위해 칼만 필터를 적용.
#
# 주요 로직:
#   1. KalmanFilter1D 클래스:
#      - ArUco 마커와의 거리 측정값에서 발생하는 노이즈(떨림 현상)를 완화하기 위한
#        간단한 1차원 칼만 필터를 구현.
#   2. ImageManager 클래스 (메인 처리 로직):
#      - __init__():
#        - 로봇으로부터 UDP 패킷을 수신하기 위한 소켓을 생성하고 지정된 포트에 바인딩.
#        - ArUco 마커 탐지 및 거리 계산에 필요한 카메라 보정 데이터(.pkl)를 로드.
#        - 각 ArUco 마커 ID별로 독립적인 칼만 필터를 관리하기 위한 딕셔너리를 초기화.
#      - run():
#        - 메인 스레드 루프. UDP 소켓을 통해 지속적으로 이미지 패킷을 수신.
#        - 수신된 패킷을 JSON 헤더와 이미지 바이너리로 파싱.
#        - 공유 객체 `robot_status['state']`를 확인하여 아래의 세 가지 모드 중 하나로 분기.
#      - _process_aruco_mode() ('moving' 상태):
#        - 네비게이션을 위한 모드. 수신된 이미지에서 ArUco 마커를 탐지.
#        - 탐지된 마커까지의 거리를 계산하고, 해당 마커 ID에 할당된 칼만 필터를 이용해 거리 값을 보정.
#        - 보정된 거리 정보를 `RobotCommander`가 사용할 수 있도록 `aruco_result_queue`에 삽입.
#        - GUI 시각화를 위해 탐지 정보가 그려진 이미지를 `DataMerger`로 전달.
#      - _process_patrolling_mode() ('patrolling' 또는 'detected' 상태):
#        - AI 분석을 위한 모드. 수신한 원본 UDP 패킷을 그대로 AI 서버(`detection_manager`)로 전달(Forwarding).
#        - 동시에, 추후 AI 분석 결과와 병합하기 위해 원본 이미지를 `DataMerger`로 전달.
#      - 'idle' 상태 처리:
#        - AI 분석이나 ArUco 탐지 없이, 수신된 이미지를 GUI 표시용으로 `DataMerger`에만 전달.
# =====================================================================================

# -------------------------------------------------------------------------------------
# [섹션 1] 모듈 임포트
# -------------------------------------------------------------------------------------
import socket  # UDP/TCP 통신을 위한 소켓 모듈
import threading  # 다중 스레딩 기능을 사용하기 위한 모듈
import queue  # 스레드 간 안전한 데이터 교환을 위한 큐 모듈
import json  # JSON 형식 데이터 처리를 위한 모듈
import pickle  # 파이썬 객체 직렬화/역직렬화를 위한 모듈 (카메라 보정값 로드)
import cv2  # OpenCV 라이브러리 (이미지 처리, ArUco 탐지)
import numpy as np  # 수치 연산 및 배열 처리를 위한 NumPy 라이브러리

# -------------------------------------------------------------------------------------
# [섹션 2] 1차원 칼만 필터 클래스
# -------------------------------------------------------------------------------------
class KalmanFilter1D:
    """
    ArUco 마커 거리 측정값의 노이즈를 줄이기 위한 간단한 1차원 칼만 필터.
    """
    def __init__(self, R=0.1, Q=1e-5):
        self.R = R  # 측정 노이즈 공분산 (Measurement Noise Covariance): 측정값의 불확실성. 클수록 측정값을 덜 신뢰.
        self.Q = Q  # 프로세스 노이즈 공분산 (Process Noise Covariance): 모델의 예측값의 불확실성. 작을수록 모델을 더 신뢰.
        self.A = 1  # 상태 전이 모델 (State Transition Model): 현재 상태가 다음 상태로 어떻게 변할지 정의 (여기서는 변화 없다고 가정).
        self.H = 1  # 관측 모델 (Observation Model): 상태 변수가 측정값으로 어떻게 변환될지 정의.
        self.x = 0  # 초기 상태 (추정값)
        self.P = 1  # 초기 오차 공분산 (Error Covariance)

    def predict(self):
        """이전 상태를 기반으로 현재 상태를 예측."""
        self.x = self.A * self.x
        self.P = self.A * self.P * self.A + self.Q
        return self.x

    def update(self, z):
        """예측값과 실제 측정값을 사용해 상태를 보정(업데이트)."""
        K = self.P * self.H / (self.H * self.P * self.H + self.R)  # 칼만 이득 계산
        self.x = self.x + K * (z - self.H * self.x)  # 상태 추정값 업데이트
        self.P = (1 - K * self.H) * self.P  # 오차 공분산 업데이트
        return self.x

# -------------------------------------------------------------------------------------
# [섹션 3] ImageManager 클래스 정의
# -------------------------------------------------------------------------------------
class ImageManager(threading.Thread):
    def __init__(self, listen_port, ai_server_addr, image_for_merger_queue, robot_status, aruco_result_queue):
        super().__init__()
        self.name = "ImageManager"
        self.running = True

        # --- 공유 자원 및 외부 설정 초기화 ---
        self.robot_status = robot_status  # 시스템 전역 로봇 상태 객체
        self.aruco_result_queue = aruco_result_queue  # RobotCommander로 ArUco 결과를 보낼 큐
        self.image_for_merger_queue = image_for_merger_queue  # DataMerger로 이미지를 보낼 큐
        self.ai_server_addr = ai_server_addr  # AI 서버의 주소 (IP, Port)

        # --- 네트워크 설정 ---
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # UDP 소켓 생성
        self.udp_socket.bind(('0.0.0.0', listen_port)) # 모든 인터페이스의 지정된 포트에서 수신 대기
        self.udp_socket.settimeout(1.0) # 1초 타임아웃 설정 (블로킹 방지)
        print(f"[{self.name}] 로봇 이미지 수신 대기 중... (Port: {listen_port})")

        # --- ArUco 탐지 설정 ---
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_250) # 사용할 ArUco 딕셔너리
        self.aruco_params = cv2.aruco.DetectorParameters() # ArUco 탐지 파라미터
        self.aruco_detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.aruco_params) # ArUco 탐지기 생성

        # --- 카메라 보정 데이터 로드 ---
        calibration_file_path = 'shared/camera_calibration.pkl'
        self.camera_matrix, self.dist_coeffs = self._load_calibration_data(calibration_file_path)
        if self.camera_matrix is None or self.dist_coeffs is None:
            print(f"[{self.name}] 치명적 오류: 카메라 보정 파일 로드 실패.")
            self.running = False

        # --- 칼만 필터 초기화 ---
        # 각 ArUco 마커 ID에 대한 칼만 필터 인스턴스를 저장할 딕셔너리
        self.kalman_filters = {}

        print(f"[{self.name}] 초기화 완료 (칼만 필터 적용).")

    def _load_calibration_data(self, pkl_path):
        """pickle 파일에서 카메라 보정 데이터를 로드."""
        try:
            with open(pkl_path, 'rb') as f:
                data = pickle.load(f)
                return np.array(data['camera_matrix']), np.array(data['dist_coeffs'])
        except Exception as e:
            print(f"[{self.name}] 보정 파일 로드 오류: {e}")
            return None, None

    def _parse_udp_packet(self, data):
        """UDP 패킷을 JSON 헤더와 이미지 바이너리로 분리."""
        try:
            delimiter_pos = data.find(b'|') # 구분자 위치 검색
            if delimiter_pos == -1: return None, None
            header_bytes = data[:delimiter_pos] # 헤더 부분 추출
            image_binary = data[delimiter_pos+1:].rstrip(b'\n') # 이미지 부분 추출 및 개행문자 제거
            header_json = json.loads(header_bytes.decode('utf-8')) # 헤더를 JSON으로 파싱
            return header_json, image_binary
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None, None

    def run(self):
        """스레드 메인 루프. UDP 패킷 수신 및 상태에 따른 처리."""
        if not self.running: return
        print(f"[{self.name}] 스레드 시작.")
        while self.running:
            try:
                data, addr = self.udp_socket.recvfrom(65535) # UDP 데이터 수신 (최대 65535 바이트)
                header_json, image_binary = self._parse_udp_packet(data) # 패킷 파싱
                if not header_json: continue # 파싱 실패 시 건너뛰기
                
                frame_id = header_json.get('frame_id')
                timestamp = header_json.get('timestamp')
                print("-----------------------------------------------------")
                print(f"[✅ UDP 수신] 1. Robot -> {self.name}: frame_id={frame_id}, timestamp={timestamp}, size={len(data)} bytes")
                
                current_state = self.robot_status.get('state', 'idle') # 현재 로봇 상태 확인

                # 로봇 상태에 따라 처리 로직 분기
                if current_state == 'idle':
                    self.image_for_merger_queue.put((frame_id, timestamp, image_binary))
                elif current_state == 'moving':
                    self._process_aruco_mode(header_json, image_binary)
                elif current_state in ['patrolling', 'detected']:
                    self._process_patrolling_mode(data, header_json, image_binary)

            except socket.timeout:
                continue # 타임아웃은 정상 동작이므로 계속 진행
            except Exception as e:
                print(f"[{self.name}] UDP 수신/처리 오류: {e}")
        print(f"[{self.name}] 스레드 종료.")

    def _process_aruco_mode(self, header_json, image_binary):
        """'moving' 상태 처리: ArUco 마커 탐지 및 거리 계산/보정."""
        frame_id = header_json.get('frame_id')
        timestamp = header_json.get('timestamp')
        try:
            image_np = np.frombuffer(image_binary, dtype=np.uint8) # 바이너리를 NumPy 배열로 변환
            frame = cv2.imdecode(image_np, cv2.IMREAD_COLOR) # 이미지를 디코딩
            corners, ids, _ = self.aruco_detector.detectMarkers(frame) # ArUco 마커 탐지

            if ids is not None: # 마커가 하나 이상 탐지된 경우
                # 마커의 3D 위치(rvecs, tvecs) 추정
                rvecs, tvecs, _ = cv2.aruco.estimatePoseSingleMarkers(corners, 0.05, self.camera_matrix, self.dist_coeffs)
                for i, marker_id_array in enumerate(ids):
                    marker_id = int(marker_id_array[0])

                    # --- 칼만 필터 적용 ---
                    if marker_id not in self.kalman_filters: # 해당 ID의 필터가 없으면 새로 생성
                        self.kalman_filters[marker_id] = KalmanFilter1D()
                        print(f"[{self.name}] ArUco ID '{marker_id}'에 대한 새 칼만 필터 생성.")

                    measured_distance = tvecs[i][0][2] # 측정된 거리 (z축 값)
                    
                    kf = self.kalman_filters[marker_id] # 해당 마커의 칼만 필터 가져오기
                    kf.predict() # 예측 단계
                    filtered_distance = kf.update(measured_distance) # 업데이트(보정) 단계

                    # RobotCommander로 보낼 결과 데이터 생성
                    aruco_result = {'id': marker_id, 'distance': filtered_distance}
                    
                    print(f"[➡️ 큐 입력] 2b-1. {self.name} -> RobotCommander: ArUco id={marker_id}, "
                          f"측정거리={measured_distance:.2f}, 필터링된 거리={filtered_distance:.2f}")
                    self.aruco_result_queue.put(aruco_result) # 큐에 결과 삽입
                    
                    # --- GUI 시각화용 이미지 생성 ---
                    cv2.aruco.drawDetectedMarkers(frame, corners, ids) # 탐지된 마커 그리기
                    top_left = corners[i][0][0] # 마커의 좌상단 좌표
                    # 보정된 거리 값을 이미지에 텍스트로 추가
                    cv2.putText(frame, f"Dist: {filtered_distance:.2f}m", (int(top_left[0]), int(top_left[1]) - 15),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            # 주석이 달린 이미지를 JPEG으로 인코딩
            _, annotated_image_binary = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            # DataMerger로 전송
            self.image_for_merger_queue.put((frame_id, timestamp, annotated_image_binary.tobytes()))
        except Exception as e:
            print(f"[{self.name}] ArUco 처리 오류: {e}")

    def _process_patrolling_mode(self, original_data, header_json, image_binary):
        """'patrolling'/'detected' 상태 처리: AI 서버 및 DataMerger로 데이터 전송."""
        frame_id = header_json.get('frame_id')
        timestamp = header_json.get('timestamp')
        try:
            # AI 서버로 원본 UDP 패킷을 그대로 전달
            self.udp_socket.sendto(original_data, self.ai_server_addr)
            # DataMerger로 원본 이미지 바이너리를 전달
            self.image_for_merger_queue.put((frame_id, timestamp, image_binary))
        except Exception as e:
            print(f"[{self.name}] 패트롤링 데이터 전송 오류: {e}")

    def stop(self):
        """스레드를 안전하게 종료."""
        self.running = False
        self.udp_socket.close()
        print(f"\n[{self.name}] 종료 요청 수신.")