import time
import os
import json
import subprocess
from naoqi import ALProxy

LAPTOP_SSH = "khaled@192.168.0.178"

LAPTOP_INCOMING_DIR = "Documents/Nao_Project/incoming"
LAPTOP_OUTGOING_DIR = "Documents/Nao_Project/outgoing"
LAPTOP_IMAGES_DIR = "Documents/Nao_Project/images"

SAMPLE_RATE = 16000
CHANNELS = [0, 0, 1, 0]
FORMAT_NAME = "wav"

RECORD_SECONDS = 5
POLL_SECONDS = 0.3
RESPONSE_TIMEOUT = 20

INTRO = (
    "Hi! I am SantaNao, your English teacher. "
    "Please tell me your name and what topic you want to learn today."
)

LED_COLORS = {
    "green": 0x0000FF00,
    "blue": 0x000000FF,
    "yellow": 0x00FFFF00,
    "red": 0x00FF0000,
    "white": 0x00FFFFFF
}

def record_once(rec, out_wav):
    try:
        rec.stopMicrophonesRecording()
    except Exception:
        pass

    rec.startMicrophonesRecording(out_wav, FORMAT_NAME, SAMPLE_RATE, CHANNELS)
    time.sleep(RECORD_SECONDS)
    rec.stopMicrophonesRecording()

def take_photo(video, image_path):
    try:
        video.unsubscribe("python_client")
    except Exception:
        pass
    
    video.subscribe("python_client", 2, 11, 5)
    time.sleep(0.2)
    
    nao_image = video.getImageRemote("python_client")
    video.unsubscribe("python_client")
    
    if nao_image is None:
        print "[ERROR] Failed to capture image"
        return False
    
    width = nao_image[0]
    height = nao_image[1]
    array = nao_image[6]
    
    try:
        import Image
        im = Image.fromstring("RGB", (width, height), array)
        im.save(image_path)
        print "[INFO] Photo saved:", image_path
        return True
    except Exception as e:
        print "[ERROR] Failed to save image:", e
        return False

def scp_to_laptop(local_file, remote_name, remote_dir):
    remote_path = "%s/%s" % (remote_dir, remote_name)
    cmd = [
        "scp",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        "-q",
        local_file,
        "%s:%s" % (LAPTOP_SSH, remote_path)
    ]
    subprocess.check_call(cmd)

def scp_from_laptop(stem, local_json):
    remote_json = "%s/%s.json" % (LAPTOP_OUTGOING_DIR, stem)
    cmd = [
        "scp",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        "-q",
        "%s:%s" % (LAPTOP_SSH, remote_json),
        local_json
    ]
    try:
        with open(os.devnull, 'w') as devnull:
            subprocess.check_call(cmd, stderr=devnull)
        return True
    except subprocess.CalledProcessError:
        return False

def set_eye_color(leds, color_name):
    color = LED_COLORS.get(color_name, LED_COLORS["blue"])
    try:
        leds.fadeRGB("FaceLeds", color, 0.5)
    except Exception as e:
        print "[WARN] Could not set LED color:", e

def perform_gesture(motion, gesture_name):
    try:
        motion.setStiffnesses("Head", 1.0)
        motion.setStiffnesses("LArm", 1.0)
        motion.setStiffnesses("RArm", 1.0)
        
        if gesture_name == "wave":
            motion.setAngles("RShoulderPitch", 0.0, 0.3)
            motion.setAngles("RShoulderRoll", -0.3, 0.3)
            time.sleep(0.3)
            for _ in range(2):
                motion.setAngles("RElbowRoll", 1.5, 0.5)
                time.sleep(0.2)
                motion.setAngles("RElbowRoll", 0.5, 0.5)
                time.sleep(0.2)
            motion.setAngles(["RShoulderPitch", "RShoulderRoll", "RElbowRoll"], [1.5, 0.0, 0.0], 0.3)
            
        elif gesture_name == "nod":
            motion.setAngles("HeadPitch", 0.3, 0.3)
            time.sleep(0.3)
            motion.setAngles("HeadPitch", -0.1, 0.3)
            time.sleep(0.3)
            motion.setAngles("HeadPitch", 0.0, 0.3)
            
        elif gesture_name == "shake_head":
            motion.setAngles("HeadYaw", 0.5, 0.3)
            time.sleep(0.3)
            motion.setAngles("HeadYaw", -0.5, 0.3)
            time.sleep(0.3)
            motion.setAngles("HeadYaw", 0.0, 0.3)
            
        elif gesture_name == "look_up":
            motion.setAngles("HeadPitch", -0.3, 0.3)
            time.sleep(0.5)
            motion.setAngles("HeadPitch", 0.0, 0.3)
            
        elif gesture_name == "look_left":
            motion.setAngles("HeadYaw", 0.5, 0.3)
            time.sleep(0.5)
            motion.setAngles("HeadYaw", 0.0, 0.3)
            
        elif gesture_name == "look_right":
            motion.setAngles("HeadYaw", -0.5, 0.3)
            time.sleep(0.5)
            motion.setAngles("HeadYaw", 0.0, 0.3)
            
        elif gesture_name == "hand_open":
            motion.setAngles(["RShoulderPitch", "RElbowRoll"], [0.5, 1.0], 0.3)
            motion.setAngles("RHand", 1.0, 0.3)
            time.sleep(0.5)
            motion.setAngles(["RShoulderPitch", "RElbowRoll", "RHand"], [1.5, 0.0, 0.0], 0.3)
            
        elif gesture_name == "hand_close":
            motion.setAngles(["RShoulderPitch", "RElbowRoll"], [0.5, 1.0], 0.3)
            motion.setAngles("RHand", 0.0, 0.3)
            time.sleep(0.5)
            motion.setAngles(["RShoulderPitch", "RElbowRoll", "RHand"], [1.5, 0.0, 0.0], 0.3)
        
        time.sleep(0.2)
        
    except Exception as e:
        print "[WARN] Gesture error:", e

