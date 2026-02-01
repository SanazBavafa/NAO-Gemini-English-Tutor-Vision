import os
import time
import json
import traceback
from pathlib import Path
import speech_recognition as sr
from google import genai
from PIL import Image

INCOMING_DIR = Path(r"C:\Users\khaled\Documents\Nao_Project\incoming")
OUTGOING_DIR = Path(r"C:\Users\khaled\Documents\Nao_Project\outgoing")
IMAGES_DIR = Path(r"C:\Users\khaled\Documents\Nao_Project\images")

MODEL_NAME = "models/gemini-2.5-flash"

API_KEY = "AIzaSyDhdgXDsNm4s6YmWABW81lRqeF2CCRsFn4"

client = genai.Client(api_key=API_KEY)

recognizer = sr.Recognizer()

VISION_KEYWORDS = ["see", "look", "watch", "color", "colour", "wearing", "hand", "holding", "what is this", "show", "picture", "photo", "capture"]

def default_state():
    return {
        "phase": "collect_profile",
        "name": None,
        "topic": None,
        "turn": 0,
        "lesson_stage": "introduction",
        "questions_asked": []
    }

def needs_vision(text):
    text_lower = text.lower()
    for keyword in VISION_KEYWORDS:
        if keyword in text_lower:
            return True
    return False

def wait_for_stable_file(path, stable_checks=3, interval_sec=0.2, timeout_sec=8.0):
    start = time.time()
    last_size = -1
    stable_count = 0

    while True:
        if time.time() - start > timeout_sec:
            raise TimeoutError(f"File not stable within {timeout_sec}s: {path}")

        try:
            if not path.exists():
                stable_count = 0
                time.sleep(interval_sec)
                continue

            size = path.stat().st_size
            if size > 0 and size == last_size:
                stable_count += 1
            else:
                stable_count = 0

            last_size = size

            with open(path, "rb"):
                pass

            if stable_count >= stable_checks:
                return

        except PermissionError:
            stable_count = 0

        time.sleep(interval_sec)

def stt_from_wav(wav_path):
    wait_for_stable_file(wav_path)
    last_err = None
    for _ in range(6):
        try:
            with sr.AudioFile(str(wav_path)) as source:
                audio = recognizer.record(source)
            return recognizer.recognize_google(audio, language="en-US")
        except PermissionError as e:
            last_err = e
            time.sleep(0.2)
        except Exception:
            raise
    raise last_err or PermissionError("Permission denied while reading audio file.")

def gemini_extract_profile(user_text):
    prompt = f"""
Return ONLY valid JSON with exactly these keys:
- "name": string or null
- "topic": string or null

No markdown. No code fences. Only raw JSON.

Student text:
{user_text}
""".strip()

    resp = client.models.generate_content(model=MODEL_NAME, contents=prompt)
    raw = (resp.text or "").strip()

    try:
        data = json.loads(raw)
    except Exception:
        data = {"name": None, "topic": None}

    name = data.get("name")
    topic = data.get("topic")

    return {
        "name": name.strip() if isinstance(name, str) else None,
        "topic": topic.strip() if isinstance(topic, str) else None
    }

