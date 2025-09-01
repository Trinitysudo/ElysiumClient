import threading
import time
import json
import traceback
import mss
import cv2
import numpy as np
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import pyautogui
import random
import os

# --- Global References (set by app.py) ---
eel, app = None, None
def set_eel_instance(eel_instance): global eel; eel = eel_instance
def set_app_instance(app_instance): global app; app = app_instance

# --- Module Globals ---
worker_thread, is_calibrated, module_settings = None, False, {}
is_hotkey_active = True
inventory_region, offhand_coords, mainhand_coords, inventory_marker_coords = None, None, None, None
totem_inventory_template, totem_offhand_template, totem_mainhand_template, inventory_marker_template = None, None, None, None

# --- File Paths ---
BASE_PATH = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_PATH, 'autototem_config_v11_final.json')
INV_MARKER_TEMPLATE_FILE = os.path.join(BASE_PATH, 'inventory_marker_template.png')
TOTEM_INVENTORY_TEMPLATE_FILE = os.path.join(BASE_PATH, 'totem_inventory_template.png')
TOTEM_OFFHAND_TEMPLATE_FILE = os.path.join(BASE_PATH, 'totem_offhand_template.png')
TOTEM_MAINHAND_TEMPLATE_FILE = os.path.join(BASE_PATH, 'totem_mainhand_template.png')

# --- Settings ---
def get_info():
    return {
        'internal_name': 'auto_totem', 'name': 'Auto Totem (FIXED)',
        'description': 'High-speed, stealth-optimized totem equipping with precise calibration.',
        'category': 'combat', 'has_calibration': True,
        'settings': {
            'hotkey': {'name': 'Toggle Hotkey', 'default': 'f4'},
            'confidence_threshold': {'name': 'Confidence Threshold', 'default': 0.90},
            'mouse_duration_ms': {'name': 'Mouse Duration (ms)', 'default': 50},
            'action_delay_ms': {'name': 'Action Delay (ms)', 'default': 25},
            'gui_render_delay_ms': {'name': 'GUI Render Delay (ms)', 'default': 10},  # Reduced from 30ms to 10ms
            'humanization_factor': {'name': 'Humanization Factor', 'default': 0.30}
        }
    }

def log(message):
    if eel: eel.add_log_entry(f"[AutoTotem] {message}")()

# --- THEMED CALIBRATION GUI ---
class ThemedCalibrator(tk.Toplevel):
    def __init__(self, parent, screenshot_data):
        super().__init__(parent)
        self.attributes("-topmost", True); self.attributes("-fullscreen", True); self.grab_set()
        self.stage = 1
        self.points = {}
        self.result = None
        pil_img = Image.frombytes("RGB", screenshot_data.size, screenshot_data.bgra, "raw", "BGRX")
        self.tk_img = ImageTk.PhotoImage(pil_img)
        self.canvas = tk.Canvas(self, cursor="crosshair", width=pil_img.width, height=pil_img.height)
        self.canvas.pack(); self.canvas.create_image(0, 0, anchor='nw', image=self.tk_img)
        self.canvas.bind("<Button-1>", self.on_click); self.bind("<Escape>", lambda e: self.destroy())
        
        self.instr_label_bg = self.canvas.create_text((pil_img.width / 2)+2, 32, text="", font=("Segoe UI", 16, "bold"), fill="black")
        self.instr_label = self.canvas.create_text(pil_img.width / 2, 30, text="", font=("Segoe UI", 16, "bold"), fill="#BB9AF7")
        self.update_instructions()

    def update_instructions(self):
        stages = {
            1: "Step 1/6: Click TOP-LEFT of inventory area",
            2: "Step 2/6: Click BOTTOM-RIGHT of inventory area",
            3: "Step 3/6: Click 'Crafting' text (inventory marker)",
            4: "Step 4/6: Click a TOTEM in your inventory",
            5: "Step 5/6: Click the TOTEM in your OFF-HAND slot",
            6: "Step 6/6: Click the TOTEM in your MAIN-HAND slot"
        }
        text = stages.get(self.stage, "Done!")
        self.canvas.itemconfig(self.instr_label, text=text)
        self.canvas.itemconfig(self.instr_label_bg, text=text)

    def on_click(self, event):
        x, y = event.x, event.y
        self.points[self.stage] = (x, y)
        self.canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill='#BB9AF7', outline='black', width=2)
        if self.stage == 2: self.canvas.create_rectangle(self.points[1], self.points[2], outline='#7AA2F7', width=2, dash=(5, 3))
        self.stage += 1
        if self.stage > 6: self.finish()
        else: self.update_instructions()

    def finish(self):
        try:
            self.result = {
                "inventory_region": {'left': self.points[1][0], 'top': self.points[1][1], 'width': self.points[2][0] - self.points[1][0], 'height': self.points[2][1] - self.points[1][1]},
                "inventory_marker_coords": self.points[3],
                "totem_inv_coords": self.points[4],
                "offhand_coords": self.points[5],
                "mainhand_coords": self.points[6],
                "screenshot": self.master.screenshot_data
            }
        except Exception as e:
            log(f"❌ Error collecting points: {e}"); self.result = None
        finally:
            self.destroy()

