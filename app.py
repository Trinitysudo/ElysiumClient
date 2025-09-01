# FILE: app.py (Complete)

import eel
import os, sys, importlib, threading, json, time
import queue
import traceback

# Import keyboard in the main script to ensure it's available
try:
    import keyboard
except ImportError:
    print("FATAL: 'keyboard' library not found. Please run: pip install keyboard")
    sys.exit()

# --- PATH CONFIGURATION ---
def get_application_path():
    """Returns the base path of the application."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))
BASE_PATH = get_application_path()

# --- GLOBAL STATE ---
loaded_modules = {}
app_settings = {}
running_modules = {}  # Track which modules are currently running
calibration_queue = queue.Queue()
action_lock = threading.Lock()

# --- SETTINGS PERSISTENCE ---
SETTINGS_FILE = os.path.join(BASE_PATH, 'settings.json')

def load_settings():
    """Load settings from disk on startup."""
    global app_settings
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                saved_settings = json.load(f)
                # Merge saved settings with default settings
                for module_name, settings in saved_settings.items():
                    if module_name in app_settings:
                        app_settings[module_name].update(settings)
            print(f"✅ Settings loaded from {SETTINGS_FILE}")
    except Exception as e:
        print(f"⚠️ Could not load settings: {e}")

def save_settings():
    """Save current settings to disk."""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(app_settings, f, indent=2)
        print(f"✅ Settings saved to {SETTINGS_FILE}")
    except Exception as e:
        print(f"❌ Could not save settings: {e}")

# --- CENTRAL HOTKEY MANAGER ---
registered_hotkeys = {}
hotkey_lock = threading.Lock()

def register_hotkey(module_name, key, callback):
    """ Safely registers a hotkey for a module, removing any old one first. """
    with hotkey_lock:
        try:
            # If this module already has a hotkey, unregister it before adding the new one.
            if module_name in registered_hotkeys:
                keyboard.remove_hotkey(registered_hotkeys[module_name])
            
            if key: # Ensure key is not empty
                keyboard.add_hotkey(key, callback, suppress=False)
                registered_hotkeys[module_name] = key
                eel.add_log_entry(f"✅ Hotkey '{key}' registered for {module_name}.")()
        except Exception as e:
            eel.add_log_entry(f"❌ Failed to register hotkey '{key}'. Try running as Administrator. Error: {e}")()

def unregister_hotkey(module_name):
    """ Safely unregisters a module's hotkey. """
    with hotkey_lock:
        if module_name in registered_hotkeys:
            try:
                keyboard.remove_hotkey(registered_hotkeys[module_name])
                del registered_hotkeys[module_name]
            except (Exception, KeyError):
                # Fails silently if the key was already removed or invalid
                pass

# --- Standard App Logic ---
def discover_and_load_modules():
    """Scans the 'modules' directory, loads all modules, and initializes settings."""
    global loaded_modules, app_settings
    modules_dir = os.path.join(BASE_PATH, 'modules')
    if not os.path.exists(modules_dir): return
    if BASE_PATH not in sys.path: sys.path.insert(0, BASE_PATH)
    
    for module_name in os.listdir(modules_dir):
        if os.path.isdir(os.path.join(modules_dir, module_name)) and '__pycache__' not in module_name:
            try:
                module_script = importlib.import_module(f'modules.{module_name}.{module_name}')
                importlib.reload(module_script)
                info = module_script.get_info()
                internal_name = info.get('internal_name', module_name.lower().replace(' ', '_'))
                
                loaded_modules[internal_name] = {'info': info, 'script': module_script}
                
                app_settings[internal_name] = {}
                if 'settings' in info:
                    for key, setting_info in info['settings'].items():
                        app_settings[internal_name][key] = setting_info['default']
                
                if info.get('category') != 'system':
                    app_settings[internal_name]['enabled'] = False
                
                print(f"✅ Loaded module: {info['name']}")
            except Exception as e:
                print(f"❌ Failed to load module '{module_name}': {e}")
                print(traceback.format_exc()) # Print full traceback for easier debugging
    
    # Load saved settings after modules are discovered
    load_settings()

def _get_module_script(module_name):
    """Retrieves a module script and injects dependencies."""
    if module_name not in loaded_modules: return None
    module_script = loaded_modules[module_name]['script']
    
    # Standardized Dependency Injection
    if hasattr(module_script, 'set_eel_instance'):
        module_script.set_eel_instance(eel)
    if hasattr(module_script, 'set_app_instance'):
        module_script.set_app_instance(sys.modules[__name__])
        
    return module_script