def say_and_move(tts, motion, leds, speech, gestures, led_color):
    if speech is None:
        speech = ""
    
    if isinstance(speech, unicode):
        speech = speech.encode('utf-8')
    else:
        speech = str(speech)

    if not speech:
        print "[WARN] Empty speech received, skipping TTS."
        return

    print "[INFO] Speaking:", speech
    print "[INFO] Gestures:", gestures
    print "[INFO] LED color:", led_color
    
    set_eye_color(leds, led_color)
    
    if gestures and len(gestures) > 0:
        for gesture in gestures[:2]:
            perform_gesture(motion, gesture)
    
    tts.say(speech)

def wait_for_response(stem, timeout=RESPONSE_TIMEOUT):
    """Wait for JSON response from laptop"""
    local_json = "/home/nao/sanaz/%s.json" % stem
    start_wait = time.time()
    
    while time.time() - start_wait < timeout:
        if scp_from_laptop(stem, local_json):
            try:
                with open(local_json, "r") as f:
                    raw = f.read()
                obj = json.loads(raw)
                return obj
            except Exception as e:
                print "[ERROR] JSON parse error:", e
                return None
        time.sleep(POLL_SECONDS)
    
    return None

def wait_for_updated_response(stem, old_speech, timeout=RESPONSE_TIMEOUT):
    """Wait for UPDATED JSON response (different from old one)"""
    local_json = "/home/nao/sanaz/%s.json" % stem
    start_wait = time.time()
    
    while time.time() - start_wait < timeout:
        if scp_from_laptop(stem, local_json):
            try:
                with open(local_json, "r") as f:
                    raw = f.read()
                obj = json.loads(raw)
                
                # Check if this is a NEW response (different speech)
                new_speech = obj.get("speech", "")
                if new_speech and new_speech != old_speech:
                    print "[INFO] Got updated response!"
                    return obj
                else:
                    print "[DEBUG] Still same response, waiting..."
                    
            except Exception as e:
                print "[ERROR] JSON parse error:", e
        
        time.sleep(POLL_SECONDS)
    
    print "[WARN] Timeout waiting for updated response"
    return None

def main():
    tts = ALProxy("ALTextToSpeech", "127.0.0.1", 9559)
    rec = ALProxy("ALAudioRecorder", "127.0.0.1", 9559)
    motion = ALProxy("ALMotion", "127.0.0.1", 9559)
    leds = ALProxy("ALLeds", "127.0.0.1", 9559)
    video = ALProxy("ALVideoDevice", "127.0.0.1", 9559)

    set_eye_color(leds, "blue")
    tts.say(INTRO)

    while True:
        try:
            ts = int(time.time())
            local_wav = "/home/nao/sanaz/input_%d.wav" % ts
            stem = "input_%d" % ts
            remote_name = stem + ".wav"

            print "[INFO] Recording..."
            set_eye_color(leds, "yellow")
            record_once(rec, local_wav)

            size = 0
            try:
                size = os.path.getsize(local_wav)
            except Exception:
                size = 0
            print "[INFO] Recorded size:", size

            if size < 2000:
                set_eye_color(leds, "red")
                tts.say("Sorry, I did not hear you.")
                continue

            print "[INFO] Uploading:", remote_name
            scp_to_laptop(local_wav, remote_name, LAPTOP_INCOMING_DIR)

            print "[INFO] Waiting for response..."
            response = wait_for_response(stem)

            if not response:
                set_eye_color(leds, "red")
                tts.say("Sorry, I did not get a reply.")
                continue

            speech = response.get("speech", "")
            gestures = response.get("gestures", [])
            led_color = response.get("led_color", "blue")
            need_camera = response.get("need_camera", False)
            
            if not isinstance(gestures, list):
                gestures = []

            # Speak first message (might be "Let me look at that")
            say_and_move(tts, motion, leds, speech, gestures, led_color)
            
            # If camera is needed
            if need_camera:
                print "[INFO] Taking photo..."
                image_stem = stem.replace("input_", "image_")
                local_image = "/home/nao/sanaz/%s.jpg" % image_stem
                
                if take_photo(video, local_image):
                    print "[INFO] Uploading photo..."
                    scp_to_laptop(local_image, "%s.jpg" % image_stem, LAPTOP_IMAGES_DIR)
                    
                    # Wait for laptop to process and OVERWRITE JSON
                    print "[INFO] Waiting for vision result (will overwrite JSON)..."
                    time.sleep(3.0)
                    
                    # Get UPDATED response with vision result
                    vision_response = wait_for_updated_response(stem, speech, timeout=15)
                    
                    if vision_response:
                        new_speech = vision_response.get("speech", "")
                        new_gestures = vision_response.get("gestures", [])
                        new_led_color = vision_response.get("led_color", "blue")
                        
                        if not isinstance(new_gestures, list):
                            new_gestures = []
                        
                        print "[INFO] Got vision result!"
                        say_and_move(tts, motion, leds, new_speech, new_gestures, new_led_color)
                    else:
                        print "[WARN] Did not get updated vision response"
                        tts.say("Sorry, I had trouble seeing that.")
                else:
                    tts.say("Sorry, I could not take a photo.")

            time.sleep(0.2)

        except KeyboardInterrupt:
            print "[INFO] Stopping..."
            try:
                rec.stopMicrophonesRecording()
            except Exception:
                pass
            break
        except Exception as e:
            print "[ERROR] Loop error:", e
            try:
                rec.stopMicrophonesRecording()
            except Exception:
                pass
            time.sleep(1.0)

if __name__ == "__main__":
    main()