def run_calibration():
    def calibration_task():
        try:
            log("--- Calibration Initiated ---")
            log("Please switch to your game. Screen will be captured in 2 seconds.")
            time.sleep(2)
            
            with mss.mss() as sct:
                screenshot_data = sct.grab(sct.monitors[1])
                
            root = tk.Tk(); root.withdraw()
            root.screenshot_data = screenshot_data
            calibrator = ThemedCalibrator(root, screenshot_data)
            root.wait_window(calibrator)
            
            if calibrator.result:
                log("✓ Calibration points captured. Saving...")
                res = calibrator.result
                
                global inventory_region, offhand_coords, mainhand_coords, inventory_marker_coords
                inventory_region = res["inventory_region"]
                offhand_coords = res["offhand_coords"]
                mainhand_coords = res["mainhand_coords"]
                inventory_marker_coords = res["inventory_marker_coords"]
                
                _save_config()

                full_screenshot = np.array(res['screenshot'])
                ss_bgr = full_screenshot[:, :, :3]

                cv2.imwrite(INV_MARKER_TEMPLATE_FILE, create_template_from_coords(ss_bgr, res["inventory_marker_coords"], 8))
                cv2.imwrite(TOTEM_OFFHAND_TEMPLATE_FILE, create_template_from_coords(ss_bgr, res["offhand_coords"], 24))
                cv2.imwrite(TOTEM_MAINHAND_TEMPLATE_FILE, create_template_from_coords(ss_bgr, res["mainhand_coords"], 24))
                cv2.imwrite(TOTEM_INVENTORY_TEMPLATE_FILE, create_template_from_coords(ss_bgr, res["totem_inv_coords"], 24))

                # --- NEW: Auto-load the new config ---
                log("✓ Calibration saved. Applying settings now...")
                _load_config()
            else:
                log("! Calibration cancelled.")
            root.destroy()
        except Exception:
            log(f"❌ Calibration failed: {traceback.format_exc()}")
    
    threading.Thread(target=calibration_task, daemon=True).start()

# --- Core Logic (Your OG Code) ---
def human_sleep_ms(base_ms):
    if base_ms <= 0: return
    factor = float(module_settings.get('humanization_factor', 0.30))
    time.sleep(max(0, (base_ms * (1 + random.uniform(-factor, factor))) / 1000.0))

def human_click():
    pyautogui.mouseDown(); time.sleep(random.uniform(0.035, 0.075)); pyautogui.mouseUp()

