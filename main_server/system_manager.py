# main_server/system_manager.py
import socket, threading, queue, time, json, cv2, numpy as np
from .db_manager import DBManager
from .image_manager import ImageManager
# RobotCommander를 임포트합니다.
from .robot_commander import RobotCommander
from shared.protocols import parse_message, create_response

class SystemManager:
    def __init__(self, host='0.0.0.0', port=9999):
        # GUI용 서버 소켓 설정
        self.gui_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.gui_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.gui_server_socket.bind((host, port))
        
        # 로봇용 서버 소켓 설정
        self.robot_command_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # 로봇 제어기, GUI 연결 정보
        self.robot_command_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.robot_command_socket.bind((host, 9996)) # 로봇 클라이언트는 포트 번호 9996을 사용할 것
        
        # 클라이언트 및 상태 관리
        self.robot_commander, self.gui_connections = None, {}  # 아직 아무런 연결도 안 된 초기 상태
        self.lock = threading.Lock() # 스레드들이 동시에 하나의 데이터에 접근하지 않게 막기 위한 안전장치
        self.aruco_detection_enabled = False # ArUco 마커 인식 활성화 플래그

        # DB 관리 모듈 초기화
        db_config = {"host": "34.47.96.177", "user": "root", "password": "qwer1234!@#$", "database": "neighbot_db"}
        self.db_manager = DBManager(db_config)
        
        # 프레임 처리용 큐 및 이미지 처리기 초기화
        self.video_frame_queue = queue.Queue(maxsize=30) # 최대 30장까지만 프레임 큐에 쌓이도록 설정
        self.image_manager = ImageManager(frame_queue=self.video_frame_queue)
        
        # ArUco 마커 인식기 초기화
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        self.aruco_params = cv2.aruco.DetectorParameters()
        self.aruco_detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.aruco_params)

        print("[서버] System Manager 초기화 완료.")

    def start(self): # image_manager 및 모든 스레드 시작 (얘는 system_launcher.py 에 의해 실행됨!)
        self.image_manager.start() # image_manager.py 내에 따로 Thread 있음
        threading.Thread(target=self._accept_gui_connections, daemon=True).start() #daemon=True로 프로그램이 꺼지면 스레드도 꺼지도록 설정
        threading.Thread(target=self._accept_robot_connection, daemon=True).start()
        threading.Thread(target=self._process_video_stream, daemon=True).start()
        print("[서버] 모든 서비스 시작됨. GUI와 로봇의 연결을 기다립니다...")
        while True: time.sleep(10) # sleep 시간은 아무값이나 기능상 아무 상관 없음

    def _accept_gui_connections(self): # GUI와의 연결 수락
        self.gui_server_socket.listen()
        while True:
            conn, addr = self.gui_server_socket.accept()
            threading.Thread(target=self.handle_gui_client, args=(conn, addr), daemon=True).start() # 연결된 client 마다 새로운 thread 를 할당 (멀티 연결)

    def _accept_robot_connection(self): # 로봇과의 연결 수락
        self.robot_command_socket.listen(1) # 오직 하나의 로봇과만 연결을 하겠다!
        while True:
            conn, addr = self.robot_command_socket.accept()
            print(f"[서버] 로봇 PC와 연결됨: {addr}")
            self.robot_commander = RobotCommander(conn) # 연결에 성공한 conn에 해당한 robot_commander 생성!

    def _process_video_stream(self):
        while True:
            frame = self.video_frame_queue.get()
            if frame is None: continue

            if self.aruco_detection_enabled: # 플래그가 True일 때만 ArUco 마커를 탐지합니다.
                corners, ids, _ = self.aruco_detector.detectMarkers(frame)
                
                if ids is not None: # 마커를 하나라도 감지하면 '도착'으로 간주합니다.
                    self.aruco_detection_enabled = False # 도착했으므로 마커 인식을 비활성화합니다.
                    print("[서버] 목적지 도착. ArUco 마커 인식을 비활성화합니다.")
                    
                    for marker_id in ids: # GUI에 도착 이벤트를 전송합니다.
                        location = f"위치 {marker_id[0]}"
                        print(f"[Aruco 탐지] ID: {marker_id[0]} 감지됨!")
                        with self.lock:
                            for event_q in self.gui_connections.values():
                                event_q.put({"type": "aruco_detection", "location": location})

    def handle_gui_client(self, conn, addr): # gui와 연결해서 이벤트(상태, 알림) 전달해주고, gui의 요청 받아서 처리해주는 애
        print(f"[서버] GUI 제어 채널 연결됨: {addr}")
        client_event_queue = queue.Queue() #나중에 _send_events_to_gui로 전송할 정보(아르코 감지등)를 미리 큐에 저장 
        with self.lock: # 잠시 다른 스레드로 부터의 접근 정지 (오류 방지)
            self.gui_connections[conn] = client_event_queue  # 클라이언트 소켓과 이벤트 큐를 딕셔너리에 저장
        
        threading.Thread(target=self._send_events_to_gui, args=(conn, client_event_queue), daemon=True).start()

        try:
            while True:
                request_bytes = conn.recv(1024)
                if not request_bytes: break  # 클라이언트가 연결을 종료한 경우
                request = parse_message(request_bytes)
                self._handle_gui_request(conn, request)
        except (BrokenPipeError, ConnectionResetError):
            print(f"[서버] GUI 클라이언트 연결 끊김: {addr}")
        finally: # 연결 종료 시 딕셔너리에서 제거하고 소켓 닫기
            with self.lock:
                if conn in self.gui_connections:
                    del self.gui_connections[conn]
            conn.close()

    def _send_events_to_gui(self, conn, event_q):  # GUI 클라이언트에게 도착 알림 같은 이벤트를 주기적으로 전송하는 함수
        while conn in self.gui_connections:  # 해당 연결이 아직 살아 있는 동안 반복
            try:
                event = event_q.get(timeout=1)  # GUI에게 보낼 이벤트가 큐에 있기를 1초간 기다려 꺼냄 (timeout 을 넣어야 프로그램이 안멈추고 계속 돌아감)
                location = event.get("location", "N/A")  # 이벤트에서 위치 정보를 추출함
                alert_message = create_response("event", f"{location}에 도착했습니다!", event)  # GUI에 보낼 JSON 응답 메시지 생성
                conn.sendall(alert_message)  # 생성한 메시지를 해당 GUI 클라이언트로 전송
            except queue.Empty:  # 큐에 아무 것도 없으면 그냥 넘김 (1초마다 반복)
                continue
            except Exception:  # 연결 끊김 등 기타 예외 발생 시 반복 종료
                break

    def _handle_gui_request(self, conn, request):  # GUI가 보낸 요청(JSON 포맷)을 받아 처리하는 함수
        req_type = request.get("type")  # 요청 타입을 확인해 어떤 명령인지 분기하기 위한 키 추출
        payload = request.get("payload")  # 요청과 함께 딸려온 실제 데이터 (명령의 상세 내용)
        response_bytes = None  # GUI에게 다시 돌려보낼 응답 메시지 변수 초기화

        if req_type == "login":  # 로그인 요청일 경우
            user_id, password = payload.get('id'), payload.get('password')  # ID와 비밀번호 추출
            success = self.db_manager.verify_user(user_id, password)  # DB를 통해 인증 시도
            msg = "로그인 성공" if success else "아이디 또는 비밀번호가 잘못되었습니다."  # 성공 여부에 따라 메시지 작성
            response_bytes = create_response("success" if success else "failed", msg)  # 결과를 JSON 응답 형식으로 포장

        # RobotCommander를 사용하여 명령을 전송합니다.
        elif req_type in ["video_control", "move_robot", "human_decision"]:  # 로봇 제어 요청인 경우
            if self.robot_commander:  # 로봇이 연결되어 있을 경우에만 처리
                success = False  # 명령 성공 여부 초기화
                if req_type == "video_control":  # 비디오 제어 요청이면
                    success = self.robot_commander.control_video(payload.get("action"))  # start/stop 명령 실행
                elif req_type == "move_robot":  # 이동 명령이면
                    self.aruco_detection_enabled = True  # 목적지 도착 감지를 위해 마커 인식 활성화
                    print("[서버] ArUco 마커 인식을 활성화합니다.")
                    success = self.robot_commander.move_to(payload.get("destination"))  # 목적지로 이동 명령 전송
                elif req_type == "human_decision":  # 수동 개입 명령이면
                    success = self.robot_commander.send_human_decision(payload.get("command"))  # 명령 전송

                if success:
                    response_bytes = create_response("success", f"'{req_type}' 명령을 로봇에 전달했습니다.")  # 성공 시 응답 메시지 생성
                else:
                    self.robot_commander = None  # 실패 시 연결 끊겼다고 간주하고 초기화
                    response_bytes = create_response("failed", "로봇 명령 전송에 실패했습니다. 연결을 확인하세요.")
            else:
                response_bytes = create_response("failed", "로봇이 연결되지 않았습니다.")  # 연결 안 된 경우 실패 메시지 전송

        if response_bytes:
            conn.sendall(response_bytes)  # 만들어진 응답 메시지를 GUI로 전송