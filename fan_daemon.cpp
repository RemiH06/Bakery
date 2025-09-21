#include <iostream>
#include <fstream>
#include <unistd.h>
#include <signal.h>
#include <sys/stat.h>
#include <wiringPi.h>
#include <softPwm.h>
#include <cstring>

// Configuración de pines - Adyacentes en esquina
#define FAN_PWM_PIN 26  // GPIO 26 (Pin físico 37) - Cable ROJO
                        // Pin 39 (GND) - Cable NEGRO
#define TEMP_PATH "/sys/class/thermal/thermal_zone0/temp"
#define CONTROL_PIPE "/tmp/fan_control"
#define STATUS_FILE "/tmp/fan_status"

class FanController {
private:
    int fanSpeed = 0;
    float currentTemp = 0.0;
    bool autoMode = true;
    bool running = true;
    
public:
    FanController() {
        // Inicializar wiringPi
        if (wiringPiSetupGpio() == -1) {
            std::cerr << "Error: No se pudo inicializar wiringPi" << std::endl;
            exit(1);
        }
        
        // Configurar PWM software para ventiladores (ambos unidos)
        softPwmCreate(FAN_PWM_PIN, 0, 100);
        
        // Crear pipe para control
        mkfifo(CONTROL_PIPE, 0666);
        
        std::cout << "Fan Controller iniciado - Ventiladores unidos en GPIO " << FAN_PWM_PIN << " (Pin 37/39)" << std::endl;
    }
    
    ~FanController() {
        softPwmWrite(FAN_PWM_PIN, 0);
        unlink(CONTROL_PIPE);
        unlink(STATUS_FILE);
    }
    
    float readTemperature() {
        std::ifstream tempFile(TEMP_PATH);
        if (!tempFile.is_open()) {
            std::cerr << "Error leyendo temperatura" << std::endl;
            return 0.0;
        }
        
        int temp_millidegrees;
        tempFile >> temp_millidegrees;
        tempFile.close();
        
        return temp_millidegrees / 1000.0;
    }
    
    void updateFanSpeeds() {
        if (!autoMode) return;
        
        int targetSpeed = 0;
        
        // Control automático basado ÚNICAMENTE en temperatura del RPi
        if (currentTemp > 80.0) {
            targetSpeed = 100;  // Emergencia - máxima velocidad
        } else if (currentTemp > 70.0) {
            targetSpeed = 85;   // Muy caliente - alta velocidad
        } else if (currentTemp > 60.0) {
            targetSpeed = 70;   // Caliente - velocidad alta-media
        } else if (currentTemp > 50.0) {
            targetSpeed = 50;   // Tibio - velocidad media
        } else if (currentTemp > 40.0) {
            targetSpeed = 30;   // Normal - baja velocidad
        } else {
            targetSpeed = 0;    // Frío - ventiladores apagados
        }
        
        // Aplicar velocidad a ambos ventiladores (están unidos)
        setFanSpeed(targetSpeed);
        
        // Log para debugging (opcional)
        if (targetSpeed != fanSpeed) {
            std::cout << "Temp: " << currentTemp << "°C -> Fan Speed: " << targetSpeed << "%" << std::endl;
        }
    }
    
    void setFanSpeed(int speed) {
        speed = std::max(0, std::min(100, speed)); // Limitar entre 0-100
        fanSpeed = speed;
        softPwmWrite(FAN_PWM_PIN, speed);
    }
    
    void writeStatus() {
        std::ofstream statusFile(STATUS_FILE);
        if (statusFile.is_open()) {
            statusFile << "temp:" << currentTemp << "\n";
            statusFile << "fans:" << fanSpeed << "\n";
            statusFile << "auto:" << (autoMode ? "1" : "0") << "\n";
            statusFile.close();
        }
    }
    
    void processCommands() {
        std::ifstream pipe(CONTROL_PIPE);
        if (!pipe.is_open()) return;
        
        std::string command;
        while (std::getline(pipe, command)) {
            if (command.substr(0, 4) == "fan:") {
                int speed = std::stoi(command.substr(4));
                setFanSpeed(speed);
                autoMode = false;
            }
            else if (command == "auto") {
                autoMode = true;
            }
            else if (command == "stop") {
                running = false;
                break;
            }
        }
        pipe.close();
    }
    
    void run() {
        while (running) {
            // Leer temperatura
            currentTemp = readTemperature();
            
            // Procesar comandos
            processCommands();
            
            // Actualizar velocidades si está en modo automático
            updateFanSpeeds();
            
            // Escribir estado
            writeStatus();
            
            // Esperar 1 segundo
            sleep(1);
        }
    }
};

// Manejador de señales para cierre limpio
FanController* globalController = nullptr;

void signalHandler(int signal) {
    if (globalController) {
        std::cout << "\nCerrando Fan Controller..." << std::endl;
        delete globalController;
        exit(0);
    }
}

int main() {
    // Configurar manejador de señales
    signal(SIGINT, signalHandler);
    signal(SIGTERM, signalHandler);
    
    // Crear y ejecutar controlador
    globalController = new FanController();
    globalController->run();
    
    delete globalController;
    return 0;
}