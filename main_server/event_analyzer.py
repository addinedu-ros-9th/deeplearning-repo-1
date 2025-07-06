# =====================================================================================
# FILE: main_server/event_analyzer.py
#
# PURPOSE:
#   - AI 서버(detection_manager)로부터 TCP를 통해 실시간으로 전송되는 객체 탐지 결과를 수신.
#   - 수신된 탐지 데이터를 특정 시간 윈도우(WINDOW_SECONDS) 동안 수집하고 분석하여,
#     일시적인 노이즈가 아닌 '안정적인 이벤트'가 발생했는지 판단하는 역할.
#   - 'patrolling' 상태에 진입한 직후, 잘못된 탐지를 방지하기 위해 일정 시간(PATROL_WARM_UP_SECONDS)
#     동안 분석을 보류하는 '워밍업' 기능을 수행.
#   - 안정적인 이벤트가 감지되면, 시스템의 전역 상태(robot_status['state'])를 'patrolling'에서
#     'detected'로 변경하여 시스템 전체에 이벤트 발생을 알리는 핵심적인 역할.
#   - 원본 탐지 결과에 'case' 정보(danger, emergency, illegal)를 추가하여 다음 컴포넌트인
#     DataMerger로 전달.
#
# 주요 로직:
#   1. 상태 변경 감지 및 워밍업:
#      - 로봇의 상태가 'patrolling'으로 처음 변경된 시점을 감지.
#      - PATROL_WARM_UP_SECONDS 동안은 안정성 분석을 수행하지 않고 데이터를 버퍼링만 하여,
#        상태 변경 직후의 불안정한 초기 탐지 결과를 무시.
#   2. 데이터 수신 및 버퍼링:
#      - AI 서버로부터 TCP 스트림을 통해 JSON 형식의 탐지 결과를 지속적으로 수신.
#      - 수신된 탐지 결과를 시간 윈도우(WINDOW_SECONDS)를 관리하는 deque(detection_window)에
#        (타임스탬프, 탐지된 객체 리스트) 형태로 저장.
#   3. 안정성 분석 (_update_robot_state_based_on_stability):
#      - 현재 deque에 쌓인 데이터가 최소 프레임 수(MIN_FRAMES_FOR_STABILITY_CHECK)를 넘었는지 확인.
#      - 시간 윈도우 내에서 가장 빈번하게 탐지된 객체의 '안정도(stability)'를 계산.
#        (안정도 = 특정 객체 탐지 횟수 / 전체 프레임 수)
#      - 특정 객체의 안정도가 설정된 임계값(STABILITY_THRESHOLD)을 초과하면, 유의미한 이벤트가
#        발생한 것으로 간주.
#   4. 상태 전파 및 데이터 전달:
#      - 안정적인 이벤트가 감지되면 robot_status['state']를 'detected'로 변경.
#      - 수신한 원본 JSON 데이터에 각 탐지별 'case' 정보를 추가.
#      - 처리된 데이터를 DataMerger가 사용할 수 있도록 output_queue에 삽입.
# =====================================================================================

# -------------------------------------------------------------------------------------
# [섹션 1] 모듈 임포트
# -------------------------------------------------------------------------------------
import socket # TCP/IP 통신을 위한 소켓 모듈
import threading # 다중 스레딩 기능을 위한 모듈
import queue # 스레드 간 안전한 데이터 교환을 위한 큐 모듈 (여기서는 사용되지 않음)
import json # JSON 형식 데이터 처리를 위한 모듈
import struct # 바이너리 데이터 패킹/언패킹을 위한 모듈
import time # 시간 관련 함수를 사용하기 위한 모듈
from collections import deque, Counter # 양방향 큐(deque)와 카운터(Counter) 자료구조

