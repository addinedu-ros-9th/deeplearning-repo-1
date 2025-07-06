import cv2
import cv2.aruco as aruco

# 사용할 ArUco 딕셔너리 로드 (예: 4x4_250)
aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_250)

# 생성할 마커의 ID와 크기 설정 (픽셀 단위)
marker_id = 10 # A 지역을 위한 마커 ID
marker_size_pixels = 200 # 생성될 이미지의 크기 (200x200 픽셀)

# ArUco 마커 생성
marker_image = aruco.generateImageMarker(aruco_dict, marker_id, marker_size_pixels)

# 이미지 저장
cv2.imwrite(f"data/aruco_marker_id_{marker_id}.png", marker_image)
print(f"ArUco Marker ID {marker_id} saved as aruco_marker_id_{marker_id}.png")

# B 지역을 위한 다른 마커 ID 생성 예시
marker_id_B = 20
marker_image_B = aruco.generateImageMarker(aruco_dict, marker_id_B, marker_size_pixels)
cv2.imwrite(f"data/aruco_marker_id_{marker_id_B}.png", marker_image_B)
print(f"ArUco Marker ID {marker_id_B} saved as aruco_marker_id_{marker_id_B}.png")

marker_id_home = 30
marker_image_home = aruco.generateImageMarker(aruco_dict, marker_id_home, marker_size_pixels)
cv2.imwrite(f"data/aruco_marker_id_{marker_id_home}.png", marker_image_home)
print(f"ArUco Marker ID {marker_id_home} saved as aruco_marker_id_{marker_id_home}.png")