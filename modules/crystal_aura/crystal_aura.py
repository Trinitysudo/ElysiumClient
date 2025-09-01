import threading
import time
import mss
import json
import random
import win32api
import win32con
import tkinter as tk
from PIL import Image, ImageTk

# --- Global References ---
eel, app = None, None

def set_eel_instance(eel_instance):
    global eel
    eel = eel_instance

def set_app_instance(app_instance):
    global app
    app = app_instance

# --- Module Metadata ---
def get_info():
    return {
        "name": "Crystal Aura",
        "description": "Fast pixel-based crystal placement automation",
        "author": "Auto (Optimized by Gemini)",
        "internal_name": "crystal_aura",
        "version": "3.5", # Version bump for optimization
        "category": "combat",
        "has_calibration": True,
        "settings": {
            "hotkey": {"name": "Hotkey", "type": "text", "default": "f4"},
            # Renamed for clarity: Delay between placing and breaking
            "place_break_delay": {"name": "Place/Break Delay (ms)", "type": "number", "default": 5},
            # Delay between one full cycle and the next
            "cycle_delay": {"name": "Cycle Delay (ms)", "type": "number", "default": 20},
            "ac_delay": {"name": "Anti-Cheat Delay (ms)", "type": "slider", "default": 0, "min": 0, "max": 100},
            "humanization": {"name": "Humanization (%)", "type": "slider", "default": 10, "min": 0, "max": 100},
            "color_tolerance": {"name": "Color Tolerance", "type": "slider", "default": 25, "min": 0, "max": 255},
            # Removed redundant/slow settings like packet_mode, strict_timing, fast_clicks
            "cal_pixel_x": {"name": "Pixel X", "type": "text", "default": "0", "hidden": True},
            "cal_pixel_y": {"name": "Pixel Y", "type": "text", "default": "0", "hidden": True},
            "cal_activation_color": {"name": "Color", "type": "text", "default": "[]", "hidden": True},
        }
    }

def log(message):
    log_message = f"[Crystal Aura] {message}"
    if eel:
        try:
            eel.add_log_entry(log_message)()
        except Exception as e:
            print(f"Failed to send log to UI: {e}")
            print(log_message)
    else:
        print(log_message)

# --- Module State ---
_state = {
    "thread": None,
    "running": False,
    "active": False,
    "calibrated": False,
    "stop_event": threading.Event(),
    "activation_event": threading.Event(),
    "settings": {},
}
_lock = threading.Lock()

# --- Helper Functions ---
def _color_distance(c1, c2):
    """Calculate Euclidean distance between two RGB colors."""
    try:
        return sum((a - b) ** 2 for a, b in zip(c1, c2)) ** 0.5
    except (TypeError, ValueError):
        return float('inf')

def _human_sleep(base_delay_ms, humanization_percent):
    """Sleep with optional humanization variance. Ensures minimum sleep time."""
    try:
        if base_delay_ms <= 0:
            return
        base_delay_s = base_delay_ms / 1000.0
        if humanization_percent > 0:
            variance = base_delay_s * (humanization_percent / 100.0)
            # Use a smaller, more controlled randomization
            delay = base_delay_s + random.uniform(-variance / 2, variance / 2)
        else:
            delay = base_delay_s
        # Ensure delay is not negative or excessively small
        time.sleep(max(0.001, delay))
    except Exception as e:
        log(f"Sleep error: {e}")
        time.sleep(0.01)

def _click(is_right):
    """Perform a mouse click as fast as possible."""
    try:
        if is_right:
            win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN, 0, 0)
            win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, 0, 0)
        else:
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
    except Exception as e:
        log(f"Click error: {e}")

