import pathlib
import sys
import time

from draw_utils import *
from facemesh import *
from kalman import *

ENABLE_EDGETPU = True

MODEL_PATH = pathlib.Path("./models/")
if ENABLE_EDGETPU:
    DETECT_MODEL = "cocompile/face_detection_front_128_full_integer_quant_edgetpu.tflite"
    MESH_MODEL = "cocompile/face_landmark_192_full_integer_quant_edgetpu.tflite"
else:
    DETECT_MODEL = "face_detection_front.tflite"
    MESH_MODEL = "face_landmark.tflite"

# turn on camera
cap = cv2.VideoCapture(1)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
ret, init_image = cap.read()
if not ret:
    sys.exit(-1)

# instantiate face models
face_detector = FaceDetector(model_path=str(MODEL_PATH / DETECT_MODEL), edgetpu=ENABLE_EDGETPU)
face_mesher = FaceMesher(model_path=str((MODEL_PATH / MESH_MODEL)), edgetpu=ENABLE_EDGETPU)
face_aligner = FaceAligner(desiredLeftEye=(0.38, 0.38))
face_pose_decoder = FacePoseDecoder(init_image.shape)

# Introduce scalar stabilizers for pose.
pose_stabilizers = [Stabilizer(
    initial_state=[0, 0, 0, 0],
    input_dim=2,
    cov_process=0.2,
    cov_measure=2) for _ in range(6)]


# detect single frame
def detect_single(image):
    # pad image
    h, w, _ = image.shape
    target_dim = max(w, h)
    padded_size = [(target_dim - h) // 2,
                   (target_dim - h + 1) // 2,
                   (target_dim - w) // 2,
                   (target_dim - w + 1) // 2]
    padded = cv2.copyMakeBorder(image.copy(),
                                *padded_size,
                                cv2.BORDER_CONSTANT,
                                value=[0, 0, 0])
    padded = cv2.flip(padded, 3)

    # face detection
    bboxes_decoded, landmarks, scores = face_detector.inference(padded)

    mesh_landmarks_inverse = []
    r_vecs, t_vecs = [], []
    for i, (bbox, landmark) in enumerate(zip(bboxes_decoded, landmarks)):
        # landmark detection
        aligned_face, M = face_aligner.align(padded, landmark)
        mesh_landmark, _ = face_mesher.inference(aligned_face)
        mesh_landmark_inverse = face_aligner.inverse(mesh_landmark, M)
        mesh_landmarks_inverse.append(mesh_landmark_inverse)

        # pose detection
        r_vec, t_vec = face_pose_decoder.solve(landmark)
        r_vecs.append(r_vec)
        t_vecs.append(t_vec)

        # tracking
        if i == 0:
            landmark_stable = []
            for mark, stb in zip(landmark.reshape(-1, 2), pose_stabilizers):
                stb.update(mark)
                landmark_stable.append(stb.get_results())
            landmark_stable = np.array(landmark_stable).flatten()
            landmarks[0] = landmark_stable

    print('bboxes_decoded', bboxes_decoded, 'scores', scores)
    
    # draw
    image_show = draw_face(padded, bboxes_decoded, landmarks, scores, confidence=True)
    for i, mesh_landmark_inverse in enumerate(mesh_landmarks_inverse):
        image_show = draw_mesh(image_show, mesh_landmark_inverse, contour=True)
    for i, (r_vec, t_vec) in enumerate(zip(r_vecs, t_vecs)):
        image_show = draw_pose(image_show, r_vec, t_vec, face_pose_decoder.camera_matrix, face_pose_decoder.dist_coeffs)

    # remove pad
    image_show = image_show[padded_size[0]:target_dim - padded_size[1], padded_size[2]:target_dim - padded_size[3]]
    return image_show


# endless loop
while True:
    start = time.time()
    ret, image = cap.read()
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    # detect single
    image_show = detect_single(image)

    # put fps
    image_show = put_fps(image_show, 1 / (time.time() - start))
    result = cv2.cvtColor(image_show, cv2.COLOR_RGB2BGR)

    # cv2.imshow('demo', result)

    # if cv2.waitKey(1) & 0xFF == ord('q'):
    #     break
