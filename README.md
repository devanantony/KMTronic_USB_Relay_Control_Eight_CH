# KMtronic U8CR 8-Channel Relay Control

A Windows desktop app for controlling a KMtronic U8CR eight-channel USB relay controller.

## Features

- Scan for and select a serial (COM) port.
- Connect to or disconnect from the relay controller.
- Switch individual relays, or use **ALL ON** and **ALL OFF**.
- Edit and automatically save a description for each relay.
- Save the selected COM port and last commanded relay states.

## Requirements

- Windows
- Python 3
- `pyserial` for running the Python script

## Run from Python

Install the dependency and launch the app:

```powershell
py -m pip install pyserial
py kmtronic_u8cr_control.py