# --- Worker Thread ---
def _worker_loop():
    """Main worker thread loop, optimized for speed."""
    log("Worker thread started")
    
    try:
        with mss.mss() as sct:
            while not _state['stop_event'].is_set():
                # Wait for the activation event. Timeout is short for responsiveness.
                if not _state['activation_event'].wait(timeout=0.001):
                    continue
                
                # Double-check stop condition after wait
                if _state['stop_event'].is_set():
                    break
                
                with _lock:
                    if not _state['active']:
                        continue
                    settings = _state['settings']

                try:
                    pixel_x = int(settings['cal_pixel_x'])
                    pixel_y = int(settings['cal_pixel_y'])
                    target_color = tuple(json.loads(settings['cal_activation_color']))
                    color_tolerance = int(settings['color_tolerance'])
                    humanization = int(settings['humanization'])
                    place_break_delay = float(settings['place_break_delay'])
                    cycle_delay = float(settings['cycle_delay'])
                    ac_delay = float(settings.get('ac_delay', 0))

                except (KeyError, ValueError, TypeError, json.JSONDecodeError) as e:
                    # Log error once and deactivate to prevent spam
                    log(f"Settings error: {e}. Deactivating module.")
                    toggle_activation(False)
                    continue

                # --- Core CPvP Logic ---
                monitor = {'top': pixel_y, 'left': pixel_x, 'width': 1, 'height': 1}
                try:
                    img = sct.grab(monitor)
                    px = img.pixel(0, 0)
                    # MSS gives BGRA, convert to RGB for comparison
                    current_color = (px[2], px[1], px[0]) 

                    if _color_distance(current_color, target_color) <= color_tolerance:
                        # 1. Place Crystal (Right Click)
                        _click(is_right=True)
                        
                        # 2. Wait for server to register the placement (CRITICAL FOR PING)
                        _human_sleep(place_break_delay, humanization)
                        
                        # 3. Break Crystal (Left Click)
                        _click(is_right=False)

                        # 4. Wait for the next cycle (controls overall speed)
                        _human_sleep(cycle_delay, humanization)
                        
                        # 5. Optional Anti-Cheat delay
                        if ac_delay > 0:
                            _human_sleep(ac_delay, 50) # Use fixed 50% humanization for AC delay

                except Exception as e:
                    log(f"Main loop error: {e}")
                    time.sleep(0.1) # Prevent rapid-fire errors

    except Exception as e:
        log(f"Worker thread crashed: {e}")
    finally:
        with _lock:
            _state['running'] = False
            _state['active'] = False
        log("Worker thread stopped")

# --- Public API (Largely unchanged, but simplified start()) ---
def start(settings):
    """Start the crystal aura module."""
    with _lock:
        if _state['running']:
            log("Already running")
            return
            
        _state['settings'] = settings.copy()
        
        # Validate calibration on start
        try:
            px = int(settings.get('cal_pixel_x', 0))
            py = int(settings.get('cal_pixel_y', 0))
            color_data = json.loads(settings.get('cal_activation_color', '[]'))
            
            if px > 0 and py > 0 and isinstance(color_data, list) and len(color_data) == 3:
                _state['calibrated'] = True
                log(f"Calibrated: pixel ({px},{py}), color {color_data}")
            else:
                _state['calibrated'] = False
                log("Module is NOT calibrated. Please run calibration.")
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            _state['calibrated'] = False
            log(f"Calibration data is invalid: {e}")
        
        _state['stop_event'].clear()
        _state['activation_event'].clear()
        _state['running'] = True
        _state['active'] = False
        
        _state['thread'] = threading.Thread(target=_worker_loop, daemon=True, name="CrystalAura-Worker")
        _state['thread'].start()
        log("Module started")

def stop():
    """Stop the crystal aura module."""
    with _lock:
        if not _state['running']:
            log("Not running")
            return
            
        _state['stop_event'].set()
        _state['activation_event'].set() # Wake up the thread so it can exit
        thread = _state['thread']
        _state['running'] = False
        _state['active'] = False
        
    if thread and thread.is_alive():
        thread.join(timeout=1.0) # Shortened timeout
        if thread.is_alive():
            log("Warning: Thread did not stop cleanly")
    
    log("Module stopped")

def toggle_activation(enabled):
    """Toggle module activation state."""
    with _lock:
        if not _state['running']:
            log("Cannot toggle - module not running")
            return False
            
        if enabled and not _state['calibrated']:
            log("Cannot activate - not calibrated")
            return False
        
        _state['active'] = enabled
        if enabled:
            _state['activation_event'].set()
        else:
            _state['activation_event'].clear()
            
    log(f"Module {'activated' if enabled else 'deactivated'}")
    return True

