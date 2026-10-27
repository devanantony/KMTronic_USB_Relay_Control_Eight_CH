"""KMtronic U8CR 8-channel USB relay controller.

Requirements:
    py -m pip install pyserial

Features:
- Simple, compact, light-themed Tkinter UI (no CustomTkinter dependency)
- COM-port selection, scan, connect and disconnect
- Individual relay ON/OFF controls plus ALL ON and ALL OFF
- Editable description for each relay, saved between launches
- Saves the last commanded relay states and COM port
- Reconnects to the last COM port and reapplies saved states at startup

Note: Indicators show the last command successfully sent, not physical-contact
feedback. Reapplying saved ON states at startup may energize connected equipment.
"""

from __future__ import annotations

import json
import os
import tempfile
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path

import serial
from serial.tools import list_ports

APP_NAME = "KMtronic U8CR Relay Control"
BAUD_RATE = 9600
DATA_FILE = Path(os.getenv("APPDATA", str(Path.home()))) / "KMtronicU8CR" / "state.json"
DEFAULT_DESCRIPTIONS = [f"Relay {i}" for i in range(1, 9)]


def load_state() -> dict:
    default = {
        "port": "",
        "relay_states": [False] * 8,
        "relay_descriptions": DEFAULT_DESCRIPTIONS.copy(),
    }
    try:
        with DATA_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        states = data.get("relay_states", default["relay_states"])
        descriptions = data.get("relay_descriptions", default["relay_descriptions"])
        if not isinstance(states, list) or len(states) != 8:
            states = default["relay_states"]
        if not isinstance(descriptions, list) or len(descriptions) != 8:
            descriptions = default["relay_descriptions"]
        return {
            "port": str(data.get("port", "")),
            "relay_states": [bool(v) for v in states],
            "relay_descriptions": [str(v)[:100] for v in descriptions],
        }
    except (OSError, ValueError, TypeError):
        return default


