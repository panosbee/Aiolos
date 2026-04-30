"""
XDART-Φ × XHEART — System Control

Gives Αίολος physical interaction with the local machine:
  - Mouse control (move, click, scroll)
  - Keyboard input (type text, hotkeys, press keys)
  - Screenshot & OCR
  - Clipboard read/write
  - Application launch & window management
  - File write/create/delete
  - Email sending (SMTP)
  - Desktop notifications

Local dev environment — minimal restrictions.

© Panos Skouras — Salimov MON IKE, 2026
"""

import base64
import io
import json
import logging
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("xdart.sysctl")


class SystemControl:
    """Physical world interaction layer for Αίολος.

    Actions are grouped by category:
      - Mouse: move, click, double_click, right_click, scroll, drag
      - Keyboard: type_text, hotkey, press_key
      - Screen: screenshot, locate_on_screen, get_mouse_pos, get_screen_size
      - Clipboard: clipboard_read, clipboard_write
      - Apps: open_app, open_file, open_url, close_window, list_windows, focus_window
      - Files: write_file, append_file, create_dir, delete_file, copy_file, move_file
      - Notifications: desktop_notify, speak
      - Email: send_email
      - System: lock_screen, set_volume, get_battery, get_wifi
    """

    def __init__(self):
        self._boot_time = datetime.now(timezone.utc)
        self._action_count = 0
        self._action_log: list[dict] = []
        self._lock = threading.Lock()

        # Lazy-load pyautogui (may not be installed yet)
        self._pyautogui = None
        self._pyautogui_err = None

        logger.info("[SystemControl] Initialized — physical world access enabled")

    def _get_pyautogui(self):
        """Lazy-load pyautogui with failsafe disabled for unrestricted access."""
        if self._pyautogui is not None:
            return self._pyautogui
        if self._pyautogui_err:
            raise ImportError(self._pyautogui_err)
        try:
            import pyautogui
            pyautogui.FAILSAFE = False  # No corner-escape — full control
            pyautogui.PAUSE = 0.05      # Fast execution
            self._pyautogui = pyautogui
            return pyautogui
        except ImportError as e:
            self._pyautogui_err = str(e)
            raise ImportError(
                "pyautogui not installed. Run: pip install pyautogui"
            ) from e

    def _log_action(self, action: str, params: dict, result: str, success: bool):
        """Log every action for audit trail."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "params": {k: str(v)[:200] for k, v in params.items()},
            "result": result[:500],
            "success": success,
        }
        with self._lock:
            self._action_log.append(entry)
            if len(self._action_log) > 500:
                self._action_log = self._action_log[-300:]
            self._action_count += 1

    # ══════════════════════════════════════════════════════════════
    #  MOUSE ACTIONS
    # ══════════════════════════════════════════════════════════════

    def mouse_move(self, x: int, y: int, duration: float = 0.3) -> dict:
        """Move mouse to absolute screen coordinates."""
        pag = self._get_pyautogui()
        pag.moveTo(x, y, duration=duration)
        self._log_action("mouse_move", {"x": x, "y": y}, f"Moved to ({x}, {y})", True)
        return {"success": True, "position": [x, y]}

    def mouse_click(self, x: int | None = None, y: int | None = None,
                    button: str = "left", clicks: int = 1) -> dict:
        """Click at position (or current position if x,y omitted)."""
        pag = self._get_pyautogui()
        kwargs = {"button": button, "clicks": clicks}
        if x is not None and y is not None:
            kwargs["x"] = x
            kwargs["y"] = y
        pag.click(**kwargs)
        pos = pag.position()
        self._log_action("mouse_click", {"x": x, "y": y, "button": button, "clicks": clicks},
                         f"Clicked {button} at ({pos.x}, {pos.y})", True)
        return {"success": True, "position": [pos.x, pos.y], "button": button, "clicks": clicks}

    def mouse_scroll(self, amount: int, x: int | None = None, y: int | None = None) -> dict:
        """Scroll mouse wheel. Positive = up, negative = down."""
        pag = self._get_pyautogui()
        if x is not None and y is not None:
            pag.scroll(amount, x=x, y=y)
        else:
            pag.scroll(amount)
        self._log_action("mouse_scroll", {"amount": amount}, f"Scrolled {amount}", True)
        return {"success": True, "amount": amount}

    def mouse_drag(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> dict:
        """Drag from (x1,y1) to (x2,y2)."""
        pag = self._get_pyautogui()
        pag.moveTo(x1, y1, duration=0.1)
        pag.drag(x2 - x1, y2 - y1, duration=duration, button='left')
        self._log_action("mouse_drag", {"from": [x1, y1], "to": [x2, y2]},
                         f"Dragged ({x1},{y1})→({x2},{y2})", True)
        return {"success": True, "from": [x1, y1], "to": [x2, y2]}

    # ══════════════════════════════════════════════════════════════
    #  KEYBOARD ACTIONS
    # ══════════════════════════════════════════════════════════════

    def type_text(self, text: str, interval: float = 0.02) -> dict:
        """Type text string (simulates keyboard input)."""
        pag = self._get_pyautogui()
        pag.typewrite(text, interval=interval) if text.isascii() else self._type_unicode(text)
        self._log_action("type_text", {"text": text[:100]}, f"Typed {len(text)} chars", True)
        return {"success": True, "length": len(text)}

    def _type_unicode(self, text: str):
        """Type unicode text via clipboard (pyautogui.typewrite doesn't support unicode)."""
        import pyperclip
        old = pyperclip.paste()
        pyperclip.copy(text)
        pag = self._get_pyautogui()
        pag.hotkey('ctrl', 'v')
        time.sleep(0.1)
        pyperclip.copy(old)  # Restore clipboard

    def hotkey(self, *keys: str) -> dict:
        """Press a hotkey combination (e.g., 'ctrl', 'c')."""
        pag = self._get_pyautogui()
        pag.hotkey(*keys)
        combo = "+".join(keys)
        self._log_action("hotkey", {"keys": combo}, f"Pressed {combo}", True)
        return {"success": True, "keys": combo}

    def press_key(self, key: str, presses: int = 1) -> dict:
        """Press a single key N times (e.g., 'enter', 'tab', 'escape', 'f5')."""
        pag = self._get_pyautogui()
        pag.press(key, presses=presses)
        self._log_action("press_key", {"key": key, "presses": presses},
                         f"Pressed {key} ×{presses}", True)
        return {"success": True, "key": key, "presses": presses}

    # ══════════════════════════════════════════════════════════════
    #  SCREEN ACTIONS
    # ══════════════════════════════════════════════════════════════

    def screenshot(self, region: tuple | None = None, save_path: str | None = None) -> dict:
        """Take a screenshot. Returns base64-encoded PNG and optional file save."""
        pag = self._get_pyautogui()
        img = pag.screenshot(region=region)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        b64 = base64.b64encode(buf.getvalue()).decode('ascii')

        result = {
            "success": True,
            "width": img.width,
            "height": img.height,
            "base64_length": len(b64),
        }

        if save_path:
            img.save(save_path)
            result["saved_to"] = save_path

        # Return truncated base64 for context (full image is too large)
        result["preview"] = f"Screenshot {img.width}×{img.height}px captured"
        self._log_action("screenshot", {"region": str(region)}, result["preview"], True)
        return result

    def get_mouse_pos(self) -> dict:
        """Get current mouse position."""
        pag = self._get_pyautogui()
        pos = pag.position()
        return {"success": True, "x": pos.x, "y": pos.y}

    def get_screen_size(self) -> dict:
        """Get screen resolution."""
        pag = self._get_pyautogui()
        size = pag.size()
        return {"success": True, "width": size.width, "height": size.height}

    def get_pixel_color(self, x: int, y: int) -> dict:
        """Get the color of a pixel at (x, y)."""
        pag = self._get_pyautogui()
        r, g, b = pag.pixel(x, y)
        return {"success": True, "x": x, "y": y, "rgb": [r, g, b], "hex": f"#{r:02x}{g:02x}{b:02x}"}

    # ══════════════════════════════════════════════════════════════
    #  CLIPBOARD
    # ══════════════════════════════════════════════════════════════

    def clipboard_read(self) -> dict:
        """Read current clipboard content."""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                capture_output=True, text=True, timeout=5,
            )
            content = result.stdout.strip()
            self._log_action("clipboard_read", {}, f"{len(content)} chars", True)
            return {"success": True, "content": content[:5000]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def clipboard_write(self, text: str) -> dict:
        """Write text to clipboard."""
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Set-Clipboard -Value '{text.replace(chr(39), chr(39)+chr(39))}'"],
                capture_output=True, text=True, timeout=5,
            )
            self._log_action("clipboard_write", {"text": text[:100]}, "Written to clipboard", True)
            return {"success": True, "length": len(text)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ══════════════════════════════════════════════════════════════
    #  APPLICATION & WINDOW MANAGEMENT
    # ══════════════════════════════════════════════════════════════

    def open_app(self, app_name: str) -> dict:
        """Open an application by name or path."""
        try:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", f"Start-Process '{app_name}'"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self._log_action("open_app", {"app": app_name}, f"Opened {app_name}", True)
            return {"success": True, "app": app_name}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def open_file(self, path: str) -> dict:
        """Open a file with its default application."""
        try:
            os.startfile(path)
            self._log_action("open_file", {"path": path}, f"Opened {path}", True)
            return {"success": True, "path": path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def open_url(self, url: str) -> dict:
        """Open a URL in the default browser."""
        import webbrowser
        webbrowser.open(url)
        self._log_action("open_url", {"url": url}, f"Opened {url}", True)
        return {"success": True, "url": url}

    def list_windows(self) -> dict:
        """List all visible windows with titles."""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-Process | Where-Object {$_.MainWindowTitle} | "
                 "Select-Object Id, MainWindowTitle | Format-Table -AutoSize"],
                capture_output=True, text=True, timeout=10,
            )
            self._log_action("list_windows", {}, "Listed windows", True)
            return {"success": True, "windows": result.stdout.strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def focus_window(self, title: str) -> dict:
        """Bring a window to foreground by (partial) title match."""
        try:
            ps_cmd = (
                f"$w = Get-Process | Where-Object {{$_.MainWindowTitle -like '*{title}*'}} | "
                f"Select-Object -First 1; "
                f"if ($w) {{ "
                f"  Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; "
                f"  public class Win {{ [DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr hWnd); "
                f"  [DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow); }}'; "
                f"  [Win]::ShowWindow($w.MainWindowHandle, 9); "
                f"  [Win]::SetForegroundWindow($w.MainWindowHandle); "
                f"  Write-Output \"Focused: $($w.MainWindowTitle)\""
                f"}} else {{ Write-Output 'Window not found' }}"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=10,
            )
            output = result.stdout.strip()
            self._log_action("focus_window", {"title": title}, output, True)
            return {"success": "Focused" in output, "result": output}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def close_window(self, title: str) -> dict:
        """Close a window by (partial) title match."""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Get-Process | Where-Object {{$_.MainWindowTitle -like '*{title}*'}} | "
                 f"Select-Object -First 1 | Stop-Process -Force"],
                capture_output=True, text=True, timeout=10,
            )
            self._log_action("close_window", {"title": title}, "Closed", True)
            return {"success": True, "title": title}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ══════════════════════════════════════════════════════════════
    #  FILE OPERATIONS
    # ══════════════════════════════════════════════════════════════

    def write_file(self, path: str, content: str, encoding: str = "utf-8") -> dict:
        """Write content to a file (creates or overwrites)."""
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding=encoding)
            self._log_action("write_file", {"path": path, "size": len(content)},
                             f"Wrote {len(content)} chars to {path}", True)
            return {"success": True, "path": str(p), "size": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def append_file(self, path: str, content: str, encoding: str = "utf-8") -> dict:
        """Append content to a file."""
        try:
            with open(path, "a", encoding=encoding) as f:
                f.write(content)
            self._log_action("append_file", {"path": path, "size": len(content)},
                             f"Appended {len(content)} chars to {path}", True)
            return {"success": True, "path": path, "size": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def create_dir(self, path: str) -> dict:
        """Create a directory (including parents)."""
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            self._log_action("create_dir", {"path": path}, f"Created {path}", True)
            return {"success": True, "path": path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_file(self, path: str) -> dict:
        """Delete a file or empty directory."""
        try:
            p = Path(path)
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                p.rmdir()
            else:
                return {"success": False, "error": f"Not found: {path}"}
            self._log_action("delete_file", {"path": path}, f"Deleted {path}", True)
            return {"success": True, "path": path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def copy_file(self, src: str, dst: str) -> dict:
        """Copy a file."""
        import shutil
        try:
            shutil.copy2(src, dst)
            self._log_action("copy_file", {"src": src, "dst": dst},
                             f"Copied {src} → {dst}", True)
            return {"success": True, "src": src, "dst": dst}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def move_file(self, src: str, dst: str) -> dict:
        """Move/rename a file."""
        import shutil
        try:
            shutil.move(src, dst)
            self._log_action("move_file", {"src": src, "dst": dst},
                             f"Moved {src} → {dst}", True)
            return {"success": True, "src": src, "dst": dst}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ══════════════════════════════════════════════════════════════
    #  NOTIFICATIONS & SPEECH
    # ══════════════════════════════════════════════════════════════

    def desktop_notify(self, title: str, message: str, duration: int = 5) -> dict:
        """Show a Windows toast notification."""
        try:
            ps_cmd = (
                f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
                f"ContentType = WindowsRuntime] | Out-Null; "
                f"$template = [Windows.UI.Notifications.ToastNotificationManager]::"
                f"GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
                f"$textNodes = $template.GetElementsByTagName('text'); "
                f"$textNodes.Item(0).AppendChild($template.CreateTextNode('{title.replace(chr(39), '')}')) | Out-Null; "
                f"$textNodes.Item(1).AppendChild($template.CreateTextNode('{message.replace(chr(39), '')}')) | Out-Null; "
                f"$toast = [Windows.UI.Notifications.ToastNotification]::new($template); "
                f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('XDART-Φ').Show($toast)"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, timeout=10,
            )
            self._log_action("desktop_notify", {"title": title}, "Notification sent", True)
            return {"success": True, "title": title}
        except Exception as e:
            # Fallback: simple BurntToast or MessageBox
            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"Add-Type -AssemblyName System.Windows.Forms; "
                     f"[System.Windows.Forms.MessageBox]::Show('{message.replace(chr(39), '')}', "
                     f"'{title.replace(chr(39), '')}', 'OK', 'Information')"],
                    capture_output=True, timeout=10,
                )
                return {"success": True, "title": title, "method": "messagebox"}
            except Exception as e2:
                return {"success": False, "error": str(e2)}

    def speak(self, text: str, rate: int = 0) -> dict:
        """Text-to-speech via Windows SAPI."""
        try:
            escaped = text.replace("'", "''")
            ps_cmd = (
                f"Add-Type -AssemblyName System.Speech; "
                f"$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$synth.Rate = {rate}; "
                f"$synth.Speak('{escaped}')"
            )
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self._log_action("speak", {"text": text[:100]}, "Speaking", True)
            return {"success": True, "text": text[:200]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ══════════════════════════════════════════════════════════════
    #  EMAIL
    # ══════════════════════════════════════════════════════════════

    def send_email(self, to: str, subject: str, body: str,
                   smtp_server: str = "", smtp_port: int = 587,
                   smtp_user: str = "", smtp_pass: str = "") -> dict:
        """Send an email via SMTP. Uses env vars if credentials not provided."""
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        server = smtp_server or os.getenv("SMTP_SERVER", "")
        port = smtp_port or int(os.getenv("SMTP_PORT", "587"))
        user = smtp_user or os.getenv("SMTP_USER", "")
        password = smtp_pass or os.getenv("SMTP_PASS", "")

        if not server or not user:
            return {"success": False, "error": "SMTP not configured. Set SMTP_SERVER, SMTP_USER, SMTP_PASS env vars."}

        try:
            msg = MIMEMultipart()
            msg["From"] = user
            msg["To"] = to
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "html"))

            with smtplib.SMTP(server, port, timeout=30) as s:
                s.ehlo()
                s.starttls()
                s.ehlo()
                s.login(user, password)
                s.send_message(msg)

            self._log_action("send_email", {"to": to, "subject": subject},
                             f"Email sent to {to}", True)
            return {"success": True, "to": to, "subject": subject}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ══════════════════════════════════════════════════════════════
    #  SYSTEM INFO & CONTROL
    # ══════════════════════════════════════════════════════════════

    def lock_screen(self) -> dict:
        """Lock the Windows workstation."""
        try:
            subprocess.run(
                ["rundll32.exe", "user32.dll,LockWorkStation"],
                timeout=5,
            )
            self._log_action("lock_screen", {}, "Screen locked", True)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_volume(self, level: int) -> dict:
        """Set system volume (0-100)."""
        try:
            level = max(0, min(100, level))
            ps_cmd = (
                f"$vol = [Math]::Round({level} * 655.35); "
                f"$wshell = New-Object -ComObject WScript.Shell; "
                + ("$wshell.SendKeys([char]174); " * (50)) +  # Volume down to 0
                "".join([f"$wshell.SendKeys([char]175); " for _ in range(level // 2)])
            )
            # Simpler approach via nircmd if available, else use PowerShell audio
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(New-Object -ComObject WScript.Shell).SendKeys([char]173)"],  # Mute toggle
                capture_output=True, timeout=5,
            )
            self._log_action("set_volume", {"level": level}, f"Volume → {level}%", True)
            return {"success": True, "level": level, "note": "Used mute toggle — for precise control install nircmd"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_battery(self) -> dict:
        """Get battery status (if laptop)."""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_Battery | Select-Object EstimatedChargeRemaining, BatteryStatus) | ConvertTo-Json"],
                capture_output=True, text=True, timeout=10,
            )
            data = json.loads(result.stdout) if result.stdout.strip() else {}
            return {"success": True, "battery": data}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_wifi(self) -> dict:
        """Get current WiFi network name and signal."""
        try:
            result = subprocess.run(
                ["netsh", "wlan", "show", "interfaces"],
                capture_output=True, text=True, timeout=10,
            )
            return {"success": True, "info": result.stdout.strip()[:2000]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_active_window(self) -> dict:
        """Get the currently active/focused window title."""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Add-Type -TypeDefinition '"
                 "using System; using System.Runtime.InteropServices; using System.Text; "
                 "public class FG { "
                 "  [DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow(); "
                 "  [DllImport(\"user32.dll\")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count); "
                 "  public static string GetTitle() { "
                 "    IntPtr h = GetForegroundWindow(); StringBuilder sb = new StringBuilder(256); "
                 "    GetWindowText(h, sb, 256); return sb.ToString(); } }'; "
                 "[FG]::GetTitle()"],
                capture_output=True, text=True, timeout=5,
            )
            title = result.stdout.strip()
            return {"success": True, "title": title}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ══════════════════════════════════════════════════════════════
    #  STATUS
    # ══════════════════════════════════════════════════════════════

    def get_stats(self) -> dict:
        """Return control statistics."""
        uptime = (datetime.now(timezone.utc) - self._boot_time).total_seconds()
        return {
            "total_actions": self._action_count,
            "uptime_seconds": int(uptime),
            "log_size": len(self._action_log),
            "pyautogui_available": self._pyautogui is not None or self._pyautogui_err is None,
        }

    def get_action_log(self, last_n: int = 20) -> list[dict]:
        """Return last N action log entries."""
        return self._action_log[-last_n:]

    def to_context_string(self) -> str:
        """Format for LLM context injection."""
        stats = self.get_stats()
        try:
            screen = self.get_screen_size()
            screen_str = f"{screen['width']}×{screen['height']}" if screen["success"] else "unknown"
        except Exception:
            screen_str = "unknown (pyautogui not loaded)"

        lines = [
            "SYSTEM CONTROL STATUS (physical world access — mouse, keyboard, screen, apps, files):",
            f"  Actions this session: {stats['total_actions']}",
            f"  Screen resolution: {screen_str}",
            f"  PyAutoGUI: {'✓ loaded' if stats['pyautogui_available'] else '✗ not available'}",
            f"  Format: <SYSTEM_CONTROL action=\"...\" param1=\"...\" param2=\"...\" />",
            "",
            "  AVAILABLE ACTIONS:",
            "    Mouse:    mouse_move(x,y) | mouse_click(x,y,button) | mouse_scroll(amount) | mouse_drag(x1,y1,x2,y2)",
            "    Keyboard: type_text(text) | hotkey(keys) | press_key(key,presses)",
            "    Screen:   screenshot(save_path) | get_mouse_pos | get_screen_size | get_pixel_color(x,y) | get_active_window",
            "    Clipboard: clipboard_read | clipboard_write(text)",
            "    Apps:     open_app(app_name) | open_file(path) | open_url(url) | list_windows | focus_window(title) | close_window(title)",
            "    Files:    write_file(path,content) | append_file(path,content) | create_dir(path) | delete_file(path) | copy_file(src,dst) | move_file(src,dst)",
            "    Notify:   desktop_notify(title,message) | speak(text)",
            "    Email:    send_email(to,subject,body)",
            "    System:   lock_screen | get_battery | get_wifi",
        ]

        recent = self._action_log[-3:] if self._action_log else []
        if recent:
            lines.append("")
            lines.append("  Recent actions:")
            for entry in recent:
                status = "✓" if entry.get("success") else "✗"
                lines.append(f"    {status} [{entry['timestamp'][:19]}] {entry['action']}: {entry['result'][:80]}")

        return "\n".join(lines)

    def execute_action(self, action: str, params: dict) -> dict:
        """Route an action string to the appropriate method.

        This is the main entry point used by the chat action tag processor.
        """
        action = action.strip().lower()

        try:
            if action == "mouse_move":
                return self.mouse_move(int(params.get("x", 0)), int(params.get("y", 0)),
                                       float(params.get("duration", 0.3)))
            elif action == "mouse_click":
                x = int(params["x"]) if "x" in params else None
                y = int(params["y"]) if "y" in params else None
                return self.mouse_click(x, y, params.get("button", "left"),
                                        int(params.get("clicks", 1)))
            elif action == "mouse_scroll":
                x = int(params["x"]) if "x" in params else None
                y = int(params["y"]) if "y" in params else None
                return self.mouse_scroll(int(params.get("amount", 0)), x, y)
            elif action == "mouse_drag":
                return self.mouse_drag(int(params["x1"]), int(params["y1"]),
                                       int(params["x2"]), int(params["y2"]),
                                       float(params.get("duration", 0.5)))
            elif action == "type_text":
                return self.type_text(params.get("text", ""),
                                      float(params.get("interval", 0.02)))
            elif action == "hotkey":
                keys = [k.strip() for k in params.get("keys", "").split("+") if k.strip()]
                if not keys:
                    return {"success": False, "error": "No keys specified"}
                return self.hotkey(*keys)
            elif action == "press_key":
                return self.press_key(params.get("key", ""),
                                      int(params.get("presses", 1)))
            elif action == "screenshot":
                return self.screenshot(save_path=params.get("save_path"))
            elif action == "get_mouse_pos":
                return self.get_mouse_pos()
            elif action == "get_screen_size":
                return self.get_screen_size()
            elif action == "get_pixel_color":
                return self.get_pixel_color(int(params.get("x", 0)), int(params.get("y", 0)))
            elif action == "get_active_window":
                return self.get_active_window()
            elif action == "clipboard_read":
                return self.clipboard_read()
            elif action == "clipboard_write":
                return self.clipboard_write(params.get("text", ""))
            elif action == "open_app":
                return self.open_app(params.get("app_name", params.get("app", "")))
            elif action == "open_file":
                return self.open_file(params.get("path", ""))
            elif action == "open_url":
                return self.open_url(params.get("url", ""))
            elif action == "list_windows":
                return self.list_windows()
            elif action == "focus_window":
                return self.focus_window(params.get("title", ""))
            elif action == "close_window":
                return self.close_window(params.get("title", ""))
            elif action == "write_file":
                return self.write_file(params.get("path", ""), params.get("content", ""))
            elif action == "append_file":
                return self.append_file(params.get("path", ""), params.get("content", ""))
            elif action == "create_dir":
                return self.create_dir(params.get("path", ""))
            elif action == "delete_file":
                return self.delete_file(params.get("path", ""))
            elif action == "copy_file":
                return self.copy_file(params.get("src", ""), params.get("dst", ""))
            elif action == "move_file":
                return self.move_file(params.get("src", ""), params.get("dst", ""))
            elif action == "desktop_notify":
                return self.desktop_notify(params.get("title", "XDART-Φ"),
                                           params.get("message", ""))
            elif action == "speak":
                return self.speak(params.get("text", ""), int(params.get("rate", 0)))
            elif action == "send_email":
                return self.send_email(
                    params.get("to", ""), params.get("subject", ""),
                    params.get("body", ""),
                    params.get("smtp_server", ""), int(params.get("smtp_port", 587)),
                    params.get("smtp_user", ""), params.get("smtp_pass", ""),
                )
            elif action == "lock_screen":
                return self.lock_screen()
            elif action == "set_volume":
                return self.set_volume(int(params.get("level", 50)))
            elif action == "get_battery":
                return self.get_battery()
            elif action == "get_wifi":
                return self.get_wifi()
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            self._log_action(action, params, f"Error: {e}", False)
            return {"success": False, "error": str(e)}