def gemini_vision_reply(state, user_text, image_path):
    name = state.get("name") or "my friend"
    topic = state.get("topic") or "today's topic"
    
    try:
        img = Image.open(image_path)
        print(f"[INFO] Image loaded successfully: {img.size}, mode: {img.mode}")
        
        prompt = f"""
You are NAO robot, an English teacher.

The student {name} asked: "{user_text}"

IMPORTANT: Look at this photo from my camera and describe what you see.

If you see a person:
- Describe the color of their shirt/clothing
- Describe any other colors you see
- Be specific and clear

Use simple English (A1/A2 level).
Keep answer SHORT (2-3 sentences).

CRITICAL RULES:
- DO NOT say gesture names (wave, nod, shake_head, look_up, hand_open, etc.) in the speech field
- DO NOT say color words like red, green, blue, yellow when talking about LED lights
- ONLY describe what you SEE in the image
- If you cannot see clearly, say "I cannot see clearly, please try again"

Return ONLY this JSON:
{{"speech": "describe what you see without gesture/LED color names", "gestures": ["nod"], "led_color": "blue"}}
""".strip()

        print("[INFO] Sending to Gemini Vision...")
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[prompt, img]
        )
        
        raw = (response.text or "").strip()
        print(f"[INFO] Gemini raw response: {raw}")
        
        if raw.startswith("```"):
            raw = raw.strip().replace("```json", "").replace("```", "").strip()
        
        data = json.loads(raw)
        speech = str(data.get("speech", "")).strip()
        gestures = data.get("gestures", ["nod"])
        led_color = data.get("led_color", "blue")
        
        print(f"[INFO] Parsed - Speech: {speech}")
        print(f"[INFO] Parsed - Gestures: {gestures}")
        print(f"[INFO] Parsed - LED: {led_color}")
        
        if not isinstance(gestures, list):
            gestures = ["nod"]
        
        # Remove forbidden words
        forbidden_words = ["wave", "nod", "shake_head", "look_up", "look_left", "look_right", 
                          "hand_open", "hand_close", "red", "green", "blue", "yellow", "white"]
        
        for word in forbidden_words:
            speech = speech.replace(" " + word + " ", " ")
            speech = speech.replace(" " + word, "")
            speech = speech.replace(word + " ", "")
        
        speech = " ".join(speech.split())
        
        print(f"[INFO] Final speech: {speech}")
        
        return {"speech": speech, "gestures": gestures, "led_color": led_color}
        
    except Exception as e:
        print(f"[ERROR] Vision processing failed: {e}")
        traceback.print_exc()
        return {
            "speech": "Sorry, I cannot see that right now. Let's continue our lesson.",
            "gestures": ["shake_head"],
            "led_color": "red"
        }