# --- CONCURRENT MODULE MANAGEMENT ---
def start_module_safely(module_name):
    """Start a module, inject dependencies, and register its hotkey if needed."""
    with action_lock:
        if module_name in running_modules:
            eel.add_log_entry(f"⚠️ {module_name} is already running!")()
            return False
        
        module_script = _get_module_script(module_name)
        if not module_script:
            eel.add_log_entry(f"❌ Module {module_name} not found!")()
            return False
        
        try:
            if hasattr(module_script, 'start'):
                module_script.start(app_settings[module_name])
                running_modules[module_name] = module_script
                
                # After starting, check for and register a hotkey
                settings = app_settings.get(module_name, {})
                hotkey_value = settings.get('hotkey')
                if hotkey_value and hasattr(module_script, 'hotkey_toggle'):
                    register_hotkey(module_name, hotkey_value, getattr(module_script, 'hotkey_toggle'))

                eel.add_log_entry(f"✅ {module_name} started successfully!")()
                return True
        except Exception:
            eel.add_log_entry(f"❌ Error starting {module_name}:\n{traceback.format_exc()}")()
            return False

def stop_module_safely(module_name, timeout=2.0):
    """
    Stop a module, unregister its hotkey, and wait for the worker thread to terminate.
    """
    with action_lock:
        if module_name not in running_modules:
            return False # Silently fail if not running, it's already stopped.
        
        # Always unregister the hotkey when stopping
        unregister_hotkey(module_name)
        
        module_script = running_modules[module_name]
        
        try:
            if hasattr(module_script, 'stop'):
                module_script.stop()
            
            time.sleep(0.5) # Give it a moment to clear
            
            del running_modules[module_name]
            eel.add_log_entry(f"✅ {module_name} stopped successfully!")()
            return True
        except Exception:
            eel.add_log_entry(f"❌ Error stopping {module_name}:\n{traceback.format_exc()}")()
            if module_name in running_modules:
                del running_modules[module_name]
            return False

def restart_module(module_name):
    """A helper function to safely stop and restart a module."""
    eel.add_log_entry(f"🔄 Restarting {module_name}...")()
    if stop_module_safely(module_name):
        start_module_safely(module_name)

# --- EEL-EXPOSED FUNCTIONS ---
@eel.expose
def get_initial_data():
    """Returns all module information for the UI to build the dashboard."""
    return {
        'modules': {name: data['info'] for name, data in loaded_modules.items()},
        'running_modules': list(running_modules.keys())
    }

@eel.expose
def update_setting(module_name, key, value):
    """Updates a single setting and restarts the module if necessary."""
    if module_name in app_settings and key in app_settings[module_name]:
        app_settings[module_name][key] = value
        save_settings()
        
        if module_name in running_modules:
            eel.add_log_entry(f"Applied setting '{key}' to {module_name}. Restarting module...")()
            restart_module(module_name)

@eel.expose
def update_multiple_settings(module_name, settings_dict):
    """Updates a dictionary of settings and restarts the module."""
    if module_name not in app_settings: return

    for key, value in settings_dict.items():
        if key in app_settings[module_name]:
            app_settings[module_name][key] = value
    
    save_settings()
    eel.add_log_entry(f"✅ Calibration data received for {module_name}. Restarting module to apply...")()
    
    if module_name in running_modules:
        restart_module(module_name)

@eel.expose
def toggle_module(module_name, is_enabled):
    """
    Called by the UI toggle. Starts/stops the module or toggles its active state.
    """
    if 'enabled' in app_settings.get(module_name, {}):
        app_settings[module_name]['enabled'] = is_enabled
        save_settings()

    if is_enabled:
        # If not running, start it.
        if module_name not in running_modules:
            return start_module_safely(module_name)
        # If running, just activate it.
        else:
            module_script = running_modules.get(module_name)
            if hasattr(module_script, 'toggle_activation'):
                success = module_script.toggle_activation(True)
                if not success: eel.set_toggle_state(module_name, False)()
                return success
            else: # Fallback for simple modules
                return True 
    else:
        # If it's running, stop it completely.
        if module_name in running_modules:
            return stop_module_safely(module_name)
        return True # It was already off.

@eel.expose
def stop_all_modules():
    """Emergency stop all running modules."""
    modules_to_stop = list(running_modules.keys())
    for module_name in modules_to_stop:
        stop_module_safely(module_name)
    eel.add_log_entry("🛑 All modules stopped!")()

@eel.expose
def run_module_calibration(module_name, calibration_type='default'):
    """Starts any module calibration in a background thread."""
    module_script = _get_module_script(module_name)
    if not module_script: 
        eel.add_log_entry(f"❌ Cannot calibrate: Module '{module_name}' not loaded.")()
        return

    if hasattr(module_script, 'run_calibration'):
        target_function = getattr(module_script, 'run_calibration')
        threading.Thread(target=target_function, daemon=True).start()
    else:
        eel.add_log_entry(f"⚠️ {module_name} has no 'run_calibration' function.")()


if __name__ == '__main__':
    web_folder = os.path.join(BASE_PATH, 'web')
    if not os.path.isdir(web_folder):
        print(f"FATAL ERROR: 'web' folder not found at '{web_folder}'")
        sys.exit()
        
    eel.init(web_folder)
    discover_and_load_modules()
    print("Starting Elysium UI...")
    eel.start('elysium.html', mode='edge', size=(900, 850), port=0)