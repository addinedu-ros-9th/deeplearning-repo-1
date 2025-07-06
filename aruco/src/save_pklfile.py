# calibrate_camera.py

import cv2
import numpy as np
import pickle
import glob
import time

# 체스보드 패턴 설정
# (width, height) = (내부 코너의 가로 개수, 내부 코너의 세로 개수)
# 예를 들어 9x6 체스보드 패턴이면 내부 코너는 8x5 입니다.
CHECKERBOARD = (10, 7) # 실제 사용하는 체스보드 패턴의 내부 코너 개수에 맞게 수정!
square_size = 0.025 # 체스보드 한 칸의 실제 크기 (미터 단위). 예를 들어 2.5cm = 0.025m

# 객체 점과 이미지 점을 저장할 리스트
objpoints = [] # 3D 공간의 실제 점들
imgpoints = [] # 2D 이미지 평면의 해당 점들

# 체스보드 코너의 3D 좌표 (Z=0 평면에 있다고 가정)
objp = np.zeros((CHECKERBOARD[0] * CHECKERBOARD[1], 3), np.float32)
objp[:, :2] = np.mgrid[0:CHECKERBOARD[0], 0:CHECKERBOARD[1]].T.reshape(-1, 2) * square_size

# 웹캠 열기
cap = cv2.VideoCapture(2) # 0은 기본 웹캠. 다른 카메라를 사용하려면 변경

if not cap.isOpened():
    print("Error: Could not open webcam.")
    exit()

criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)

print("Press 'c' to capture a frame for calibration.")
print("Capture at least 10-15 good frames from different angles and distances.")
print("Press 'q' to quit (capturing will stop, but calibration won't be saved if not enough frames).")

captured_frames_count = 0

while True:
    ret, frame = cap.read()
    if not ret:
        print("Failed to grab frame.")
        break

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # 체스보드 코너 찾기
    ret_corners, corners = cv2.findChessboardCorners(gray, CHECKERBOARD, None)

    # 코너를 찾았으면 objpoints, imgpoints에 추가
    if ret_corners:
        cv2.drawChessboardCorners(frame, CHECKERBOARD, corners, ret_corners)

    cv2.imshow('Calibration - Press "c" to capture, "q" to quit', frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('c'):
        if ret_corners:
            objpoints.append(objp)
            corners2 = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            imgpoints.append(corners2)
            captured_frames_count += 1
            print(f"Captured frame {captured_frames_count}. Total points: {len(objpoints)}")
            # 캡처 성공 시 잠시 대기하여 연속 캡처 방지
            time.sleep(1)
        else:
            print("No chessboard corners found in this frame. Try again.")
    elif key == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()

if len(objpoints) > 5: # 최소한 5장 이상의 프레임이 필요
    print(f"\nCalibrating camera with {len(objpoints)} frames...")
    # 카메라 캘리브레이션 수행
    ret, camera_matrix, dist_coeffs, rvecs, tvecs = cv2.calibrateCamera(
        objpoints, imgpoints, gray.shape[::-1], None, None
    )

    if ret:
        print("Camera calibration successful!")
        calibration_data = {
            'camera_matrix': camera_matrix,
            'dist_coeffs': dist_coeffs
        }
        # 캘리브레이션 데이터 저장
        with open('camera_calibration.pkl', 'wb') as f:
            pickle.dump(calibration_data, f)
        print("Calibration data saved to camera_calibration.pkl")
        print("Camera Matrix:\n", camera_matrix)
        print("Distortion Coefficients:\n", dist_coeffs)
    else:
        print("Camera calibration failed.")
else:
    print("Not enough frames captured for calibration. Need at least 5 frames.")