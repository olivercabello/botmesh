## 📡 Meshtastic to Telegram Bridge (IP Mode)
Este script crea un puente bidireccional entre tu red Meshtastic y un grupo de Telegram.

- Escucha: El bot envía a Telegram los mensajes de todos los canales de tu radio.
- Responde: Los mensajes escritos en Telegram se envían al canal de radio que tú elijas.

## 🛠️ Requisitos Previos
- Un nodo Meshtastic (Heltec, T-Beam, Xiao S3) conectado a tu WiFi.
- Un Bot de Telegram: Créalo hablando con @BotFather.
- ID de Chat: Consigue el ID de tu grupo o chat privado usando @myidbot.

## 📥 Instalación Paso a Paso
1. Preparar el sistema:
- Abre la terminal de tu servidor (LXC, Ubuntu, Debian) y ejecuta:

```bash
sudo apt update && sudo apt install python3 python3-pip python3-venv git -y
```

2. Descargar y configurar el entorno

```bash
mkdir -p /opt/meshbridge
cd /opt/meshbridge
# Clona el repositorio
git clone https://github.com/olivercabello/botmesh.git .

# Crear el entorno virtual e instalar librerías
python3 -m venv venv
source venv/bin/activate
pip install meshtastic paho-mqtt python-telegram-bot PyPubSub
```

3. Configuración Segura (Archivo de Servicio)
- Para no escribir tus contraseñas en el código, las inyectaremos mediante un servicio de sistema. Esto hace que el bot se inicie solo al arrancar el servidor.

- Crea el archivo de servicio:

```bash
sudo nano /etc/systemd/system/meshtastic-bridge.service
```
- Copia y pega este contenido, sustituyendo los valores de ejemplo por los tuyos reales:

```bash
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
```

4. Arrancar el Bridge
```bash
sudo systemctl daemon-reload
sudo systemctl enable meshtastic-bridge
sudo systemctl start meshtastic-bridge
```

5. Monitorización
- Para ver si el bot está trabajando o diagnosticar errores, usa:

```bash
journalctl -u meshtastic-bridge -f
```
## 🗒️ Notas: 
- Si necesitas reiniciar el nodo, se recomienda reiniciar el servicio. 
- Posteriormente confirma que conecta correctamente monitorizando el bot según paso 5
- El bot recibe todos los mensajes que de los canales que tenga configurados incluídos los DM. En cada mensaje que reciba el bot los identifica el bot mediante canal o DM en su caso con la descripción del nodo
- El nodo siempre devuelve mensaje por un único canal que deberás configurar la variable SEND_CHANNEL_INDEX, recuerda que 0 es siempre el canal primario o Longfast
- Si quieres que se envíe mensajería a Home Assistant configura la información del broker con la IP, usuario y contraseña de HA
- Si quieres que el bot envíe la mensajes a la meshtastic mediante MQTT configura adecuadmente tu nodo según las indicaciones del grupo Meshtastic España
