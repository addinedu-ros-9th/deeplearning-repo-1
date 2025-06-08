# robot_app/robot_launcher.py
import threading
import time
from .communication.image_sender import ImageSender
from .communication.command_receiver import CommandReceiver

class RobotApplication:
    def __init__(self):
        print("로봇 애플리케이션을 시작합니다...")
        self.image_sender = ImageSender()
        self.command_receiver = CommandReceiver(self.image_sender)
        self.command_thread = None

    def start(self):
        # 명령 수신기는 항상 동작해야 하므로 스레드로 실행
        self.command_thread = threading.Thread(target=self.command_receiver.listen, daemon=True)
        self.command_thread.start()
        print("모든 로봇 서비스가 시작되었습니다.")
        
    def stop(self):
        """Ctrl+C 입력 시 호출될 전체 종료 메서드"""
        print("\n종료 절차를 시작합니다...")
        self.command_receiver.stop()
        self.image_sender.close()
        if self.command_thread and self.command_thread.is_alive():
            self.command_thread.join(timeout=1)
        print("모든 서비스가 안전하게 종료되었습니다.")

if __name__ == '__main__':
    robot_app = RobotApplication()
    robot_app.start()
    try:
        # 메인 스레드는 프로그램이 종료될 때까지 대기
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        robot_app.stop()


# python -m robot_app.robot_launcher