# -------------------------------------------------------------------------------------
# [섹션 2] EventAnalyzer 클래스 정의
# -------------------------------------------------------------------------------------
class EventAnalyzer(threading.Thread):
    # --- 클래스 상수 정의 ---
    PATROL_WARM_UP_SECONDS = 1.0  # 'patrolling' 상태 진입 후 안정성 분석을 시작하기 전 대기 시간 (초)
    WINDOW_SECONDS = 2.0  # 안정성 분석에 사용할 시간 윈도우 크기 (초)
    STABILITY_THRESHOLD = 0.4  # 특정 객체가 '안정적'으로 탐지되었다고 판단할 비율 임계값
    MIN_FRAMES_FOR_STABILITY_CHECK = 40 # 안정성 분석을 시작하기 위한 최소 프레임 수
    CASE_MAPPING = { # 탐지된 객체 레이블을 이벤트 종류(case)로 매핑하는 딕셔너리
        'knife': 'danger',
        'gun': 'danger',
        'lying_down': 'emergency',
        'cigarette': 'illegal'
    }

    def __init__(self, listen_port, output_queue, robot_status):
        super().__init__()
        self.name = "EventAnalyzer"
        self.running = True

        # --- 공유 자원 및 외부 설정 초기화 ---
        self.output_queue = output_queue # 분석 결과를 DataMerger로 보낼 큐
        self.robot_status = robot_status # 시스템 전역 로봇 상태 공유 객체
        self.detection_window = deque() # 시간 윈도우 내 탐지 결과를 저장할 deque
        self.last_detected_label = None # 마지막으로 안정적으로 탐지된 객체 레이블
        self.is_paused_log_printed = False # 분석 일시 중지 로그 출력 여부 플래그

        # --- 상태 변경 감지 관련 변수 ---
        self.previous_state = self.robot_status.get('state', 'idle') # 이전 로봇 상태 저장
        self.patrol_mode_start_time = None # 'patrolling' 모드 시작 시간 저장

        # --- 네트워크 설정 ---
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # TCP 서버 소켓 생성
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # 주소 재사용 옵션 설정
        self.server_socket.bind(('0.0.0.0', listen_port)) # 모든 인터페이스의 지정된 포트에서 수신 대기
        self.server_socket.listen(5) # 연결 대기열 크기 설정
        print(f"[{self.name}] AI 서버의 분석 결과 수신 대기 중... (Port: {listen_port})")

    def run(self):
        """스레드 메인 루프. AI 서버의 연결을 수락하고 처리."""
        print(f"[{self.name}] 스레드 시작.")
        while self.running:
            try:
                client_socket, addr = self.server_socket.accept() # 클라이언트(AI 서버) 연결 수락
                print(f"[{self.name}] AI 서버 연결됨: {addr}")
                # 각 연결을 별도의 스레드에서 처리
                handler = threading.Thread(target=self._handle_client, args=(client_socket, addr), daemon=True)
                handler.start()
            except socket.error:
                if not self.running: break
        print(f"[{self.name}] 스레드 종료.")

    def _handle_client(self, conn, addr):
        """연결된 AI 서버로부터 탐지 결과를 수신하고 처리."""
        buffer = b'' # 수신 데이터를 임시 저장할 버퍼
        while self.running:
            try:
                current_state = self.robot_status.get('state', 'idle') # 현재 로봇 상태 확인

                # 'patrolling' 상태로 처음 전환되었는지 감지
                if current_state == 'patrolling' and self.previous_state != 'patrolling':
                    print(f"\n[🚦 시스템 상태] {self.name}: Patrolling 상태 진입. {self.PATROL_WARM_UP_SECONDS}초의 워밍업을 시작합니다.")
                    self.patrol_mode_start_time = time.time() # 워밍업 시작 시간 기록
                    self.detection_window.clear() # 이전 상태의 탐지 기록 초기화

                self.previous_state = current_state # 현재 상태를 다음 루프를 위해 저장

                # 분석이 필요 없는 상태(idle, moving)일 경우, 분석 일시 중지
                if current_state in ['idle', 'moving']:
                    if not self.is_paused_log_printed:
                        print(f"[ℹ️ 상태 확인] {self.name}: '{current_state}' 상태이므로 분석을 일시 중지합니다.")
                        self.is_paused_log_printed = True
                    time.sleep(0.5)
                    self.detection_window.clear() # 버퍼 초기화
                    continue

                if self.is_paused_log_printed: # 분석 재개 시 로그 출력
                    print(f"[ℹ️ 상태 확인] {self.name}: '{current_state}' 상태이므로 분석을 재개합니다.")
                    self.is_paused_log_printed = False

                data = conn.recv(4096) # 데이터 수신
                if not data: break
                buffer += data

                # 버퍼에 개행 문자가 포함될 때까지 데이터를 모아 완전한 메시지 처리
                while b'\n' in buffer:
                    payload, buffer = buffer.split(b'\n', 1) # 메시지와 나머지 버퍼 분리
                    header = payload[:4] # 4바이트 헤더 추출
                    msg_len = struct.unpack('>I', header)[0] # 헤더에서 메시지 길이 파싱
                    json_data_bytes = payload[4:4+msg_len] # 실제 JSON 데이터 추출
                    
                    self._process_detection_result(json_data_bytes) # 파싱된 데이터 처리
                    
            except (ConnectionResetError, struct.error, json.JSONDecodeError) as e:
                print(f"[{self.name}] AI 서버({addr}) 연결 오류: {e}")
                break
        conn.close()
        print(f"[{self.name}] AI 서버({addr}) 연결 종료.")


    def _process_detection_result(self, data_bytes):
        """수신된 탐지 결과를 처리하고, 안정성 분석 후 큐에 삽입."""
        try:
            result_json = json.loads(data_bytes.decode('utf-8')) # 바이트를 JSON으로 파싱
            frame_id = result_json.get('frame_id')
            timestamp = result_json.get('timestamp')
            detections = result_json.get('detections', [])
            
            print("-----------------------------------------------------")
            print(f"[✅ TCP 수신] 3. AI_Server -> {self.name}: frame_id={frame_id}, timestamp={timestamp}, dets={len(detections)}건")

            now = time.time()
            # 각 탐지 결과에 'case' 정보 추가
            for det in detections:
                det['case'] = self.CASE_MAPPING.get(det.get('label'))

            # 시간 윈도우(deque)에 현재 탐지 결과 추가
            self.detection_window.append((now, [d['label'] for d in detections if d.get('label')]))
            # 윈도우 크기를 초과하는 오래된 데이터 제거
            while self.detection_window and now - self.detection_window[0][0] > self.WINDOW_SECONDS:
                self.detection_window.popleft()

            # 안정성 분석 및 상태 업데이트 수행
            self._update_robot_state_based_on_stability()
            
            # 처리된 데이터를 DataMerger로 전송하기 위해 큐에 삽입
            print(f"[➡️ 큐 입력] 4. {self.name} -> DataMerger: frame_id={frame_id}, timestamp={timestamp}")
            self.output_queue.put(result_json)

        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"[{self.name}] JSON 파싱 오류: {e}")

    def _update_robot_state_based_on_stability(self):
        """시간 윈도우 내의 데이터를 분석하여 로봇 상태를 'detected'로 변경할지 결정."""
        # 이미 'detected' 상태이면 추가 분석 불필요
        if self.robot_status.get('state') == 'detected':
            return

        # 'patrolling' 모드 진입 후 워밍업 시간이 지나지 않았으면 분석 중단
        if self.patrol_mode_start_time is None or \
           time.time() - self.patrol_mode_start_time < self.PATROL_WARM_UP_SECONDS:
            return

        # 안정성 분석을 위한 최소 프레임 수를 충족하지 못하면 중단
        total_frames = len(self.detection_window)
        if total_frames < self.MIN_FRAMES_FOR_STABILITY_CHECK:
            return

        # 시간 윈도우 내의 모든 탐지된 객체 레이블을 하나의 리스트로 통합
        recent_classes = [cls for _, classes in self.detection_window for cls in classes]
        if not recent_classes: return

        # 가장 빈번하게 나타난 객체부터 순서대로 안정성 검사
        counter = Counter(recent_classes)
        for label, count in counter.most_common():
            if label not in self.CASE_MAPPING: continue # 유의미한 이벤트 대상이 아니면 건너뛰기
            
            stability = count / total_frames # 안정도 계산
            if stability >= self.STABILITY_THRESHOLD: # 안정도가 임계값을 넘으면
                print("\n=====================================================")
                print(f"[🚨 안정적 탐지!] '{label}' 객체가 {self.WINDOW_SECONDS}초 내 {stability:.2%}의 안정도로 탐지됨.")
                print(f"[🚦 시스템 상태] {self.name}: 상태 변경: patrolling -> detected")
                print("=====================================================\n")
                self.robot_status['state'] = 'detected' # 로봇 상태를 'detected'로 변경
                self.last_detected_label = label
                break # 하나의 안정적인 이벤트만 처리하고 루프 종료
            
    def stop(self):
        """스레드를 안전하게 종료."""
        self.running = False
        if self.server_socket:
            self.server_socket.close() # 서버 소켓을 닫아 run 루프의 accept()에서 빠져나오게 함
        print(f"\n[{self.name}] 종료 요청 수신.")