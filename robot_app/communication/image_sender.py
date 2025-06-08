# robot_app/communication/image_sender.py
import cv2, socket, time
# [수정] import config -> from .. import config
from .. import config
import threading

class ImageSender:
    def __init__(self):
        self.server_address = (config.MAIN_SERVER_IP, config.VIDEO_PORT)
        self.jpeg_quality = config.JPEG_QUALITY
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.cap = cv2.VideoCapture(config.CAMERA_INDEX)
        if not self.cap.isOpened(): raise IOError("카메라 열기 실패")
        print(f"카메라 영상 전송 시작 -> {self.server_address}")
        self._is_streaming = False
        self._thread = None

    def start_streaming(self):
        if not self._is_streaming:
            self._is_streaming = True
            self._thread = threading.Thread(target=self._stream_loop, daemon=True)
            self._thread.start()
            print("[영상] 스트리밍 시작됨.")

    def stop_streaming(self):
        self._is_streaming = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1) # 스레드가 끝날 때까지 잠시 대기
        print("[영상] 스트리밍 중지됨.")

    def _stream_loop(self):
        while self._is_streaming:
            try:
                ret, frame = self.cap.read()
                if not ret: break
                _, encoded_frame = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
                self.socket.sendto(encoded_frame, self.server_address)
                time.sleep(0.03) # ~30fps
            except Exception as e:
                print(f"영상 전송 오류: {e}")
                break
        print("[영상] 스트리밍 루프 종료.")

    # 프로그램 종료 시 자원 해제
    def close(self):
        self.stop_streaming()
        self.cap.release()
        self.socket.close()