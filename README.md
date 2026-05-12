📡 Meshtastic to Telegram Bridge (IP Mode)
Este script crea un puente bidireccional entre tu red Meshtastic y un grupo de Telegram.

Escucha: El bot envía a Telegram los mensajes de todos los canales de tu radio.

Responde: Los mensajes escritos en Telegram se envían al canal de radio que tú elijas.

🛠️ Requisitos Previos
Un nodo Meshtastic (Heltec, T-Beam, Xiao S3) conectado a tu WiFi.

Un Bot de Telegram: Créalo hablando con @BotFather.

ID de Chat: Consigue el ID de tu grupo o chat privado usando @myidbot.

📥 Instalación Paso a Paso
1. Preparar el sistema
Abre la terminal de tu servidor (LXC, Ubuntu, Debian) y ejecuta:

Bash
sudo apt update && sudo apt install python3 python3-pip python3-venv git -y
2. Descargar y configurar el entorno
Bash
mkdir -p /opt/meshbridge
cd /opt/meshbridge
# Clona el repositorio
git clone https://github.com/TU_USUARIO/TU_REPOSITORIO.git .

# Crear el entorno virtual e instalar librerías
python3 -m venv venv
source venv/bin/activate
pip install meshtastic paho-mqtt python-telegram-bot PyPubSub
3. Configuración Segura (Archivo de Servicio)
Para no escribir tus contraseñas en el código, las inyectaremos mediante un servicio de sistema. Esto hace que el bot se inicie solo al arrancar el servidor.

Crea el archivo de servicio:

Bash
sudo nano /etc/systemd/system/meshtastic-bridge.service
Copia y pega este contenido, sustituyendo los valores de ejemplo por los tuyos reales:

Ini, TOML
[Unit]
Description=Meshtastic Telegram Bridge
After=network.target

[Service]
ExecStart=/opt/meshbridge/venv/bin/python3 /opt/meshbridge/bridge.py
WorkingDirectory=/opt/meshbridge
Restart=always
RestartSec=10

# --- CONFIGURACIÓN DE TUS DATOS (EDITA AQUÍ) ---
Environment="TELEGRAM_TOKEN=tu_token_aqui"
Environment="TELEGRAM_CHAT_ID=-100xxxxxxxx"
Environment="MESHTASTIC_IP=192.168.0.42"

# Canal de envío (0=LongFast, 1=Canal 1, etc.)
Environment="SEND_CHANNEL_INDEX=1"

# Configuración MQTT (Solo si vas a usar Home Assistant)
Environment="ENABLE_MQTT=False"
Environment="MQTT_BROKER=192.168.0.151"
Environment="MQTT_USER=tu_usuario"
Environment="MQTT_PASS=tu_password"
Environment="MQTT_TOPIC_PREFIX=mesh"
# -----------------------------------------------

User=root

[Install]
WantedBy=multi-user.target
4. Arrancar el Bridge
Bash
sudo systemctl daemon-reload
sudo systemctl enable meshtastic-bridge
sudo systemctl start meshtastic-bridge
5. Monitorización
Para ver si el bot está trabajando o diagnosticar errores, usa:

Bash
journalctl -u meshtastic-bridge -f