def gemini_tutor_reply(state, user_text):
    name = state.get("name") or "my friend"
    topic = state.get("topic") or "today's topic"
    turn = state.get("turn", 0)
    lesson_stage = state.get("lesson_stage", "introduction")

    stage_instructions = {
        "introduction": """Give a clear, simple explanation of {topic} with 2 concrete examples. 
Use A1/A2 level English. Make it engaging and encourage the student. 
Then ask one simple question to check understanding.""",
        
        "practice": """FIRST: Check the student's previous answer. If there are ANY mistakes (grammar, vocabulary, pronunciation spelling), gently correct them with explanation. Give positive feedback first, then correction. 
THEN: Ask a NEW follow-up question to practice more.""",
        
        "application": """FIRST: Check if their answer was correct. If mistakes exist, correct gently. 
THEN: Create a real-life scenario where student must use {topic}. Ask them to respond.""",
        
        "check_questions": """FIRST: If student just answered a question, check it and correct any mistakes. 
THEN: Ask: 'Do you have any questions about {topic} so far?' and wait for response.""",
        
        "review": """FIRST: If they just answered, correct any mistakes. 
THEN: Briefly review what was learned. Give specific positive feedback. Ask what they found easy or difficult."""
    }

    current_instruction = stage_instructions.get(lesson_stage, stage_instructions["introduction"]).replace("{topic}", topic)

    prompt = f"""
You are NAO robot, a professional English tutor.

STUDENT INFO:
- Name: {name}
- Topic: {topic}
- Turn: {turn}
- Stage: {lesson_stage}

TEACHING STAGE: {current_instruction}

CRITICAL WORKFLOW (MUST FOLLOW IN ORDER):
1. ALWAYS first analyze what student just said
2. If student made ANY mistake (grammar, word choice, structure), correct it gently but clearly
3. Explain WHY it was wrong and give the correct version
4. Give encouragement
5. ONLY THEN ask the next question or move forward

CRITICAL RULES:
1. Use simple A1/A2 English
2. NEVER skip correction - if student makes a mistake, ALWAYS correct it before asking next question
3. If student's answer was correct, praise them specifically
4. Every 5 turns, after correcting, ask if they have questions
5. Be encouraging but honest about mistakes
6. DO NOT mention gesture names in speech (wave, nod, shake_head, etc.)
7. DO NOT mention color names in speech (red, green, blue, yellow, etc.)
8. DO NOT use line breaks in speech - write as one continuous paragraph
9. Keep total response under 5 sentences
10. The "speech" field is ONLY what you will say out loud - NEVER include gesture names or colors there

GESTURE SELECTION:
- Use "wave" for greeting or celebrating
- Use "nod" for agreeing or when answer is correct
- Use "shake_head" when correcting mistakes
- Use "hand_open" for explaining
- Use "look_up" when asking questions

LED COLOR SELECTION (for robot eyes, NOT to say out loud):
- "green" for correct answers
- "blue" for teaching/explaining
- "yellow" for questions/waiting
- "red" for corrections

Student said: {user_text}

Return ONLY this JSON format (speech must be ONE line and must NOT contain gesture or color words):
{{"speech": "your response without any gesture or color names", "gestures": ["gesture1", "gesture2"], "led_color": "color"}}
""".strip()

    resp = client.models.generate_content(model=MODEL_NAME, contents=prompt)
    raw = (resp.text or "").strip()

    if raw.startswith("```"):
        raw = raw.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(raw)
        speech = str(data.get("speech", "")).strip()
        gestures = data.get("gestures", [])
        led_color = data.get("led_color", "blue")
        
        if not isinstance(gestures, list):
            gestures = []
        gestures = [g for g in gestures if isinstance(g, str)]
        
        if not isinstance(led_color, str):
            led_color = "blue"
        
        forbidden_words = ["wave", "nod", "shake_head", "look_up", "look_left", "look_right", 
                          "hand_open", "hand_close", "red", "green", "blue", "yellow", "white"]
        
        for word in forbidden_words:
            speech = speech.replace(" " + word + " ", " ")
            speech = speech.replace(" " + word, "")
            speech = speech.replace(word + " ", "")
        
        speech = " ".join(speech.split())
            
    except json.JSONDecodeError as e:
        print(f"[ERROR] Gemini JSON parse failed: {e}")
        print(f"[ERROR] Raw response: {raw}")
        
        raw_fixed = raw.replace('\n', ' ').replace('\r', ' ')
        try:
            data = json.loads(raw_fixed)
            speech = str(data.get("speech", "")).strip()
            gestures = data.get("gestures", [])
            led_color = data.get("led_color", "blue")
            
            if not isinstance(gestures, list):
                gestures = []
            gestures = [g for g in gestures if isinstance(g, str)]
            if not isinstance(led_color, str):
                led_color = "blue"
            
            forbidden_words = ["wave", "nod", "shake_head", "look_up", "look_left", "look_right", 
                              "hand_open", "hand_close", "red", "green", "blue", "yellow", "white"]
            
            for word in forbidden_words:
                speech = speech.replace(" " + word + " ", " ")
                speech = speech.replace(" " + word, "")
                speech = speech.replace(word + " ", "")
            
            speech = " ".join(speech.split())
                
            print("[INFO] Fixed by removing newlines")
        except Exception:
            speech = "Sorry, I had a problem. Please say that again."
            gestures = ["shake_head"]
            led_color = "red"
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        speech = "Sorry, I had a problem. Please say that again."
        gestures = ["shake_head"]
        led_color = "red"

    if not speech:
        speech = "Sorry, I did not understand. Please say it again."
        gestures = ["shake_head"]
        led_color = "yellow"

    return {"speech": speech, "gestures": gestures, "led_color": led_color}

def write_outgoing(basename, payload):
    OUTGOING_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTGOING_DIR / (Path(basename).stem + ".json")
    out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"[INFO] Wrote: {out_path}")

def update_lesson_stage(state):
    turn = state["turn"]
    if turn == 1:
        state["lesson_stage"] = "introduction"
    elif turn <= 5:
        state["lesson_stage"] = "practice"
    elif turn == 6:
        state["lesson_stage"] = "check_questions"
    elif turn <= 11:
        state["lesson_stage"] = "application"
    elif turn == 12:
        state["lesson_stage"] = "check_questions"
    else:
        state["lesson_stage"] = "review"
    return state

