#!/usr/bin/env python3
import cv2
import numpy as np
import tkinter as tk
from tkinter import ttk, messagebox
import threading
from PIL import Image, ImageTk
from detector import ObjectDetector
from camera import CameraManager

class ObjectDetectionApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Computer Vision Object Detector")
        self.root.geometry("1200x800")
        
        self.camera_manager = CameraManager()
        self.detector = ObjectDetector()
        
        self.is_running = False
        self.current_frame = None
        self.detection_thread = None
        
        self.setup_ui()
        
    def setup_ui(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        control_frame = ttk.Frame(main_frame)
        control_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Button(control_frame, text="Start Detection", 
                  command=self.start_detection).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(control_frame, text="Stop Detection", 
                  command=self.stop_detection).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Label(control_frame, text="Model:").pack(side=tk.LEFT, padx=(20, 5))
        self.model_var = tk.StringVar(value="YOLO")
        model_combo = ttk.Combobox(control_frame, textvariable=self.model_var, 
                                  values=["YOLO", "ResNet50"], state="readonly", width=10)
        model_combo.pack(side=tk.LEFT)
        model_combo.bind("<<ComboboxSelected>>", self.change_model)
        
        self.video_frame = ttk.Label(main_frame, relief=tk.SUNKEN)
        self.video_frame.pack(fill=tk.BOTH, expand=True)
        
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN)
        status_bar.pack(fill=tk.X, pady=(10, 0))
        
    def start_detection(self):
        if not self.is_running:
            try:
                self.camera_manager.start()
                self.is_running = True
                self.status_var.set("Detection running...")
                self.detection_thread = threading.Thread(target=self.detection_loop, daemon=True)
                self.detection_thread.start()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to start camera: {e}")
                
    def stop_detection(self):
        self.is_running = False
        self.camera_manager.stop()
        self.status_var.set("Detection stopped")
        
    def change_model(self, event=None):
        model_name = self.model_var.get()
        self.detector.switch_model(model_name)
        self.status_var.set(f"Switched to {model_name}")
        
    def detection_loop(self):
        while self.is_running:
            frame = self.camera_manager.get_frame()
            if frame is not None:
                detections = self.detector.detect(frame)
                annotated_frame = self.detector.draw_detections(frame, detections)
                self.update_display(annotated_frame)
                
    def update_display(self, frame):
        if frame is not None:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_pil = Image.fromarray(frame_rgb)
            
            display_size = (800, 600)
            frame_pil = frame_pil.resize(display_size, Image.Resampling.LANCZOS)
            
            frame_tk = ImageTk.PhotoImage(frame_pil)
            
            self.video_frame.configure(image=frame_tk)
            self.video_frame.image = frame_tk
            
    def on_closing(self):
        self.stop_detection()
        self.root.destroy()

def main():
    root = tk.Tk()
    app = ObjectDetectionApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()