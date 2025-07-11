# gui/src/detection_dialog.py
"""
탐지 다이얼로그 모듈
- 로봇이 탐지한 객체나 상황 정보를 사용자에게 표시
- 사용자가 무시하거나 조치를 취할 수 있는 인터페이스 제공
"""

# 표준 라이브러리 임포트
import traceback

# PyQt5 관련 임포트
from PyQt5.QtWidgets import QDialog
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.uic import loadUi

class DetectionDialog(QDialog):
    """탐지 결과를 표시하는 팝업 다이얼로그"""
    
    # 사용자 응답에 대한 시그널 (응답유형, 탐지정보)
    response_signal = pyqtSignal(str, dict)  # "PROCEED"/"IGNORE", 탐지정보
    
    def __init__(self, parent=None, detection=None, image_data=None, user_name=None):
        super().__init__(parent)
        self.detection = detection
        self.image_data = image_data
        self.user_name = user_name or "사용자"  # 사용자 이름 (기본값: "사용자")
        self.init_ui()
        
    def init_ui(self):
        try:
            # UI 파일 로드
            loadUi('./gui/ui/detection_dialog3.ui', self)
            
            # 다이얼로그 제목 설정
            self.setWindowTitle(self.get_dialog_title())
            
            # 이미지 표시
            if self.image_data:
                pixmap = QPixmap()
                if pixmap.loadFromData(self.image_data):
                    scaled_pixmap = pixmap.scaled(
                        self.image_label.width(), 
                        self.image_label.height(), 
                        Qt.KeepAspectRatio, 
                        Qt.SmoothTransformation
                    )
                    self.image_label.setPixmap(scaled_pixmap)
                    self.image_label.setAlignment(Qt.AlignCenter)
            else:
                self.image_label.setText("이미지 없음")
                self.image_label.setAlignment(Qt.AlignCenter)
            
            # 탐지 정보 표시
            self.label_and_case_info.setText(self.get_detection_info())
            
            # 질문 설정
            self.question.setText(f"{self.user_name}님, 자세히 확인하시겠습니까?")
            
            # 버튼 연결
            self.btn_ignore.clicked.connect(lambda: self.handle_response("IGNORE"))
            self.btn_proceed.clicked.connect(lambda: self.handle_response("PROCEED"))
            
            print("탐지 다이얼로그 초기화 완료")
            
        except Exception as e:
            print(f"탐지 다이얼로그 초기화 실패: {e}")
            print(traceback.format_exc())
    
    def closeEvent(self, event):
        """X 버튼을 눌러 다이얼로그를 닫을 경우 IGNORE로 처리"""
        # 명시적으로 closeEvent가 호출되었을 때 (X 버튼 클릭 시)
        # 아직 응답이 처리되지 않았다면 IGNORE로 처리
        print("X 버튼으로 다이얼로그 종료 - IGNORE로 처리")
        self.handle_response("IGNORE")
        event.accept()  # 이벤트 수락 (창 닫기)
    
    def get_dialog_title(self):
        """다이얼로그 제목 생성"""
        try:
            if not self.detection:
                return "탐지 알림"
                
            case = self.detection.get('case', '알 수 없음')
            label = self.detection.get('label', '알 수 없음')
            
            case_str = {
                'danger': '위험',
                'illegal': '위법',
                'emergency': '응급',
                'unknown': '알 수 없음'
            }.get(case, case)
            
            label_str = {
                'knife': '칼',
                'gun': '총',
                'fallen': '쓰러짐',
                'smoking': '흡연'
            }.get(label, label)
            
            return f"{case_str} 상태, {label_str} 검출"
        except Exception as e:
            print(f"다이얼로그 제목 생성 실패: {e}")
            return "탐지 알림"
    
    def get_detection_info(self):
        """탐지 정보 텍스트 생성"""
        try:
            if not self.detection:
                return "탐지 정보 없음"
                
            case = self.detection.get('case', '알 수 없음')
            label = self.detection.get('label', '알 수 없음')
            confidence = self.detection.get('confidence', 0.0)
            
            case_str = {
                'danger': '위험',
                'illegal': '위법',
                'emergency': '응급',
                'unknown': '알 수 없음'
            }.get(case, case)
            
            label_str = {
                'knife': '칼',
                'gun': '총',
                'fallen': '쓰러짐',
                'smoking': '흡연'
            }.get(label, label)
            
            # 정보 텍스트 구성
            info_text = f"탐지 유형: {label_str}\n"
            info_text += f"상황 분류: {case_str}\n"
            
            if isinstance(confidence, (int, float)):
                info_text += f"신뢰도: {confidence:.2f}\n"
            
            # 상황별 추가 설명
            if case == 'danger':
                info_text += "\n위험 물체가 탐지되었습니다.\n"
                info_text += "즉시 확인이 필요합니다."
            elif case == 'illegal':
                info_text += "\n위법 행위가 탐지되었습니다.\n"
                info_text += "확인 후 적절한 조치가 필요합니다."
            elif case == 'emergency':
                info_text += "\n응급 상황이 탐지되었습니다.\n"
                info_text += "신속한 확인이 필요합니다."
                
            return info_text
        except Exception as e:
            print(f"탐지 정보 생성 실패: {e}")
            return "탐지 정보 생성 중 오류 발생"
            
    def handle_response(self, response):
        """사용자 응답 처리"""
        print(f"사용자 응답: {response}")
        # 탐지 정보와 함께 응답 시그널 발생
        self.response_signal.emit(response, self.detection or {})
        self.accept()
