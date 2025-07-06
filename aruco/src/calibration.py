import cv2
import datetime

# 카메라 장치 열기
cap = cv2.VideoCapture(2)

# 영상 캡처 루프
while True:
    # 프레임 읽기
    ret, frame = cap.read()
    if not ret:
        print("카메라에서 프레임을 가져올 수 없습니다.")
        break

    # 프레임을 화면에 표시
    cv2.imshow("Video", frame)

    # 키 입력 대기
    key = cv2.waitKey(1) & 0xFF

    # 'a' 키를 누르면 프레임 캡처하여 저장
    if key == ord('a'):
        # 파일 이름에 현재 날짜와 시간을 추가하여 저장
        filename = datetime.datetime.now().strftime("./capture_%Y%m%d_%H%M%S.png")
        cv2.imwrite(filename, frame)
        print(f"{filename} 이미지가 저장되었습니다.")

    # 'q' 키를 누르면 종료
    elif key == ord('q'):
        break

# 자원 해제
cap.release()
cv2.destroyAllWindows()