def save_state(port: str, states: list[bool], descriptions: list[str]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "port": port,
        "relay_states": [bool(v) for v in states],
        "relay_descriptions": [str(v)[:100] for v in descriptions],
    }
    fd, temp_name = tempfile.mkstemp(prefix="state_", suffix=".tmp", dir=str(DATA_FILE.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, DATA_FILE)
    finally:
        try:
            if os.path.exists(temp_name):
                os.remove(temp_name)
        except OSError:
            pass


class U8CRApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("690x485")
        self.minsize(620, 430)
        self.configure(bg="#f4f6f8")

        self.saved = load_state()
        self.relay_states = self.saved["relay_states"].copy()
        self.descriptions = self.saved["relay_descriptions"].copy()
        self.serial_connection: serial.Serial | None = None
        self.rows: list[dict] = []

        self._setup_styles()
        self._build_ui()
        self.refresh_ports()
        if self.saved["port"]:
            self.port_var.set(self.saved["port"])
            self.after(350, self.connect_and_restore)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _setup_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#f4f6f8")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("TLabel", background="#f4f6f8", foreground="#202833", font=("Segoe UI", 9))
        style.configure("Title.TLabel", font=("Segoe UI", 15, "bold"), background="#f4f6f8")
        style.configure("Small.TLabel", font=("Segoe UI", 8), foreground="#5b6572", background="#f4f6f8")
        style.configure("TButton", font=("Segoe UI", 9), padding=(8, 4))
        style.configure("On.TButton", foreground="#ffffff", background="#16845b")
        style.map("On.TButton", background=[("active", "#116c49")])
        style.configure("Off.TButton", foreground="#ffffff", background="#b83b43")
        style.map("Off.TButton", background=[("active", "#982e35")])
        style.configure("AllOn.TButton", foreground="#ffffff", background="#16845b", padding=(12, 6))
        style.map("AllOn.TButton", background=[("active", "#116c49")])
        style.configure("AllOff.TButton", foreground="#ffffff", background="#b83b43", padding=(12, 6))
        style.map("AllOff.TButton", background=[("active", "#982e35")])

    def _build_ui(self):
        outer = ttk.Frame(self, padding=(14, 10))
        outer.pack(fill="both", expand=True)

        heading = ttk.Frame(outer)
        heading.pack(fill="x", pady=(0, 8))
        ttk.Label(heading, text="KMtronic U8CR", style="Title.TLabel").pack(side="left")
        self.connection_label = ttk.Label(heading, text="● Disconnected", foreground="#b83b43")
        self.connection_label.pack(side="right", padx=(8, 0))

        connection = ttk.Frame(outer)
        connection.pack(fill="x", pady=(0, 8))
        ttk.Label(connection, text="COM port:").pack(side="left", padx=(0, 5))
        self.port_var = tk.StringVar(value="")
        self.port_combo = ttk.Combobox(connection, textvariable=self.port_var, width=12, state="readonly")
        self.port_combo.pack(side="left", padx=(0, 5))
        ttk.Button(connection, text="Scan", command=self.refresh_ports).pack(side="left", padx=(0, 5))
        ttk.Button(connection, text="Connect / Restore", command=self.connect_and_restore).pack(side="left", padx=(0, 5))
        ttk.Button(connection, text="Disconnect", command=self.disconnect).pack(side="left")

        bulk = ttk.Frame(outer)
        bulk.pack(fill="x", pady=(0, 8))
        ttk.Button(bulk, text="ALL ON", style="AllOn.TButton", command=lambda: self.set_all(True)).pack(side="left", padx=(0, 6))
        ttk.Button(bulk, text="ALL OFF", style="AllOff.TButton", command=lambda: self.set_all(False)).pack(side="left")
        ttk.Label(bulk, text="Descriptions are saved automatically.", style="Small.TLabel").pack(side="right")

        table = ttk.Frame(outer)
        table.pack(fill="both", expand=True)
        table.columnconfigure(1, weight=1)
        for col, text in enumerate(("Channel", "Relay description", "Command state", "Control")):
            ttk.Label(table, text=text, font=("Segoe UI", 9, "bold")).grid(row=0, column=col, sticky="w", padx=(5, 8), pady=(0, 4))

        for i in range(8):
            row_bg = "#ffffff" if i % 2 == 0 else "#edf1f5"
            channel = tk.Label(table, text=f"Relay {i + 1}", bg=row_bg, fg="#202833", width=9, anchor="w", padx=7, pady=4, font=("Segoe UI", 9))
            channel.grid(row=i + 1, column=0, sticky="nsew")
            desc_var = tk.StringVar(value=self.descriptions[i])
            desc_entry = tk.Entry(table, textvariable=desc_var, relief="solid", bd=1, bg="#ffffff", fg="#202833", insertbackground="#202833", font=("Segoe UI", 9))
            desc_entry.grid(row=i + 1, column=1, sticky="ew", padx=(4, 8), pady=2, ipady=2)
            status = tk.Label(table, text="● ON" if self.relay_states[i] else "● OFF", width=9, bg=row_bg, fg="#16845b" if self.relay_states[i] else "#6b7280", anchor="w", font=("Segoe UI", 9, "bold"))
            status.grid(row=i + 1, column=2, sticky="w", padx=(0, 8))
            button = ttk.Button(table, text="Turn OFF" if self.relay_states[i] else "Turn ON", width=10, style="Off.TButton" if self.relay_states[i] else "On.TButton", command=lambda index=i: self.toggle_relay(index))
            button.grid(row=i + 1, column=3, sticky="e", padx=(0, 4), pady=2)
            desc_var.trace_add("write", lambda *_args, index=i, var=desc_var: self._description_changed(index, var.get()))
            desc_entry.bind("<FocusOut>", lambda _event: self.save_current_state())
            desc_entry.bind("<Return>", lambda _event: self.save_current_state())
            self.rows.append({"description_var": desc_var, "entry": desc_entry, "status": status, "button": button, "bg": row_bg})

        ttk.Separator(outer).pack(fill="x", pady=(8, 5))
        self.status_var = tk.StringVar(value="Ready. Select a COM port and connect.")
        ttk.Label(outer, textvariable=self.status_var, style="Small.TLabel", anchor="w").pack(fill="x")
        self._render_states()

    def _description_changed(self, index: int, value: str):
        self.descriptions[index] = value[:100]
        # Save immediately so descriptions persist even if the app closes unexpectedly.
        self.save_current_state()

    def refresh_ports(self):
        ports = sorted(list_ports.comports(), key=lambda p: p.device)
        values = [p.device for p in ports] or ["No COM ports found"]
        current = self.port_var.get()
        self.port_combo.configure(values=values)
        if current in values:
            self.port_var.set(current)
        elif self.saved["port"] in values:
            self.port_var.set(self.saved["port"])
        else:
            self.port_var.set(values[0])
        self.set_status(f"Found {len(ports)} serial port(s).")

    def connect_and_restore(self):
        port = self.port_var.get().strip()
        if not port or port == "No COM ports found":
            self.set_status("No COM port found. Connect the U8CR and click Scan.")
            return
        self.disconnect(silent=True)
        try:
            self.serial_connection = serial.Serial(
                port=port, baudrate=BAUD_RATE, bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                timeout=0.5, write_timeout=1.0,
            )
            self.saved["port"] = port
            self.connection_label.configure(text=f"● Connected: {port}", foreground="#16845b")
            for i, is_on in enumerate(self.relay_states):
                self._send_command(i, is_on)
            self.save_current_state()
            self.set_status(f"Connected to {port}; saved relay states restored.")
        except (serial.SerialException, OSError) as exc:
            self.serial_connection = None
            self.connection_label.configure(text="● Disconnected", foreground="#b83b43")
            self.set_status(f"Could not open {port}: {exc}")
            messagebox.showerror("Connection failed", f"Could not open {port}.\n\n{exc}")

    def _send_command(self, index: int, is_on: bool):
        if self.serial_connection is None or not self.serial_connection.is_open:
            raise serial.SerialException("Not connected to the relay controller.")
        # U8CR command: 0xFF, relay number (1..8), state (0x00=OFF, 0x01=ON)
        packet = bytes((0xFF, index + 1, 0x01 if is_on else 0x00))
        self.serial_connection.write(packet)
        self.serial_connection.flush()

    def toggle_relay(self, index: int):
        self._set_relay(index, not self.relay_states[index])

    def _set_relay(self, index: int, requested_state: bool):
        try:
            self._send_command(index, requested_state)
            self.relay_states[index] = requested_state
            self._render_states()
            self.save_current_state()
            self.set_status(f"Relay {index + 1}: {'ON' if requested_state else 'OFF'} command sent.")
        except (serial.SerialException, OSError) as exc:
            self.set_status(f"Command failed for relay {index + 1}: {exc}")
            messagebox.showerror("Relay command failed", str(exc))

    def set_all(self, requested_state: bool):
        if self.serial_connection is None or not self.serial_connection.is_open:
            self.set_status("Connect to the U8CR before using ALL ON / ALL OFF.")
            messagebox.showwarning("Not connected", "Connect to the U8CR before using ALL ON / ALL OFF.")
            return
        completed = 0
        for i in range(8):
            try:
                self._send_command(i, requested_state)
                self.relay_states[i] = requested_state
                completed += 1
            except (serial.SerialException, OSError) as exc:
                self._render_states()
                self.save_current_state()
                self.set_status(f"Bulk command stopped at relay {i + 1}: {exc}")
                messagebox.showerror("Bulk command failed", f"Command failed at relay {i + 1}.\n\n{exc}")
                return
        self._render_states()
        self.save_current_state()
        self.set_status(f"{('ALL ON' if requested_state else 'ALL OFF')} command sent to all {completed} relays.")

    def _render_states(self):
        for i, is_on in enumerate(self.relay_states):
            row = self.rows[i]
            row["status"].configure(text="● ON" if is_on else "● OFF", fg="#16845b" if is_on else "#6b7280")
            row["button"].configure(text="Turn OFF" if is_on else "Turn ON", style="Off.TButton" if is_on else "On.TButton")

    def disconnect(self, silent=False):
        if self.serial_connection is not None:
            try:
                self.serial_connection.close()
            except (serial.SerialException, OSError):
                pass
            self.serial_connection = None
        if hasattr(self, "connection_label"):
            self.connection_label.configure(text="● Disconnected", foreground="#b83b43")
        if not silent and hasattr(self, "status_var"):
            self.set_status("Disconnected. Saved states and descriptions are unchanged.")

    def save_current_state(self):
        try:
            port = self.port_var.get() if hasattr(self, "port_var") else self.saved.get("port", "")
            save_state(port, self.relay_states, self.descriptions)
        except OSError as exc:
            if hasattr(self, "status_var"):
                self.set_status(f"Could not save settings: {exc}")

    def set_status(self, text: str):
        if hasattr(self, "status_var"):
            self.status_var.set(text)

    def on_close(self):
        self.save_current_state()
        self.disconnect(silent=True)
        self.destroy()


if __name__ == "__main__":
    app = U8CRApp()
    app.mainloop()
