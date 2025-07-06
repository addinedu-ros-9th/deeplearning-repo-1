# test_aruco_detection.py

import cv2
import numpy as np
import pickle
import time
import os

def load_calibration_data(filename='camera_calibration.pkl'):
    """
    카메라 캘리브레이션 데이터를 로드합니다.
    """
    try:
        with open(filename, 'rb') as f:
            calibration_data = pickle.load(f)
        print(f"Calibration data loaded successfully from {filename}")
        return calibration_data
    except FileNotFoundError:
        print(f"Error: Camera calibration file '{filename}' not found. "
              "Please ensure 'camera_calibration.pkl' is in the same directory "
              "or provide the correct path. ArUco detection will not work without it.")
        return None
    except Exception as e:
        print(f"Error loading calibration data: {e}")
        return None

def test_aruco_detection():
    """
    웹캠을 통해 ArUco 마커를 실시간으로 검출하고 Z축 거리를 표시하는 함수.
    """
    calibration_data = load_calibration_data()
    if not calibration_data:
        return

    camera_matrix = calibration_data['camera_matrix']
    dist_coeffs = calibration_data['dist_coeffs']

    # ArUco 검출기 설정
    aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_250)
    aruco_params = cv2.aruco.DetectorParameters()
    detector = cv2.aruco.ArucoDetector(aruco_dict, aruco_params)

    # 마커 크기 설정 (미터 단위). 실제 인쇄된 마커의 크기와 일치해야 합니다.
    marker_size = 0.1  # 예: 5cm = 0.05m. 실제 마커 크기에 맞게 수정하세요.

    # 웹캠 열기
    cap = cv2.VideoCapture(2) # 0번은 기본 웹캠입니다. 다른 카메라가 있다면 번호를 변경하세요 (예: 1, 2)
    if not cap.isOpened():
        print("Error: Could not open webcam.")
        return

    print("Starting ArUco marker detection test. Press 'q' to quit.")
    # 카메라 초기화 대기 (필요시)
    time.sleep(1)

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame. Exiting...")
            break

        # 이미지 왜곡 보정
        frame_undistorted = cv2.undistort(frame, camera_matrix, dist_coeffs)

        # 마커 검출
        corners, ids, rejected = detector.detectMarkers(frame_undistorted)

        # 마커가 검출되면 표시 및 포즈 추정
        if ids is not None:
            # 검출된 마커 표시
            cv2.aruco.drawDetectedMarkers(frame_undistorted, corners, ids)

            # 각 마커의 포즈 추정
            rvecs, tvecs, _ = cv2.aruco.estimatePoseSingleMarkers(
                corners, marker_size, camera_matrix, dist_coeffs
            )

            # 각 마커에 대해 처리
            for i in range(len(ids)):
                marker_id = ids[i][0]
                pos_z = tvecs[i][0][2] # Z축 거리 (깊이)

                # 좌표축 표시
                cv2.drawFrameAxes(frame_undistorted, camera_matrix, dist_coeffs,
                                rvecs[i], tvecs[i], marker_size/2)

                # 마커 정보 표시
                corner = corners[i][0]
                center_x = int(np.mean(corner[:, 0]))
                center_y = int(np.mean(corner[:, 1]))

                cv2.putText(frame_undistorted,
                          f"ID: {marker_id}",
                          (center_x, center_y - 40),
                          cv2.FONT_HERSHEY_SIMPLEX,
                          0.5, (0, 255, 0), 2) # ID는 초록색
                          
                cv2.putText(frame_undistorted,
                          f"Z-Dist: {pos_z:.2f}m",
                          (center_x, center_y - 20),
                          cv2.FONT_HERSHEY_SIMPLEX,
                          0.5, (0, 0, 255), 2) # Z축 거리는 빨간색

                # 1m 이내 감지 여부 표시
                if abs(pos_z) <= 1.0:
                    cv2.putText(frame_undistorted,
                              "CLOSE (<1m)!",
                              (center_x - 30, center_y + 10),
                              cv2.FONT_HERSHEY_SIMPLEX,
                              0.6, (255, 0, 0), 2) # 파란색으로 "CLOSE" 표시

        # 프레임 표시
        cv2.imshow('ArUco Marker Detection Test', frame_undistorted)

        # 'q' 키를 누르면 종료
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # 리소스 해제
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    # 이 스크립트를 실행하기 전에 'camera_calibration.pkl' 파일이 준비되어 있어야 합니다.
    # 해당 파일은 카메라 캘리브레이션을 통해 얻은 결과입니다.
    test_aruco_detection()