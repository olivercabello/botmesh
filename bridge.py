import asyncio
import logging
import json
import os
import meshtastic
import meshtastic.tcp_interface
import paho.mqtt.client as mqtt
from pubsub import pub
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# --- CARGA DE CONFIGURACIÓN SEGURA (Variables de Entorno) ---
# El script tomará estos valores del archivo de servicio (.service)

# 1. Interruptor Maestro MQTT
ENABLE_MQTT = os.getenv("ENABLE_MQTT", "False").lower() == "true"

# 2. Configuración de Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 3. Configuración del Nodo Meshtastic
MESHTASTIC_IP = os.getenv("MESHTASTIC_IP")
# Canal de respuesta (0=LongFast, 1=Canal Privado, etc.)
SEND_CHANNEL_INDEX = int(os.getenv("SEND_CHANNEL_INDEX", "1"))

# 4. Configuración del Broker MQTT (Solo si ENABLE_MQTT es True)
MQTT_BROKER = os.getenv("MQTT_BROKER")
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASS = os.getenv("MQTT_PASS")
MQTT_TOPIC_PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "mesh")

# --- LÓGICA DEL SISTEMA ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

interface = None
telegram_app = None
mqtt_client = None
main_loop = None

def limpiar_paquete(obj):
    """Convierte datos complejos de la radio en texto plano para JSON/MQTT."""
    if isinstance(obj, (str, int, float, bool, type(None))): return obj
    if isinstance(obj, bytes): return obj.hex()
    if isinstance(obj, dict): return {k: limpiar_paquete(v) for k, v in obj.items()}
    if isinstance(obj, list): return [limpiar_paquete(i) for i in obj]
    return str(obj)

def iniciar_mqtt():
    global mqtt_client
    if not ENABLE_MQTT: return
    try:
        mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
        mqtt_client.connect(MQTT_BROKER, 1883, 60)
        mqtt_client.loop_start()
        logging.info("✅ MQTT: Conectado correctamente al broker.")
    except Exception as e:
        logging.error(f"❌ MQTT Error: {e}")

def on_receive(packet, interface):
    """Recibe mensajes de la radio y los envía a Telegram/MQTT."""
    try:
        if not packet: return
        from_id = packet.get('fromId')
        to_id = str(packet.get('toId'))
        my_id = interface.getMyNodeInfo().get('user', {}).get('id')
        if from_id == my_id: return

        if ENABLE_MQTT and mqtt_client:
            try:
                p_limpio = limpiar_paquete(packet)
                mqtt_client.publish(f"{MQTT_TOPIC_PREFIX}/json/{from_id}", json.dumps(p_limpio))
            except: pass

        decoded = packet.get('decoded', {})
        if decoded.get('portnum') == 'TEXT_MESSAGE_APP':
            text = decoded.get('text', '')
            node_info = interface.nodes.get(from_id)
            sender = node_info.get('user', {}).get('longName', from_id) if node_info else from_id
            
            chan_idx = packet.get("channel", 0)
            chan_name = "LongFast" if chan_idx == 0 else f"Canal {chan_idx}"
            try:
                if interface.localNode and interface.localNode.channels:
                    for c in interface.localNode.channels:
                        if c.index == chan_idx and c.settings.name:
                            chan_name = c.settings.name
                            break
            except: pass

            if to_id in ["!ffffffff", "4294967295", "^all"]:
                msg = f"📡 [{sender}] channel [{chan_name}]: {text}"
            else:
                msg = f"📡 [{sender}] DM [Mi Base]: {text}"

            if telegram_app and main_loop:
                asyncio.run_coroutine_threadsafe(
                    telegram_app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg), main_loop
                )
    except Exception as e:
        logging.error(f"❌ Error en on_receive: {e}")

async def handle_telegram_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibe mensajes de Telegram y los envía al canal de la radio configurado."""
    if not update.message or not update.message.text: return
    if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID) or update.message.text.startswith('/'): return
    
    user = update.message.from_user.first_name if update.message.from_user else "Anónimo"
    txt = f"{user}: {update.message.text}"
    
    if interface:
        try:
            interface.sendText(txt, channelIndex=SEND_CHANNEL_INDEX)
            logging.info(f"📤 Telegram -> Radio (Canal {SEND_CHANNEL_INDEX}): {txt}")
        except Exception as e:
            logging.error(f"❌ Error envío radio: {e}")

async def main():
    global interface, telegram_app, main_loop
    main_loop = asyncio.get_running_loop()
    iniciar_mqtt()
    telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_telegram_message))
    pub.subscribe(on_receive, "meshtastic.receive")
    
    try:
        logging.info(f"Conectando al nodo IP {MESHTASTIC_IP}...")
        interface = meshtastic.tcp_interface.TCPInterface(hostname=MESHTASTIC_IP)
        await asyncio.sleep(6)
    except Exception as e:
        logging.error(f"❌ Error conexión IP: {e}"); return

    await telegram_app.initialize(); await telegram_app.start(); await telegram_app.updater.start_polling()
    logging.info(f"🚀 BRIDGE v4.5 OPERATIVO (Canal de envío: {SEND_CHANNEL_INDEX})")
    while True: await asyncio.sleep(1)

if __name__ == '__main__':
    try: asyncio.run(main())
    except KeyboardInterrupt:
        if interface: interface.close()