def process_one_audio(wav_path, state):
    try:
        text = stt_from_wav(wav_path)
        print(f"[INFO] STT: {text}")
    except sr.UnknownValueError:
        print("[ERROR] STT failed: UnknownValueError()")
        return state
    except Exception as e:
        print(f"[ERROR] STT failed: {repr(e)}")
        return state

    state["turn"] += 1

    if state["phase"] == "collect_profile":
        prof = gemini_extract_profile(text)
        if prof["name"] and not state["name"]:
            state["name"] = prof["name"]
        if prof["topic"] and not state["topic"]:
            state["topic"] = prof["topic"]

        if not state["name"] or not state["topic"]:
            missing = []
            if not state["name"]:
                missing.append("your name")
            if not state["topic"]:
                missing.append("a topic")
            payload = {"speech": f"Sorry, I did not catch {' and '.join(missing)}. Please say it again.", "gestures": ["shake_head"], "led_color": "yellow"}
            write_outgoing(wav_path.name, payload)
            return state

        state["phase"] = "tutor"
        state["lesson_stage"] = "introduction"
        payload = {
            "speech": f"Perfect {state['name']}! Let's learn about {state['topic']} today.",
            "gestures": ["wave", "nod"],
            "led_color": "green"
        }
        write_outgoing(wav_path.name, payload)
        return state

    if needs_vision(text):
        print("[INFO] Vision request detected!")
        
        # Signal NAO to take photo
        payload = {
            "speech": "Let me look at that.",
            "gestures": ["look_up"],
            "led_color": "yellow",
            "need_camera": True
        }
        write_outgoing(wav_path.name, payload)
        
        # Wait for image
        image_stem = Path(wav_path.name).stem.replace("input_", "image_")
        image_path = IMAGES_DIR / f"{image_stem}.jpg"
        
        print(f"[INFO] Waiting for image: {image_path}")
        timeout = 15
        start = time.time()
        image_received = False
        
        while time.time() - start < timeout:
            if image_path.exists():
                try:
                    wait_for_stable_file(image_path, timeout_sec=5)
                    print(f"[INFO] Image received: {image_path}")
                    image_received = True
                    break
                except Exception as e:
                    print(f"[WARN] Image not ready: {e}")
            time.sleep(0.5)
        
        if image_received:
            # Process with vision - this OVERWRITES the previous JSON
            print("[INFO] Processing image with Gemini Vision...")
            payload = gemini_vision_reply(state, text, image_path)
            write_outgoing(wav_path.name, payload)
            print("[INFO] Vision response written")
        else:
            # Timeout - no image - OVERWRITE with error message
            payload = {
                "speech": "Sorry, I could not see that. Let's continue.",
                "gestures": ["shake_head"],
                "led_color": "red"
            }
            write_outgoing(wav_path.name, payload)
        
        return state

    state = update_lesson_stage(state)
    payload = gemini_tutor_reply(state, text)
    write_outgoing(wav_path.name, payload)
    return state

def main():
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    OUTGOING_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] Watching incoming: {INCOMING_DIR}")
    print(f"[INFO] Writing outgoing: {OUTGOING_DIR}")
    print(f"[INFO] Images directory: {IMAGES_DIR}")

    state = default_state()
    seen = set()

    while True:
        try:
            wavs = sorted(INCOMING_DIR.glob("input_*.wav"), key=lambda p: p.stat().st_mtime)
            for wav_path in wavs:
                if wav_path.name in seen:
                    continue

                try:
                    wait_for_stable_file(wav_path)
                except Exception as e:
                    print(f"[WARN] File not ready yet: {wav_path} ({e})")
                    continue

                seen.add(wav_path.name)
                print(f"[INFO] Audio received: {wav_path}")
                state = process_one_audio(wav_path, state)

            time.sleep(0.2)

        except KeyboardInterrupt:
            print("[INFO] Stopped by user.")
            break
        except Exception:
            print("[ERROR] Loop error:")
            print(traceback.format_exc())
            time.sleep(1.0)

if __name__ == "__main__":
    main()
