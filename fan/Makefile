# Makefile para Fan Control System
CXX = g++
CXXFLAGS = -std=c++11 -Wall -Wextra -O2
LIBS = -lwiringPi -lpthread
TARGET = fan_daemon
SOURCE = fan_daemon.cpp

# Directorios
INSTALL_DIR = /home/pi/fan_control
SERVICE_DIR = /etc/systemd/system

.PHONY: all build install clean uninstall setup-display

all: build

build:
	@echo "Compilando daemon de control de ventiladores..."
	$(CXX) $(CXXFLAGS) $(SOURCE) -o $(TARGET) $(LIBS)
	@echo "Compilación completada."

install: build
	@echo "Instalando sistema de control de ventiladores..."
	sudo mkdir -p $(INSTALL_DIR)
	sudo cp $(TARGET) $(INSTALL_DIR)/
	sudo cp simple_monitor.py $(INSTALL_DIR)/
	sudo chmod +x $(INSTALL_DIR)/$(TARGET)
	sudo chmod +x $(INSTALL_DIR)/simple_monitor.py
	sudo cp fan-control.service $(SERVICE_DIR)/
	sudo systemctl daemon-reload
	@echo "Instalación completada."
	@echo "Para iniciar el servicio: sudo systemctl enable fan-control && sudo systemctl start fan-control"

setup-display:
	@echo "Configurando pantalla touch 3.5 pulgadas..."
	@echo "Instalando drivers de pantalla..."
	sudo apt-get update
	sudo apt-get install -y xserver-xorg-input-evdev xinput-calibrator
	@echo "Configurando LCD35 driver..."
	cd /tmp && git clone https://github.com/goodtft/LCD-show.git
	cd /tmp/LCD-show && sudo ./LCD35-show
	@echo "NOTA: El sistema se reiniciará automáticamente después de configurar la pantalla"

clean:
	rm -f $(TARGET)

uninstall:
	@echo "Desinstalando sistema de control..."
	sudo systemctl stop fan-control 2>/dev/null || true
	sudo systemctl disable fan-control 2>/dev/null || true
	sudo rm -f $(SERVICE_DIR)/fan-control.service
	sudo rm -rf $(INSTALL_DIR)
	sudo systemctl daemon-reload
	@echo "Desinstalación completada."

# Reglas para desarrollo
debug: CXXFLAGS += -g -DDEBUG
debug: build

test: build
	@echo "Ejecutando daemon en modo test..."
	./$(TARGET)

# Información del sistema
info:
	@echo "=== Información del Sistema ==="
	@echo "Temperatura CPU: $$(cat /sys/class/thermal/thermal_zone0/temp | awk '{print $$1/1000}')°C"
	@echo "Estado GPIO:"
	@gpio readall 2>/dev/null || echo "gpio command no encontrado (instalar wiringPi)"
	@echo "Servicios activos:"
	@systemctl is-active fan-control 2>/dev/null || echo "fan-control: inactivo"

# Configuración inicial completa
setup: setup-dependencies build install
	@echo "=== Configuración inicial completada ==="
	@echo "1. Conecta los ventiladores a los pines especificados"
	@echo "2. Ejecuta 'make setup-display' para configurar la pantalla"
	@echo "3. Inicia el servicio: sudo systemctl enable fan-control && sudo systemctl start fan-control"
	@echo "4. Monitor opcional: python3 $(INSTALL_DIR)/simple_monitor.py"

setup-dependencies:
	@echo "Instalando dependencias del sistema..."
	sudo apt-get update
	sudo apt-get install -y build-essential git python3 python3-pip python3-tk
	
	@echo "Instalando wiringPi (biblioteca GPIO para C++)..."
	cd /tmp && rm -rf WiringPi
	cd /tmp && git clone https://github.com/WiringPi/WiringPi.git
	cd /tmp/WiringPi && ./build
	
	@echo "Verificando instalación de wiringPi..."
	@gpio -v || echo "Error: wiringPi no se instaló correctamente"
	
	@echo "Instalando bibliotecas Python para GUI..."
	pip3 install --user tk
	
	@echo "✅ Todas las dependencias instaladas correctamente."