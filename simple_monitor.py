#!/usr/bin/env python3
"""
Monitor Simple de Temperatura y Ventiladores
Para usar ocasionalmente en la pantalla touch
"""

import tkinter as tk
from tkinter import ttk
import threading
import time
import os

class TemperatureMonitor:
    def __init__(self, root):
        self.root = root
        self.root.title("Monitor del Sistema")
        self.root.geometry("480x320")  # Pantalla 3.5"
        self.root.configure(bg='#1a1a1a')
        
        # Variables
        self.temp_var = tk.StringVar(value="--°C")
        self.fan_speed_var = tk.StringVar(value="--%")
        self.status_var = tk.StringVar(value="Daemon: Desconocido")
        
        self.create_widgets()
        self.start_monitoring()
        
    def create_widgets(self):
        # Frame principal
        main_frame = tk.Frame(self.root, bg='#1a1a1a', padx=30, pady=30)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Título
        title = tk.Label(main_frame, text="🌡️ Monitor RPi", 
                        font=('Arial', 24, 'bold'), fg='#00ff41', bg='#1a1a1a')
        title.pack(pady=(0, 30))
        
        # Temperatura - Display grande
        temp_frame = tk.Frame(main_frame, bg='#2d2d2d', relief=tk.RAISED, bd=3)
        temp_frame.pack(fill=tk.X, pady=(0, 20))
        
        temp_label = tk.Label(temp_frame, text="Temperatura CPU", 
                             font=('Arial', 14), fg='#ffffff', bg='#2d2d2d')
        temp_label.pack(pady=(15, 5))
        
        temp_display = tk.Label(temp_frame, textvariable=self.temp_var,
                               font=('Arial', 36, 'bold'), fg='#ff4444', bg='#2d2d2d')
        temp_display.pack(pady=(0, 15))
        
        # Estado de ventiladores
        fan_frame = tk.Frame(main_frame, bg='#2d2d2d', relief=tk.RAISED, bd=3)
        fan_frame.pack(fill=tk.X, pady=(0, 20))
        
        fan_label = tk.Label(fan_frame, text="💨 Velocidad Ventiladores", 
                            font=('Arial', 14), fg='#ffffff', bg='#2d2d2d')
        fan_label.pack(pady=(15, 5))
        
        fan_display = tk.Label(fan_frame, textvariable=self.fan_speed_var,
                              font=('Arial', 24, 'bold'), fg='#44aaff', bg='#2d2d2d')
        fan_display.pack(pady=(0, 15))
        
        # Estado del sistema
        status_label = tk.Label(main_frame, textvariable=self.status_var,
                               font=('Arial', 12), fg='#888888', bg='#1a1a1a')
        status_label.pack(pady=(10, 0))
        
        # Botón cerrar
        close_btn = tk.Button(main_frame, text="✖ Cerrar", 
                             command=self.root.destroy, bg='#ff4444', fg='white',
                             font=('Arial', 12, 'bold'), relief=tk.FLAT, 
                             padx=20, pady=5)
        close_btn.pack(pady=(20, 0))
    
    def read_temperature(self):
        """Leer temperatura directamente del sistema"""
        try:
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                temp_millidegrees = int(f.read().strip())
                return temp_millidegrees / 1000.0
        except:
            return 0.0
    
    def read_daemon_status(self):
        """Leer estado del daemon si existe"""
        try:
            if os.path.exists('/tmp/fan_status'):
                with open('/tmp/fan_status', 'r') as f:
                    lines = f.readlines()
                    
                status = {}
                for line in lines:
                    if ':' in line:
                        key, value = line.strip().split(':', 1)
                        status[key] = value
                
                return status
        except:
            pass
        return None
    
    def update_display(self):
        """Actualizar información en pantalla"""
        # Temperatura siempre disponible
        temp = self.read_temperature()
        self.temp_var.set(f"{temp:.1f}°C")
        
        # Cambiar color según temperatura
        temp_widget = None
        for widget in self.root.winfo_children():
            if isinstance(widget, tk.Frame):
                for child in widget.winfo_children():
                    if isinstance(child, tk.Frame):
                        for grandchild in child.winfo_children():
                            if isinstance(grandchild, tk.Label) and grandchild.cget('font')[1] == 36:
                                temp_widget = grandchild
                                break
        
        if temp_widget:
            if temp > 70:
                temp_widget.config(fg='#ff0000')  # Rojo - caliente
            elif temp > 60:
                temp_widget.config(fg='#ff8800')  # Naranja - tibio
            elif temp > 50:
                temp_widget.config(fg='#ffff00')  # Amarillo - normal
            else:
                temp_widget.config(fg='#00ff00')  # Verde - frío
        
        # Estado del daemon
        daemon_status = self.read_daemon_status()
        if daemon_status:
            fan_speed = daemon_status.get('fans', '0')
            self.fan_speed_var.set(f"{fan_speed}%")
            self.status_var.set("✅ Daemon: Activo")
        else:
            self.fan_speed_var.set("--")
            self.status_var.set("⚠️ Daemon: Inactivo")
    
    def monitor_loop(self):
        """Hilo de monitoreo"""
        while True:
            try:
                self.update_display()
            except:
                pass
            time.sleep(2)  # Actualizar cada 2 segundos
    
    def start_monitoring(self):
        """Iniciar monitoreo en hilo separado"""
        monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
        monitor_thread.start()

def main():
    root = tk.Tk()
    app = TemperatureMonitor(root)
    
    # Hacer la ventana siempre visible
    root.attributes('-topmost', False)
    root.mainloop()

if __name__ == "__main__":
    main()