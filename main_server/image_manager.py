# =====================================================================================
# FILE: main_server/image_manager.py
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
import socket # 네트워크 통신을 위한 소켓 모듈 임포트
import threading # 스레드 기능을 사용하기 위한 모듈 임포트
import queue # 큐 자료구조를 사용하기 위한 모듈 임포트
import json # JSON 데이터 처리를 위한 모듈 임포트
import pickle # .pkl 파일 로드를 위한 pickle 모듈 임포트
import cv2 # OpenCV 라이브러리 임포트 (ArUco 탐지 및 이미지 처리용)
import numpy as np # 숫자 및 행렬 연산을 위한 NumPy 라이브러리 임포트

# -------------------------------------------------------------------------------------
# [섹션 2] ImageManager 클래스 정의
# -------------------------------------------------------------------------------------
class ImageManager(threading.Thread):
    """
    로봇의 영상 프레임을 수신하고, 시스템 상태에 따라 ArUco 탐지 또는 AI 서버로 전달하는 클래스.
    """
    def __init__(self, listen_port, ai_server_addr, image_for_merger_queue, robot_status, aruco_result_queue):
        super().__init__()
        self.name = "ImageManagerThread" # 스레드 이름 설정
        self.running = True # 스레드 실행 상태를 제어하는 플래그

        # SystemManager로부터 공유 객체 및 큐를 전달받음
        self.robot_status = robot_status # 로봇 상태 공유 딕셔너리
        self.aruco_result_queue = aruco_result_queue # ArUco 탐지 결과를 RobotCommander로 보낼 큐
        self.image_for_merger_queue = image_for_merger_queue # 이미지를 DataMerger로 보낼 큐

        # 네트워크 설정
        self.ai_server_addr = ai_server_addr # 영상 분석을 요청할 AI 서버 주소
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # UDP 소켓 생성
        self.udp_socket.bind(('0.0.0.0', listen_port)) # 모든 인터페이스의 지정된 포트에서 수신 대기
        self.udp_socket.settimeout(1.0) # 소켓 타임아웃 1초로 설정 (stop() 호출 시 즉각 반응 위함)
        print(f"[{self.name}] 로봇 이미지 수신 대기 중... (Port: {listen_port})")

        # ArUco 탐지를 위한 설정 초기화
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_250) # 사용할 ArUco 딕셔너리
        self.aruco_params = cv2.aruco.DetectorParameters() # ArUco 탐지 파라미터
        self.aruco_detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.aruco_params)

        # --- 카메라 보정 데이터 로드 ---
        # .pkl 파일로부터 카메라 매트릭스와 왜곡 계수를 로드
        calibration_file_path = 'shared/camera_calibration.pkl'  # .pkl 파일 경로
        self.camera_matrix, self.dist_coeffs = self._load_calibration_data(calibration_file_path)

        # 파일 로드에 실패하면 스레드 실행을 중단 (정확한 거리 측정이 불가능하므로)
        if self.camera_matrix is None or self.dist_coeffs is None:
            print(f"[{self.name}] 치명적 오류: 카메라 보정 파일 로드 실패. 스레드를 시작할 수 없습니다.")
            self.running = False # run() 메서드가 즉시 종료되도록 설정

    def _load_calibration_data(self, pkl_path):
        """지정된 경로의 .pkl 파일에서 카메라 보정 데이터를 로드합니다."""
        try:
            with open(pkl_path, 'rb') as f:
                # .pkl 파일에 데이터가 저장된 형식에 맞춰 아래 코드를 선택 또는 수정합니다.
                # 예시: 딕셔너리 {'camera_matrix': ..., 'dist_coeffs': ...} 형태로 저장된 경우
                calibration_data = pickle.load(f)
                camera_matrix = calibration_data['camera_matrix']
                dist_coeffs = calibration_data['dist_coeffs']
                
                print(f"[{self.name}] 카메라 보정 데이터를 '{pkl_path}'에서 성공적으로 로드했습니다.")
                return np.array(camera_matrix), np.array(dist_coeffs)

        except FileNotFoundError:
            print(f"[{self.name}] 오류: 보정 파일({pkl_path})을 찾을 수 없습니다.")
            return None, None
        except Exception as e:
            print(f"[{self.name}] 오류: 보정 파일 로드 중 에러 발생 - {e}")
            return None, None

    def run(self): # 스레드가 시작될 때 호출되는 메인 메서드
        """메인 처리 스레드를 시작합니다."""
        if not self.running: # 생성자에서 파일 로드 실패 시 run 메서드 조기 종료
            return
            
        self._receive_and_forward_thread()
        print(f"[{self.name}] 스레드 종료.")

    def _receive_and_forward_thread(self):
        """UDP 소켓으로 로봇의 이미지를 계속 수신하고 상태에 따라 처리합니다."""
        while self.running:
            try:
                # UDP 소켓으로부터 최대 65535 바이트의 데이터를 수신
                data, addr = self.udp_socket.recvfrom(65535)
                
                # 수신한 데이터 패킷을 JSON 헤더와 이미지 바이너리로 파싱
                header_json, image_binary = self._parse_udp_packet(data)
                if not header_json: continue # 파싱 실패 시 다음 패킷 대기
                
                # 디버깅: 로봇으로부터 데이터 수신 확인
                print(f"[✅ UDP 수신] 1. Robot -> ImageManager : frame_id {header_json.get('frame_id')}")
                
                # --- 현재 로봇 상태에 따른 분기 처리 ---
                current_state = self.robot_status.get('state', 'idle')

                if current_state == 'idle':
                    # 'idle' 상태: 이미지를 DataMerger로만 보냄 (AI 분석 없음)
                    print(f"[➡️ 큐 입력] 2. ImageManager -> DataMerger : (idle) frame_id {header_json.get('frame_id')}")
                    self.image_for_merger_queue.put((header_json, image_binary))

                elif current_state == 'moving':
                    # '이동 중' 상태: ArUco 탐지 모드 실행
                    self._process_aruco_mode(header_json, image_binary)
                
                elif current_state == 'patrolling':
                    # '순찰 중' 상태: 기존 패트롤링 모드 실행
                    self._process_patrolling_mode(data, header_json, image_binary)

            except socket.timeout:
                # 1초 타임아웃 발생 시, self.running 플래그 확인 후 계속 진행
                continue
            except Exception as e:
                print(f"[{self.name}] UDP 수신/처리 오류: {e}")

    def _parse_udp_packet(self, data):
        """UDP 패킷에서 구분자 '|'를 기준으로 JSON 헤더와 이미지 바이너리를 분리합니다."""
        try:
            # 구분자 b'|'의 위치를 찾음
            delimiter_pos = data.find(b'|')
            if delimiter_pos == -1:
                return None, None
            
            # 구분자를 기준으로 JSON 부분과 이미지 부분을 나눔
            header_bytes = data[:delimiter_pos]
            image_binary = data[delimiter_pos+1:]
            
            # JSON 바이트를 문자열로 디코딩 후 파싱
            header_json = json.loads(header_bytes.decode('utf-8'))
            return header_json, image_binary
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"[{self.name}] UDP 패킷 파싱 오류: {e}")
            return None, None

    def _process_aruco_mode(self, header_json, image_binary):
        """'moving' 상태의 처리 로직: ArUco 마커를 탐지하고 결과를 각 큐로 보냅니다."""
        try:
            # 1. 이미지 디코딩
            image_np = np.frombuffer(image_binary, dtype=np.uint8)
            frame = cv2.imdecode(image_np, cv2.IMREAD_COLOR)

            # 2. ArUco 마커 탐지
            corners, ids, rejected = self.aruco_detector.detectMarkers(frame)

            if ids is not None: # 마커가 하나 이상 탐지된 경우
                # 3. 시각화를 위해 이미지에 마커 그리기
                # 4. 마커 3D 위치 추정
                cv2.aruco.drawDetectedMarkers(frame, corners, ids)
                rvecs, tvecs, _ = cv2.aruco.estimatePoseSingleMarkers(corners, 0.05, self.camera_matrix, self.dist_coeffs)

                for i, marker_id in enumerate(ids):
                    # 5. [흐름 A] 제어용 데이터 전송
                    distance_z = tvecs[i][0][2]
                    aruco_result = {'id': int(marker_id[0]), 'distance': distance_z}
                    # 디버깅: RobotCommander로 ArUco 결과 전송 확인
                    print(f"[➡️ 큐 입력] 2. ImageManager -> RobotCommander : (moving) ArUco id={aruco_result['id']}, dist={aruco_result['distance']:.2f}")
                    self.aruco_result_queue.put(aruco_result)
                
                    # ✨ [여기 추가] 이미지에 거리 텍스트를 그리는 로직 ✨
                    # 마커의 첫 번째 코너 좌표를 가져옴
                    top_left_corner = corners[i][0][0]
                    text_position = (int(top_left_corner[0]), int(top_left_corner[1] - 15))
                    distance_text = f"Dist: {distance_z:.2f}m"
                    
                    # 프레임에 텍스트를 그림
                    cv2.putText(frame, distance_text, text_position, 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            
            # 6. [흐름 B] 시각화용 데이터 전송
            _, annotated_image_binary = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            # 디버깅: DataMerger로 수정된(annotated) 이미지 전송 확인
            print(f"[➡️ 큐 입력] 2. ImageManager -> DataMerger : (moving) frame_id {header_json.get('frame_id')} (annotated)")
            self.image_for_merger_queue.put((header_json, annotated_image_binary.tobytes()))

        except Exception as e:
            print(f"[{self.name}] ArUco 처리 오류: {e}")

    def _process_patrolling_mode(self, original_data, header_json, image_binary):
        """'patrolling' 상태의 처리 로직: AI 서버와 DataMerger로 데이터를 보냅니다."""
        try:
            # 디버깅: AI 서버로 UDP 전송 확인
            print(f"[✈️ UDP 전송] 2. ImageManager -> AI_Server : (patrolling) frame_id {header_json.get('frame_id')}")
            self.udp_socket.sendto(original_data, self.ai_server_addr)
            
            # 디버깅: DataMerger로 원본 이미지 전송 확인
            print(f"[➡️ 큐 입력] 2. ImageManager -> DataMerger : (patrolling) frame_id {header_json.get('frame_id')}")
            self.image_for_merger_queue.put((header_json, image_binary))
        except Exception as e:
            print(f"[{self.name}] 패트롤링 데이터 전송 오류: {e}")

    def stop(self): # 스레드를 안전하게 종료하는 메서드
        """스레드의 메인 루프를 중지하고 소켓을 닫습니다."""
        self.running = False # 메인 루프 종료를 위한 플래그 설정
        self.udp_socket.close() # recvfrom() 대기 상태를 해제하기 위해 소켓을 닫음
        print(f"[{self.name}] 종료 요청 수신.")