def worker_loop():
    global worker_thread
    inventory_was_open = False; pyautogui.PAUSE = 0
    
    # Pre-calculate delay values to avoid repeated dict lookups
    base_gui_delay = int(module_settings.get('gui_render_delay_ms', 10))
    
    with mss.mss() as sct:
        while worker_thread is not None:
            time.sleep(0.020)  # Reduced from 0.035 to 0.020 for faster detection
            if not is_hotkey_active or not is_calibrated: continue
            try:
                is_open_now = is_inventory_open(sct)
                if is_open_now and not inventory_was_open:
                    # Dynamic delay: only wait if we need to, and use shorter delay
                    human_sleep_ms(base_gui_delay)
                    
                    # Quick parallel slot checking
                    offhand_full = is_slot_full(sct, offhand_coords, totem_offhand_template)
                    mainhand_full = is_slot_full(sct, mainhand_coords, totem_mainhand_template)
                    
                    if not offhand_full or not mainhand_full:
                        perform_equip_sequence(sct, not offhand_full, not mainhand_full)
                inventory_was_open = is_open_now
            except Exception as e:
                log(f"❌ Worker error: {e}")

def perform_equip_sequence(sct, equip_offhand, equip_mainhand):
    available_totems = find_all_totems(sct)
    if not available_totems: return
    action_taken = False
    
    # Faster execution with minimal delays
    if equip_offhand and available_totems:
        equip_slot(available_totems.pop(0), 'offhand'); action_taken = True
    if equip_mainhand and available_totems:
        equip_slot(available_totems.pop(0), 'mainhand'); action_taken = True
    
    if action_taken:
        # Reduced closing delay for faster response
        human_sleep_ms(random.randint(20, 40))  # Reduced from 40-75 to 20-40
        pyautogui.press('e')
        log("✅ Equip cycle complete.")

def is_slot_full(sct, slot_coords, template):
    if not slot_coords or template is None: return False
    slot_region = {'left': int(slot_coords[0]-16), 'top': int(slot_coords[1]-16), 'width': 32, 'height': 32}
    slot_ss = np.array(sct.grab(slot_region))[:, :, :3]
    res = cv2.matchTemplate(slot_ss, template, cv2.TM_CCOEFF_NORMED); _, max_val, _, _ = cv2.minMaxLoc(res)
    return max_val > float(module_settings.get('confidence_threshold', 0.90))

def find_all_totems(sct):
    if not inventory_region or totem_inventory_template is None: return []
    inv_ss = np.array(sct.grab(inventory_region))[:, :, :3]
    threshold = float(module_settings.get('confidence_threshold', 0.90))
    res = cv2.matchTemplate(inv_ss, totem_inventory_template, cv2.TM_CCOEFF_NORMED)
    locs = np.where(res >= threshold)
    rects = [[int(pt[0]), int(pt[1]), totem_inventory_template.shape[1], totem_inventory_template.shape[0]] for pt in zip(*locs[::-1])]
    indices = cv2.dnn.NMSBoxes(rects, [1.0]*len(rects), threshold, 0.3)
    if not isinstance(indices, np.ndarray) or len(indices) == 0: return []
    search_x, search_y = inventory_region['left'], inventory_region['top']
    return sorted([(int(search_x + rects[i][0] + rects[i][2] / 2), int(search_y + rects[i][1] + rects[i][3] / 2)) for i in indices.flatten()], key=lambda p: (p[1], p[0]))

def equip_slot(totem_coord, slot_type):
    base_ms = int(module_settings.get('mouse_duration_ms', 50))
    action_ms = int(module_settings.get('action_delay_ms', 25))
    factor = float(module_settings.get('humanization_factor', 0.30))
    
    # Faster mouse movement for quicker response
    move_duration_s = max(0.008, (base_ms * (1 + random.uniform(-factor, factor))) / 1000.0)  # Reduced min from 0.01 to 0.008
    x_jitter, y_jitter = random.randint(-2, 2), random.randint(-2, 2)
    pyautogui.moveTo(totem_coord[0] + x_jitter, totem_coord[1] + y_jitter, duration=move_duration_s, tween=pyautogui.easeOutQuad)
    
    # Shorter action delay for faster equipping
    human_sleep_ms(max(15, action_ms))  # Minimum 15ms to ensure stability
    
    if slot_type == 'offhand':
        pyautogui.press('f')
    elif slot_type == 'mainhand':
        # --- NEW: Use capslock for mainhand ---
        pyautogui.press('capslock')

