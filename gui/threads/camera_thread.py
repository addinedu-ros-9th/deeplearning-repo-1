import cv2
from PyQt5.QtCore import QThread, pyqtSignal, Qt # Qt는 여기서 직접 사용 안하면 빼도 됨
from PyQt5.QtGui import QImage

class CameraThread(QThread):
    change_pixmap_signal = pyqtSignal(QImage)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._run_flag = True
        self.cap = None

    def run(self):
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            print("카메라를 열 수 없습니다.")
            return

        while self._run_flag and self.cap.isOpened(): # 바깥 루프에서 _run_flag 체크
            ret, frame = self.cap.read()
            if ret:
                # 프레임 처리... (BGR to RGB, QImage 생성 등)
                rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_image.shape
                bytes_per_line = ch * w
                qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
                
                # emit 직전에 한 번 더 _run_flag 확인
                if self._run_flag:
                    self.change_pixmap_signal.emit(qt_image)
            
            # msleep은 스레드 자체를 잠시 멈추므로 _run_flag 상태 변경을 즉시 반영하지 못할 수 있으나,
            # 루프 시작 시점에 _run_flag를 체크하므로 큰 문제는 되지 않음.
            # 좀 더 반응성을 높이려면 msleep 시간을 줄이거나 다른 방식을 고려.
            self.msleep(30) 

        if self.cap:
            self.cap.release()
        print("카메라 스레드 종료 (자원 해제됨)")

    def stop(self):
        self._run_flag = False
        # self.wait() # 필요시 주석 해제