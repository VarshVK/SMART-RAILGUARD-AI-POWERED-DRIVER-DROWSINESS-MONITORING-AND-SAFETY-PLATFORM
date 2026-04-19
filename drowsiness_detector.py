import cv2
import mediapipe as mp
import numpy as np
import time
import threading
import requests
import pygame
import os
import pyttsx3

# ---------------- AUDIO ----------------
pygame.mixer.init()
engine = pyttsx3.init()
engine.setProperty('rate', 150)

def voice_alert():
    engine.say("Wake up driver")
    engine.runAndWait()

def play_alert():
    if os.path.exists("alert.wav"):
        pygame.mixer.music.load("alert.wav")
        pygame.mixer.music.play(-1)

def stop_alert():
    pygame.mixer.music.stop()

# ---------------- MEDIAPIPE ----------------
mp_face = mp.solutions.face_mesh
face_mesh = mp_face.FaceMesh(refine_landmarks=True)

LEFT_EYE  = [33,160,158,133,153,144]
RIGHT_EYE = [362,385,387,263,373,380]

def eye_aspect_ratio(eye, lm, w, h):
    pts = [(lm[i].x*w, lm[i].y*h) for i in eye]
    pts = np.array(pts)

    v1 = np.linalg.norm(pts[1]-pts[5])
    v2 = np.linalg.norm(pts[2]-pts[4])
    h1 = np.linalg.norm(pts[0]-pts[3])

    return (v1+v2)/(2*h1) if h1>0 else 0.3

# ---------------- VARIABLES ----------------
eye_closed_start = None
alarm_on = False

ear_buffer = []
SMOOTH_N = 5

baseline_ear = None
calib_ears = []

blink_count = 0
blink_detected = False

# TIME TRACKING
last_time = time.time()
safe_time = 0
drowsy_time = 0
safety_score = 100

cap = cv2.VideoCapture(0)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    h, w = frame.shape[:2]
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    result = face_mesh.process(rgb)

    # -------- FACE DETECTION SAFE BLOCK --------
    if result.multi_face_landmarks:

        lm = result.multi_face_landmarks[0].landmark

    # 👉 ONLY HERE do EAR, tilt, etc.

    else:
        status = "NO DRIVER"
        ear_avg = 0
        eye_closed_start = None

    # display
        cv2.putText(frame, "NO DRIVER", (40,80),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,255), 3)

        cv2.imshow("RailGuard AI", frame)

        if cv2.waitKey(1) == 27:
            break

        continue   # 🔥 skip rest of loop safely
    
    # -------- HEAD TILT --------
    tilt = abs(lm[33].y - lm[263].y)
    head_tilt = tilt > 0.07

    # -------- EAR --------
    left = eye_aspect_ratio(LEFT_EYE, lm, w, h)
    right = eye_aspect_ratio(RIGHT_EYE, lm, w, h)
    ear = (left + right)/2

    ear_buffer.append(ear)
    if len(ear_buffer) > SMOOTH_N:
        ear_buffer.pop(0)

    ear_avg = np.mean(ear_buffer)

    # -------- CALIBRATION --------
    if baseline_ear is None:
        calib_ears.append(ear_avg)
        cv2.putText(frame, "Calibrating...", (40,120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,255), 2)

        if len(calib_ears) >= 40:
            baseline_ear = np.median(calib_ears)
            EAR_THRESHOLD = baseline_ear * 0.90
            print("Calibrated:", baseline_ear)

        cv2.imshow("RailGuard", frame)
        continue

    # -------- BLINK --------
    if ear_avg < EAR_THRESHOLD:
        if not blink_detected:
            blink_count += 1
            blink_detected = True
    else:
        blink_detected = False

    # -------- DROWSINESS (STABLE) --------
    CLOSE_THRESHOLD = EAR_THRESHOLD + 0.02

    if ear_avg < CLOSE_THRESHOLD:
        if eye_closed_start is None:
            eye_closed_start = time.time()
        elapsed = time.time() - eye_closed_start
    else:
        if eye_closed_start is not None and (time.time() - eye_closed_start < 0.7):
            elapsed = time.time() - eye_closed_start
        else:
            eye_closed_start = None
            elapsed = 0

    # -------- STATUS --------
    if elapsed > 10 and head_tilt:
        status = "CRITICAL"
    elif elapsed > 10:
        status = "CRITICAL"
    elif elapsed > 5:
        status = "DROWSY"
    elif head_tilt:
        status = "HEAD TILT"
    else:
        status = "SAFE"

    # -------- ALERT (>10 sec) --------
    if elapsed >= 10:
        if not alarm_on:
            print("🚨 ALERT TRIGGERED")
            alarm_on = True
            threading.Thread(target=play_alert, daemon=True).start()
            threading.Thread(target=voice_alert, daemon=True).start()
    else:
        if alarm_on:
            stop_alert()
        alarm_on = False

    # -------- TIME TRACKING --------
    current_time = time.time()
    delta = current_time - last_time
    last_time = current_time

    if status == "SAFE":
        safe_time += delta
    else:
        drowsy_time += delta

    total_time = safe_time + drowsy_time

    # -------- SEND DATA EVERY 30 SEC --------

    if status == "NO DRIVER":
        actual = "NO DRIVER"
    elif elapsed > 10:
        actual = "DROWSY"
    else:
        actual = "SAFE"
    # 🔥 Normalize prediction
    #pred_label = "DROWSY" if status in ["DROWSY","HIGH RISK","CRITICAL"] else "SAFE"
    if status == "NO DRIVER":
        pred_label = "NO DRIVER"
    elif status in ["DROWSY","HIGH RISK","CRITICAL"]:
        pred_label = "DROWSY"
    else:
        pred_label = "SAFE"
    if total_time >= 30:
        safety_score = round((safe_time / total_time) * 100, 1)

        print("🔥 SENDING DATA:", safety_score)

        try:
            requests.post("http://127.0.0.1:5000/log", json={
                "status": status,
                "ear": float(ear_avg),
                "mar": 0,
                "score": float(safety_score),
                "actual": actual   # 🔥 ADD THIS
            })
        except Exception as e:
            print("POST ERROR:", e)

        safe_time = 0
        drowsy_time = 0

    # -------- DISPLAY --------
    color = (0,255,0) if status=="SAFE" else (0,0,255)

    cv2.putText(frame, f"STATUS: {status}", (40,40),
                cv2.FONT_HERSHEY_SIMPLEX, 1, color, 3)

    cv2.putText(frame, f"EAR: {ear_avg:.2f}", (40,80),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)

    cv2.putText(frame, f"Blinks: {blink_count}", (40,110),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)

    cv2.putText(frame, f"Score: {safety_score}%", (40,140),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)

    if head_tilt:
        cv2.putText(frame, "HEAD TILT", (40,170),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,165,255), 2)

    cv2.imshow("RailGuard AI", frame)

    if cv2.waitKey(1)==27:
        break

cap.release()
cv2.destroyAllWindows()