def is_inventory_open(sct):
    if not inventory_marker_coords or inventory_marker_template is None: return False
    marker_region = {'left': int(inventory_marker_coords[0]-8), 'top': int(inventory_marker_coords[1]-8), 'width': 16, 'height': 16}
    marker_ss = np.array(sct.grab(marker_region))[:, :, :3]
    res = cv2.matchTemplate(marker_ss, inventory_marker_template, cv2.TM_CCOEFF_NORMED)
    return res.max() > 0.90

# --- Config ---
def _save_config():
    with open(CONFIG_FILE, 'w') as f: json.dump({"inventory_region": inventory_region, "offhand_coords": offhand_coords, "mainhand_coords": mainhand_coords, "inventory_marker_coords": inventory_marker_coords}, f, indent=4)

def _load_config():
    global is_calibrated, inventory_region, offhand_coords, mainhand_coords, inventory_marker_coords
    global totem_inventory_template, totem_offhand_template, totem_mainhand_template, inventory_marker_template
    files = [CONFIG_FILE, INV_MARKER_TEMPLATE_FILE, TOTEM_INVENTORY_TEMPLATE_FILE, TOTEM_OFFHAND_TEMPLATE_FILE, TOTEM_MAINHAND_TEMPLATE_FILE]
    if not all(os.path.exists(f) for f in files): return False
    try:
        with open(CONFIG_FILE, 'r') as f: config = json.load(f)
        inventory_region, offhand_coords, mainhand_coords, inventory_marker_coords = config["inventory_region"], config["offhand_coords"], config["mainhand_coords"], config["inventory_marker_coords"]
        inventory_marker_template = cv2.imread(INV_MARKER_TEMPLATE_FILE)
        totem_inventory_template = cv2.imread(TOTEM_INVENTORY_TEMPLATE_FILE)
        totem_offhand_template = cv2.imread(TOTEM_OFFHAND_TEMPLATE_FILE)
        totem_mainhand_template = cv2.imread(TOTEM_MAINHAND_TEMPLATE_FILE)
        if any(img is None for img in [inventory_marker_template, totem_inventory_template, totem_offhand_template, totem_mainhand_template]): raise Exception("Template load failed.")
        is_calibrated = True; log("Loaded config."); return True
    except Exception as e:
        log(f"❌ Config error: {e}"); is_calibrated = False; return False

def create_template_from_coords(ss_bgr, coords, size=16):
    x, y = int(coords[0]), int(coords[1])
    half = size // 2
    return ss_bgr[max(0, y-half):y+half, max(0, x-half):x+half]

def toggle_hotkey_state():
    global is_hotkey_active
    is_hotkey_active = not is_hotkey_active
    log(f"Hotkey Toggled: {'ACTIVE' if is_hotkey_active else 'PAUSED'}.")

def get_toggle_callback(): return toggle_hotkey_state

def start(settings):
    global worker_thread, module_settings, is_hotkey_active
    if worker_thread: return
    module_settings = settings; is_hotkey_active = True
    if not _load_config():
        log("❌ Cannot start: Please calibrate."); eel.set_toggle_state(get_info()['internal_name'], False)(); return
    worker_thread = threading.Thread(target=worker_loop, daemon=True); worker_thread.start()
    if app: app.register_hotkey(get_info()['internal_name'], module_settings.get('hotkey'), get_toggle_callback())
    log("✅ AutoTotem started.")

def stop():
    global worker_thread
    if app: app.unregister_hotkey(get_info()['internal_name'])
    if worker_thread:
        thread_to_stop = worker_thread
        worker_thread = None
        thread_to_stop.join(timeout=0.5)
    log("⏹️ Module stopped.")