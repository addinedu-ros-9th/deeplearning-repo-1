# main_server/system_manager.py
import socket, threading, queue, time, json, cv2, numpy as np
from .db_manager import DBManager
from .image_manager import ImageManager
# RobotCommander를 임포트합니다.
from .robot_commander import RobotCommander
from shared.protocols import parse_message, create_response

class SystemManager:
    def __init__(self, host='0.0.0.0', port=9999):
        # 통신 소켓 설정
        self.gui_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.gui_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.gui_server_socket.bind((host, port))
        
        self.robot_command_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.robot_command_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.robot_command_socket.bind((host, 9996))
        
        # 클라이언트 및 상태 관리
        # robot_connection 대신 robot_commander를 사용합니다.
        self.robot_commander, self.gui_connections = None, {}
        self.lock = threading.Lock()
        self.aruco_detection_enabled = False # ArUco 마커 인식 활성화 플래그

        # 핵심 로직 모듈 초기화
        db_config = {"host": "34.47.96.177", "user": "root", "password": "qwer1234!@#$", "database": "neighbot_db"}
        self.db_manager = DBManager(db_config)
        
        self.video_frame_queue = queue.Queue(maxsize=30)
        self.image_manager = ImageManager(frame_queue=self.video_frame_queue)
        
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        self.aruco_params = cv2.aruco.DetectorParameters()
        self.aruco_detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.aruco_params)

        print("[서버] System Manager 초기화 완료.")

    def start(self):
        self.image_manager.start()
        threading.Thread(target=self._accept_gui_connections, daemon=True).start()
        threading.Thread(target=self._accept_robot_connection, daemon=True).start()
        threading.Thread(target=self._process_video_stream, daemon=True).start()
        print("[서버] 모든 서비스 시작됨. GUI와 로봇의 연결을 기다립니다...")
        while True: time.sleep(10)

    def _accept_gui_connections(self):
        self.gui_server_socket.listen()
        while True:
            conn, addr = self.gui_server_socket.accept()
            threading.Thread(target=self.handle_gui_client, args=(conn, addr), daemon=True).start()

    def _accept_robot_connection(self):
        self.robot_command_socket.listen(1)
        while True:
            conn, addr = self.robot_command_socket.accept()
            print(f"[서버] 로봇 PC와 연결됨: {addr}")
            # 로봇이 연결되면 RobotCommander 인스턴스를 생성합니다.
            self.robot_commander = RobotCommander(conn)

    def _process_video_stream(self):
        while True:
            frame = self.video_frame_queue.get()
            if frame is None: continue

            # 플래그가 True일 때만 ArUco 마커를 탐지합니다.
            if self.aruco_detection_enabled:
                corners, ids, _ = self.aruco_detector.detectMarkers(frame)
                
                # 마커를 하나라도 감지하면 '도착'으로 간주합니다.
                if ids is not None:
                    # 도착했으므로 마커 인식을 비활성화합니다.
                    self.aruco_detection_enabled = False
                    print("[서버] 목적지 도착. ArUco 마커 인식을 비활성화합니다.")
                    
                    # GUI에 도착 이벤트를 전송합니다.
                    for marker_id in ids:
                        location = f"위치 {marker_id[0]}"
                        print(f"[Aruco 탐지] ID: {marker_id[0]} 감지됨!")
                        with self.lock:
                            for event_q in self.gui_connections.values():
                                event_q.put({"type": "aruco_detection", "location": location})

    def handle_gui_client(self, conn, addr):
        print(f"[서버] GUI 제어 채널 연결됨: {addr}")
        client_event_queue = queue.Queue()
        with self.lock:
            self.gui_connections[conn] = client_event_queue
        
        event_thread = threading.Thread(target=self._send_events_to_gui, args=(conn, client_event_queue), daemon=True)
        event_thread.start()
        try:
            while True:
                request_bytes = conn.recv(1024)
                if not request_bytes: break
                request = parse_message(request_bytes)
                self._handle_gui_request(conn, request)
        except (BrokenPipeError, ConnectionResetError):
            print(f"[서버] GUI 클라이언트 연결 끊김: {addr}")
        finally:
            with self.lock:
                if conn in self.gui_connections:
                    del self.gui_connections[conn]
            conn.close()

    def _send_events_to_gui(self, conn, event_q):
        while conn in self.gui_connections:
            try:
                event = event_q.get(timeout=1)
                location = event.get("location", "N/A")
                alert_message = create_response("event", f"{location}에 도착했습니다!", event)
                conn.sendall(alert_message)
            except queue.Empty:
                continue
            except Exception:
                break

    def _handle_gui_request(self, conn, request):
        req_type = request.get("type")
        payload = request.get("payload")
        response_bytes = None
        
        if req_type == "login":
            user_id, password = payload.get('id'), payload.get('password')
            success = self.db_manager.verify_user(user_id, password)
            msg = "로그인 성공" if success else "아이디 또는 비밀번호가 잘못되었습니다."
            response_bytes = create_response("success" if success else "failed", msg)
        
        # RobotCommander를 사용하여 명령을 전송합니다.
        elif req_type in ["video_control", "move_robot", "human_decision"]:
            if self.robot_commander:
                success = False
                if req_type == "video_control":
                    success = self.robot_commander.control_video(payload.get("action"))
                
                elif req_type == "move_robot":
                    # 이동 명령 시, ArUco 인식 활성화 (SystemManager의 의사결정)
                    self.aruco_detection_enabled = True
                    print("[서버] ArUco 마커 인식을 활성화합니다.")
                    success = self.robot_commander.move_to(payload.get("destination"))
                
                elif req_type == "human_decision":
                    success = self.robot_commander.send_human_decision(payload.get("command"))

                if success:
                    response_bytes = create_response("success", f"'{req_type}' 명령을 로봇에 전달했습니다.")
                else:
                    # 전송 실패 시, commander 내부에서 연결이 끊어졌을 수 있음
                    self.robot_commander = None
                    response_bytes = create_response("failed", "로봇 명령 전송에 실패했습니다. 연결을 확인하세요.")
            else:
                response_bytes = create_response("failed", "로봇이 연결되지 않았습니다.")
        
        if response_bytes:
            conn.sendall(response_bytes)