# main_server/system_manager.py (최종 수정 완료)

import threading
import time
import queue
from .image_manager import ImageManager
from .event_analyzer import EventAnalyzer
from .data_merger import DataMerger
from .db_manager import DBManager
from .robot_commander import RobotCommander

# --- 전역 설정 (이전과 동일) ---
ROBOT_HOST = "192.168.0.3"
IMAGE_RECV_PORT = 9001
ROBOT_CONTROLLER_PORT = 9008
AI_SERVER_HOST = "127.0.0.1"
AI_SERVER_PORT = 9002
ANALYSIS_RECV_PORT = 9003
GUI_HOST = "127.0.0.1"
GUI_MERGER_PORT = 9004
GUI_ROBOT_COMMANDER_PORT = 9006
DB_MANAGER_HOST = '0.0.0.0'
DB_MANAGER_PORT = 9005

class SystemManager:
    def __init__(self):
        DB_CONFIG = {
            'user': 'root',
            'password': 'qwer1234!@#$',
            'host': '34.47.96.177',
            'database': 'neighbot_db',
            'raise_on_warnings': True
        }
        
        # --- 공유 자원 생성 ---
        # [추가] 녹화 종료 신호 및 최종 파일명 전달을 위한 'recording_stop_signal' 키 추가
        self.robot_status = {
            'state': 'idle', 
            'target_marker_id': None,
            'recording_stop_signal': None # 이 키를 통해 DBManager가 ImageManager에 녹화 종료를 알림
        }
        print(f"[🚦 시스템 상태] SystemManager: 초기 상태를 '{self.robot_status['state']}'(으)로 설정")

        self.aruco_result_queue = queue.Queue()
        self.image_for_merger_queue = queue.Queue()
        self.event_result_queue = queue.Queue()

        # --- 컴포넌트 인스턴스 생성 및 연결 ---
        self.image_manager = ImageManager(
            listen_port=IMAGE_RECV_PORT,
            ai_server_addr=(AI_SERVER_HOST, AI_SERVER_PORT),
            image_for_merger_queue=self.image_for_merger_queue,
            robot_status=self.robot_status,
            aruco_result_queue=self.aruco_result_queue
        )
        
        self.event_analyzer = EventAnalyzer(
            listen_port=ANALYSIS_RECV_PORT,
            output_queue=self.event_result_queue,
            robot_status=self.robot_status
        )
        
        self.data_merger = DataMerger(
            image_queue=self.image_for_merger_queue,
            event_queue=self.event_result_queue,
            gui_listen_addr=(GUI_HOST, GUI_MERGER_PORT),
            robot_status=self.robot_status
        )
        
        # [추가] DBManager에 robot_status 객체 전달
        # DBManager가 ImageManager와 통신(녹화 종료 신호)하기 위해 공유 객체를 전달합니다.
        self.db_manager = DBManager(
            host=DB_MANAGER_HOST,
            port=DB_MANAGER_PORT,
            db_config=DB_CONFIG,
            robot_status=self.robot_status 
        )

        self.robot_commander = RobotCommander(
            gui_listen_port=GUI_ROBOT_COMMANDER_PORT,
            robot_controller_addr=(ROBOT_HOST, ROBOT_CONTROLLER_PORT),
            robot_status=self.robot_status,
            aruco_result_queue=self.aruco_result_queue
        )

        self.threads = [
            self.image_manager,
            self.event_analyzer,
            self.data_merger,
            self.db_manager,
            self.robot_commander
        ]
        
    def start(self):
        print("SystemManager: Starting all component threads...")
        for thread in self.threads:
            thread.start()
        print("SystemManager: All component threads started.")

    def stop(self):
        print("\nSystemManager: Stopping all component threads...")
        for thread in self.threads:
            if hasattr(thread, 'stop') and callable(getattr(thread, 'stop')):
                thread.stop()
        
        for thread in self.threads:
            thread.join()
        print("SystemManager: All component threads stopped.")

if __name__ == "__main__":
    manager = SystemManager()
    try:
        manager.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[System Manager] KeyboardInterrupt 수신. 시스템을 종료합니다.")
    finally:
        manager.stop()
        print("[System Manager] System shutdown completed.")