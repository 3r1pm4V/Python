import os
import string
import tkinter as tk
from tkinter import filedialog, messagebox

def get_drives():
    drives = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            drives.append(drive)
    return drives

def scan_empty_folders(drive):
    empty_folders = []
    for root, dirs, files in os.walk(drive):
        if not dirs and not files:
            empty_folders.append(root)
    return empty_folders

def choose_drive_and_scan():
    drives = get_drives()
    if not drives:
        messagebox.showerror("Error", "No drives found.")
        return
    drive = filedialog.askdirectory(title="Select Drive", initialdir=drives[0])
    if not drive:
        return
    empty_folders = scan_empty_folders(drive)
    if empty_folders:
        result = "\n".join(empty_folders)
        messagebox.showinfo("Empty Folders Found", f"Empty folders:\n{result}")
    else:
        messagebox.showinfo("Result", "No empty folders found.")

if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    choose_drive_and_scan()