def hotkey_toggle():
    """Handle hotkey toggle."""
    with _lock:
        if not _state['running'] or not _state['calibrated']:
            log(f"Hotkey ignored - running: {_state['running']}, calibrated: {_state['calibrated']}")
            return
        
        new_state = not _state['active']
        _state['active'] = new_state
        
        if new_state:
            _state['activation_event'].set()
        else:
            _state['activation_event'].clear()
        
    log(f"Hotkey toggle: {'ON' if new_state else 'OFF'}")
    
    if eel:
        try:
            eel.set_toggle_state('crystal_aura', new_state)()
        except Exception as e:
            log(f"Failed to update UI toggle: {e}")

def run_calibration():
    """Start calibration process."""
    log("Starting calibration...")
    threading.Thread(target=_calibration_task, daemon=True, name="CrystalAura-Calibration").start()

def _calibration_task():
    """Calibration task running in separate thread."""
    try:
        log("Get ready... Capturing screen in 3 seconds.")
        time.sleep(3)
        
        with mss.mss() as sct:
            # Capture the primary monitor
            screenshot = sct.grab(sct.monitors[1])
        
        root = tk.Tk()
        root.withdraw()
        
        calibrator = _Calibrator(root, screenshot)
        root.wait_window(calibrator) # Wait until the calibration window is closed
        result = calibrator.result
        root.destroy()
        
        if result and app:
            log(f"Calibration complete: ({result['x']},{result['y']}) Color: {result['color']}")
            app.update_multiple_settings('crystal_aura', {
                'cal_pixel_x': str(result['x']),
                'cal_pixel_y': str(result['y']),
                'cal_activation_color': json.dumps(result['color'])
            })
        else:
            log("Calibration cancelled")
            
    except Exception as e:
        log(f"Calibration failed: {e}")

class _Calibrator(tk.Toplevel):
    """Calibration window for selecting pixel and color."""
    
    def __init__(self, parent, screenshot):
        super().__init__(parent)
        
        self.result = None
        
        self.attributes("-topmost", True)
        self.attributes("-fullscreen", True)
        self.grab_set() # Modal window
        self.configure(bg='black')
        
        try:
            # Convert MSS BGRA format to PIL's RGB format
            pil_img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            self.tk_img = ImageTk.PhotoImage(pil_img)

            self.canvas = tk.Canvas(self, cursor="crosshair", bg='black')
            self.canvas.pack(fill="both", expand=True)
            self.canvas.create_image(0, 0, anchor='nw', image=self.tk_img)
            
            # Instructions with a black outline for visibility
            text = "Hold a crystal, aim at a valid block, then LEFT-CLICK the crystal icon in your hotbar to calibrate."
            for dx, dy in [(-2,0), (2,0), (0,-2), (0,2), (-1,-1), (1,-1), (-1,1), (1,1)]:
                self.canvas.create_text(pil_img.width // 2 + dx, 50 + dy, text=text, 
                                        font=("Arial", 18, "bold"), fill="black")
            self.canvas.create_text(pil_img.width // 2, 50, text=text, 
                                    font=("Arial", 18, "bold"), fill="cyan")
            
            self.canvas.bind("<Button-1>", self.on_click)
            self.bind("<Escape>", lambda e: self.destroy())
            self.focus_set()
            
        except Exception as e:
            log(f"Calibrator setup error: {e}")
            self.destroy()

    def on_click(self, event):
        """Handle mouse click for calibration."""
        try:
            # Re-grab the single pixel at the exact moment of the click for accuracy
            with mss.mss() as sct:
                monitor = {'top': event.y, 'left': event.x, 'width': 1, 'height': 1}
                px = sct.grab(monitor).pixel(0, 0)
                
                self.result = {
                    "x": event.x, 
                    "y": event.y, 
                    # Convert BGRA to RGB: [R, G, B]
                    "color": [px[2], px[1], px[0]]
                }
            
            self.destroy() # Close the window
            
        except Exception as e:
            log(f"Calibration click error: {e}")
            self.destroy()