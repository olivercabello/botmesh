# -*- coding: utf-8 -*-
import logging
import signal
import sys
import threading
import time

# Importaciones de Meshtastic
import meshtastic
from meshtastic.mqtt_interface import MQTTInterface
from pubsub import pub

# Importaciones de Telegram
import telebot

# --- CONFIGURACIÓN TELEGRAM ---
TELEGRAM_TOKEN = "8442696388:AAGLWuntercwO5pRtOchlSFyh2BTb_Zeekc"
TELEGRAM_CHAT_ID = "-5222903422"

# --- CONFIGURACIÓN HIVEMQ CLOUD ---
MQTT_SERVER = "e5b95815f4f841b29bb099992f8527cf.s1.eu.hivemq.cloud" 
MQTT_USER = "ocabgon"
MQTT_PASS = "Twist1977@"

# --- CONFIGURACIÓN DE RED MESH ---
MESH_CHANNEL = "GrupoChicha" 

# Configuración de Logs profesional
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("mesh_bridge.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Inicializar Bot de Telegram
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Variable global para la interfaz
interface = None
running = True

def signal_handler(sig, frame):
    """Maneja la interrupción del sistema para un cierre limpio."""
    global running, interface
    logger.info("Señal de parada recibida. Cerrando conexiones...")
    running = False
    if interface:
        interface.close()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def connect_meshtastic_mqtt():
    """Establece la conexión con HiveMQ Cloud."""
    global interface
    while running:
        try:
            logger.info(f"Intentando conectar a HiveMQ Cloud en {MQTT_SERVER}...")
            # Usamos la clase MQTTInterface directamente
            new_interface = MQTTInterface(
                hostname=MQTT_SERVER,
                username=MQTT_USER,
                password=MQTT_PASS,
                use_Ssl=True
            )
            logger.info("✅ Conexión establecida con éxito.")
            return new_interface
        except Exception as e:
            logger.error(f"❌ Error de conexión: {e}. Reintentando en 15 segundos...")
            time.sleep(15)
    return None

def on_meshtastic_receive(packet, interface):
    """Procesa los paquetes que llegan desde la red LoRa/MQTT."""
    try:
        if 'decoded' in packet and packet['decoded']['portnum'] == 'TEXT_MESSAGE_APP':
            msg_text = packet['decoded']['text']
            sender_id = packet.get('fromId', 'Desconocido')
            
            node_info = interface.nodes.get(sender_id)
            sender_name = node_info['user']['longName'] if node_info and 'user' in node_info else sender_id
            
            # Evitar bucles
            if msg_text.startswith("TG:"):
                return

            logger.info(f"Mensaje de {sender_name}: {msg_text}")
            
            formatted_msg = (
                f"📡 *Mensaje desde la Red Mesh*\n"
                f"👤 *Usuario:* `{sender_name}`\n"
                f"💬 *Msg:* {msg_text}"
            )
            bot.send_message(TELEGRAM_CHAT_ID, formatted_msg, parse_mode="Markdown")
            
    except Exception as e:
        logger.error(f"Error procesando paquete entrante: {e}")

# Suscribir al evento
pub.subscribe(on_meshtastic_receive, "meshtastic.receive")

@bot.message_handler(func=lambda message: True)
def on_telegram_receive(message):
    """Maneja los mensajes de Telegram."""
    global interface
    
    if str(message.chat.id) != str(TELEGRAM_CHAT_ID):
        return

    msg_text = message.text
    logger.info(f"Enviando a Mesh: {msg_text}")
    
    try:
        if interface:
            interface.sendText(f"TG: {msg_text}")
            bot.reply_to(message, "✅ Enviado a la red LoRa.")
        else:
            bot.reply_to(message, "❌ Sin conexión al nodo.")
    except Exception as e:
        logger.error(f"Error al enviar: {e}")

if __name__ == "__main__":
    logger.info("=== INICIANDO BRIDGE TELEGRAM-MESHTASTIC ===")
    
    interface = connect_meshtastic_mqtt()
    
    # Iniciar Telegram
    telegram_thread = threading.Thread(target=lambda: bot.infinity_polling(), daemon=True)
    telegram_thread.start()

    # Mantener vivo el programa
    while running:
        if not interface or getattr(interface, 'is_closed', False):
            interface = connect_meshtastic_mqtt()
        time.sleep(10)