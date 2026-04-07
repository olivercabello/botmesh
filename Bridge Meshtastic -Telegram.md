Entendido. Vamos a crear el **Manual de Instalación Definitivo**, estructurado de principio a fin. Esta es tu bitácora maestra: si mañana tu servidor explota y tienes que montarlo todo en un equipo nuevo, solo tendrás que seguir esta guía copiando y pegando.

Guarda este texto a buen recaudo.

---

# 📖 Manual Maestre: Bridge Meshtastic ↔ Telegram (Red Canarias)

## FASE 1: Configuración del Hardware (Nodo Físico)
Antes de tocar el servidor, el nodo conectado por USB debe tener esta configuración en la app de Meshtastic o WebUI:

1.  **Rol del Dispositivo:** `CLIENT_MUTE` (Evita que repita paquetes por RF, dejando ese trabajo a tu nodo de la azotea).
2.  **Canal 0 (Primario):** Configurado con el nombre `Canarias` y su PSK correspondiente. Debe tener activado **Uplink** y **Downlink**.
3.  **Módulo MQTT:** Activado, apuntando a `mqtt.meshtastic.es` con *Proxy to Client* habilitado.
4.  **Privacidad:** En la configuración de Usuario, activar **"Ignore Direct Messages"** para que nadie intente enviarle DMs por radio.

---

## FASE 2: Preparación del Servidor (LXC en Proxmox)
Conecta el nodo por USB al servidor Proxmox, mapea el puerto al contenedor LXC y abre la consola del LXC.

**1. Actualizar e instalar dependencias base:**
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-venv python3-pip nano -y
```

**2. Crear la estructura de carpetas y el Entorno Virtual:**
```bash
mkdir -p /opt/meshtastic_bridge
cd /opt/meshtastic_bridge
python3 -m venv meshtastic_env
```

**3. Activar el entorno e instalar las librerías necesarias:**
```bash
source meshtastic_env/bin/activate
pip install meshtastic python-telegram-bot pypubsub httpx
```

---

## FASE 3: El Código Fuente (Script Principal)
Dentro de la carpeta `/opt/meshtastic_bridge`, crea el archivo principal:
```bash
nano bridge_meshtastic_telegram.py
```
Pega el siguiente código íntegro. **No olvides poner tu Token de Telegram y el ID de tu Chat en las primeras líneas.**

```python
import asyncio
import logging
import httpx
import meshtastic
import meshtastic.serial_interface
from pubsub import pub
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
import unicodedata
import xml.etree.ElementTree as ET

# --- CONFIGURACIÓN ---
TELEGRAM_TOKEN = "8632334351:AAF1BBf1kDkiDDNRQheahtmXZEYkfYBighI"
TELEGRAM_CHAT_ID = "-1003700510725"         
MESHTASTIC_CONNECTION_TYPE = "serial"                        
MESHTASTIC_IP = "192.168.0.134"                         
MESHTASTIC_PORT = "/dev/ttyUSB0"                     
MESHTASTIC_CHANNEL_INDEX = 0                        

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

interface = None
telegram_app = None
main_loop = None
ultimo_estado_alerta_roja = False  

# Cola de mensajes para Telegram -> Malla
cola_tx_malla = asyncio.Queue()

# --- TAREAS EN SEGUNDO PLANO ---

async def trabajador_cola_tx():
    """Extrae mensajes de la sala de espera y los envía al nodo con pausas de 5 segundos."""
    while True:
        mensaje = await cola_tx_malla.get()
        if interface:
            try:
                logging.info(f"✅ Enviando a Meshtastic -> {mensaje}")
                interface.sendText(mensaje, channelIndex=MESHTASTIC_CHANNEL_INDEX)
            except Exception as e:
                logging.error(f"Error crítico al inyectar por USB: {e}")
        
        await asyncio.sleep(5)
        cola_tx_malla.task_done()

async def get_tiempo():
    """Consulta Open-Meteo para el clima de las dos provincias canarias."""
    url_tf = "https://api.open-meteo.com/v1/forecast?latitude=28.4682&longitude=-16.2546&current=temperature_2m,wind_speed_10m"
    url_gc = "https://api.open-meteo.com/v1/forecast?latitude=28.1248&longitude=-15.4300&current=temperature_2m,wind_speed_10m"
    try:
        async with httpx.AsyncClient() as client:
            resp_tf = await client.get(url_tf, timeout=5.0)
            resp_gc = await client.get(url_gc, timeout=5.0)
            tf = resp_tf.json()['current']
            gc = resp_gc.json()['current']
            return f"⛅ Canarias -> TF: {tf['temperature_2m']}°C ({tf['wind_speed_10m']}km/h) | GC: {gc['temperature_2m']}°C ({gc['wind_speed_10m']}km/h)"
    except Exception as e:
        logging.error(f"Error clima: {e}")
        return "⚠️ Error al consultar el clima de Canarias."

async def get_mar():
    """Consulta Open-Meteo Marine."""
    url = "https://marine-api.open-meteo.com/v1/marine?latitude=28.29&longitude=-16.0&current=wave_height"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=5.0)
            data = resp.json()
            olas = data['current']['wave_height']
            return f"🌊 Mar Canarias: Oleaje actual medio de {olas}m."
    except Exception as e:
        logging.error(f"Error mar: {e}")
        return "⚠️ Error al consultar el estado del mar."

async def get_alerta():
    """Consulta el Atom XML de AEMET usando la URL directa proporcionada."""
    url_atom = "https://www.aemet.es/documentos_d/eltiempo/prediccion/avisos/rss/CAP_AFAC65_ATOM.xml"
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url_atom, timeout=8.0)
            if resp.status_code != 200:
                return f"⚠️ Error AEMET: Status {resp.status_code}"
            
            root = ET.fromstring(resp.content)
            entries = root.findall('atom:entry', ns)

            if not entries:
                return "🟢 AEMET: Sin alertas activas en Canarias."

            max_nivel = 0 
            fenomenos = set()

            for entry in entries:
                titulo = entry.find('atom:title', ns).text.lower()
                
                if "rojo" in titulo: max_nivel = max(max_nivel, 3)
                elif "naranja" in titulo: max_nivel = max(max_nivel, 2)
                elif "amarillo" in titulo: max_nivel = max(max_nivel, 1)

                if "viento" in titulo: fenomenos.add("Viento")
                if "costeros" in titulo or "oleaje" in titulo: fenomenos.add("Mar")
                if "lluvia" in titulo or "precipitaci" in titulo: fenomenos.add("Lluvias")
                if "polvo" in titulo or "calima" in titulo: fenomenos.add("Calima")
                if "temperatura" in titulo or "calor" in titulo: fenomenos.add("Calor")
                if "tormenta" in titulo: fenomenos.add("Tormentas")

            colores = {3: "ROJO 🔴", 2: "NARANJA 🟠", 1: "AMARILLO 🟡", 0: "VERDE 🟢"}
            nivel_str = colores.get(max_nivel, "INFO")
            fen_str = ", ".join(fenomenos) if fenomenos else "Varios"

            return f"⚠️ AEMET {nivel_str}: {fen_str}. Info: https://www.aemet.es/es/eltiempo/prediccion/avisos?k=can"

    except Exception as e:
        logging.error(f"Error AEMET Atom: {e}")
        return "⚠️ AEMET no disponible temporalmente."

async def procesar_comando_malla(comando):
    """Ejecuta la consulta web de forma asíncrona y la envía a la malla."""
    respuesta = ""
    if comando == "tiempo":
        respuesta = await get_tiempo()
    elif comando == "mar":
        respuesta = await get_mar()
    elif comando == "alerta":
        respuesta = await get_alerta()
    elif comando == "canalic":
        respuesta = "🇮🇨 Canal Canarias: https://meshtastic.org/e/?add=true#ChESAQEaCENhbmFyaWFzKAEwARIMCAFAA0gBwAYAyAYB"
    elif comando == "canaltg":
        respuesta = "📲 Telegram: https://t.me/meshtastic_canarias"
    elif comando == "info":
        respuesta = "🤖 Bridge Radio-Internet. Mensajes de Telegram van a la radio y viceversa. Comandos (!tiempo, !alerta) consultan webs en tiempo real para usuarios sin internet."

    if respuesta:
        await cola_tx_malla.put(respuesta)

# --- TAREA DE MONITORIZACIÓN AUTOMÁTICA ---

async def monitor_aemet():
    """Revisa el XML cada 30 min para avisar de alertas rojas."""
    global ultimo_estado_alerta_roja
    url_atom = "https://www.aemet.es/documentos_d/eltiempo/prediccion/avisos/rss/CAP_AFAC65_ATOM.xml"
    
    while True:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url_atom, timeout=10.0)
                if resp.status_code == 200:
                    texto_raw = resp.text.lower()
                    hay_alerta_roja = "nivel rojo" in texto_raw or "aviso rojo" in texto_raw
                    
                    if hay_alerta_roja and not ultimo_estado_alerta_roja:
                        mensaje = (
                            "🚨 **ALERTA ROJA AEMET DETECTADA** 🚨\n"
                            "Se han publicado avisos de **Nivel Rojo**.\n\n"
                            "🔗 [Ver detalles en AEMET](https://www.aemet.es/es/eltiempo/prediccion/avisos?k=can)"
                        )
                        if telegram_app:
                            await telegram_app.bot.send_message(
                                chat_id=TELEGRAM_CHAT_ID, 
                                text=mensaje, 
                                parse_mode='Markdown', 
                                disable_web_page_preview=True
                            )
                        ultimo_estado_alerta_roja = True
                    elif not hay_alerta_roja:
                        ultimo_estado_alerta_roja = False
                else:
                    logging.error(f"Monitor AEMET falló: Status {resp.status_code}")
                    
        except Exception as e:
            logging.error(f"Error en monitor automático AEMET: {e}")
        
        await asyncio.sleep(1800)

# --- CALLBACK DE RECEPCIÓN DE RADIO ---

def on_receive(packet, interface):
    try:
        if 'decoded' in packet and packet['decoded'].get('portnum') == 'TEXT_MESSAGE_APP':
            text = packet['decoded'].get('text', '')
            sender_id = packet.get('fromId')
            to_id = packet.get('toId')
            packet_channel = packet.get('channel', 0)
            my_node_id = interface.getMyNodeInfo()['user']['id']

            if sender_id == my_node_id: return

            node_info = interface.nodes.get(sender_id)
            long_name = sender_id
            if node_info and 'user' in node_info and 'longName' in node_info['user']:
                long_name = node_info['user']['longName']

            is_broadcast = (to_id == '^all' or to_id == 4294967295 or str(to_id).lower() == '!ffffffff')
            
            if is_broadcast and packet_channel == MESHTASTIC_CHANNEL_INDEX:
                texto_limpio = text.strip().lower()
                
                if texto_limpio == '!ping':
                    if main_loop: asyncio.run_coroutine_threadsafe(cola_tx_malla.put("🏓 Pong. Bridge Operativo."), main_loop)
                elif texto_limpio == '!nodos':
                    total_nodos = len(interface.nodes) - 1 if interface.nodes else 0
                    if main_loop: asyncio.run_coroutine_threadsafe(cola_tx_malla.put(f"📡 Antena local viendo {total_nodos} nodos."), main_loop)
                elif texto_limpio == '!help':
                    if main_loop: asyncio.run_coroutine_threadsafe(cola_tx_malla.put("Comandos: !info, !ping, !nodos, !tiempo, !mar, !alerta, !canalic, !canaltg"), main_loop)
                elif texto_limpio == '!info':
                    if main_loop: asyncio.run_coroutine_threadsafe(procesar_comando_malla("info"), main_loop)
                elif texto_limpio == '!tiempo':
                    if main_loop: asyncio.run_coroutine_threadsafe(procesar_comando_malla("tiempo"), main_loop)
                elif texto_limpio == '!mar':
                    if main_loop: asyncio.run_coroutine_threadsafe(procesar_comando_malla("mar"), main_loop)
                elif texto_limpio == '!alerta':
                    if main_loop: asyncio.run_coroutine_threadsafe(procesar_comando_malla("alerta"), main_loop)
                elif texto_limpio == '!canalic':
                    if main_loop: asyncio.run_coroutine_threadsafe(procesar_comando_malla("canalic"), main_loop)
                elif texto_limpio == '!canaltg':
                    if main_loop: asyncio.run_coroutine_threadsafe(procesar_comando_malla("canaltg"), main_loop)
                else:
                    mensaje_telegram = f"📡 [{long_name}]: {text}"
                    if telegram_app and main_loop:
                        asyncio.run_coroutine_threadsafe(
                            telegram_app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=mensaje_telegram),
                            main_loop
                        )
                    
    except Exception as e:
        logging.error(f"Error procesando el paquete entrante: {e}")

# --- COMANDOS DE TELEGRAM ---

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID): return
    mensaje_ayuda = (
        "🤖 *Menú del Bridge Meshtastic*\n\n"
        "📖 /info - ¿Qué es esto y cómo funciona?\n"
        "📖 /help - Lista de comandos rápidos.\n"
        "🇮🇨 /CanalIC - URL para añadir canal Canarias.\n"
        "📲 /CanalTG - Enlace al grupo de Telegram.\n"
        "🏓 /ping - Test de conexión.\n"
        "📡 /nodos - Nodos vistos por la antena.\n"
        "⛅ /tiempo - Clima (TF y GC).\n"
        "🌊 /mar - Oleaje medio.\n"
        "⚠️ /alerta - Avisos AEMET.\n\n"
        "_Radio: usa ! (ej. !info)_"
    )
    await update.message.reply_text(mensaje_ayuda, parse_mode='Markdown')

async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Explica el funcionamiento del bridge de forma amigable."""
    if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID): return
    mensaje_info = (
        "🔗 *¿Cómo funciona este Bridge?*\n\n"
        "Este sistema conecta la red de radio **Meshtastic** (malla sin internet) con este grupo de **Telegram**.\n\n"
        "1️⃣ **Telegram ➔ Radio:** Cualquier mensaje escrito aquí (que no sea un comando) se enviará por radio a través del nodo local. Hay una pausa de 5 segundos entre mensajes para no saturar la frecuencia.\n\n"
        "2️⃣ **Radio ➔ Telegram:** Los mensajes que circulan por la red Mesh en el canal configurado aparecerán aquí automáticamente.\n\n"
        "3️⃣ **Servicios Integrados:** Los usuarios en el campo (sin internet) pueden pedir información útil enviando comandos como `!tiempo` o `!alerta` desde sus radios.\n\n"
        "🚀 *Objetivo:* Mantener la comunicación fluida y ofrecer servicios de datos a quienes están fuera de cobertura móvil."
    )
    await update.message.reply_text(mensaje_info, parse_mode='Markdown')

async def cmd_canaltg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID): return
    url_tg = "https://t.me/meshtastic_canarias"
    mensaje = f"📲 *Canal Telegram Meshtastic Canarias*\n\nÚnete a la comunidad local aquí:\n\n{url_tg}"
    await update.message.reply_text(mensaje, parse_mode='Markdown')

async def cmd_canalic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID): return
    url_canarias = "https://meshtastic.org/e/?add=true#ChESAQEaCENhbmFyaWFzKAEwARIMCAFAA0gBwAYAyAYB"
    mensaje = f"🇮🇨 *Canal Canarias Meshtastic*\n\nUsa el siguiente enlace para añadir el canal a tu aplicación:\n\n{url_canarias}"
    await update.message.reply_text(mensaje, parse_mode='Markdown')

async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID): return
    await update.message.reply_text("🏓 Pong. El Bridge Meshtastic está operativo.")

async def cmd_nodos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID): return
    if interface and interface.nodes:
        await update.message.reply_text(f"📡 Mi antena local ve {len(interface.nodes) - 1} nodos.")
    else:
        await update.message.reply_text("⚠️ No hay conexión con la base de datos de nodos.")

async def cmd_tiempo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID): return
    await update.message.reply_text(await get_tiempo())

async def cmd_mar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID): return
    await update.message.reply_text(await get_mar())

async def cmd_alerta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID): return
    await update.message.reply_text(await get_alerta())

async def handle_telegram_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID): return
    if not update.message or not update.message.text: return
    if update.message.text.startswith('/'): return

    user_name = update.message.from_user.first_name if update.message.from_user else "Anónimo"
    nombre_limpio = unicodedata.normalize('NFKC', user_name)
    texto_limpio = unicodedata.normalize('NFKC', update.message.text)
    
    mensaje_mesh = f"{nombre_limpio}: {texto_limpio}"
    await cola_tx_malla.put(mensaje_mesh)

async def main():
    global interface, telegram_app, main_loop
    main_loop = asyncio.get_running_loop()

    telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    telegram_app.add_handler(CommandHandler("help", cmd_help))
    telegram_app.add_handler(CommandHandler("info", cmd_info)) # Nuevo registro
    telegram_app.add_handler(CommandHandler("CanalIC", cmd_canalic))
    telegram_app.add_handler(CommandHandler("CanalTG", cmd_canaltg))
    telegram_app.add_handler(CommandHandler("ping", cmd_ping))
    telegram_app.add_handler(CommandHandler("nodos", cmd_nodos))
    telegram_app.add_handler(CommandHandler("tiempo", cmd_tiempo))
    telegram_app.add_handler(CommandHandler("mar", cmd_mar))
    telegram_app.add_handler(CommandHandler("alerta", cmd_alerta))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_telegram_message))

    logging.info(f"Iniciando Bridge Meshtastic <-> Telegram...")
    pub.subscribe(on_receive, "meshtastic.receive")
    
    try:
        interface = meshtastic.serial_interface.SerialInterface(devPath=MESHTASTIC_PORT)
        logging.info("Conexión Meshtastic establecida.")
    except Exception as e:
        logging.error(f"Fallo crítico: No se pudo abrir el puerto. Error: {e}")
        return

    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling()
    
    asyncio.create_task(monitor_aemet())
    asyncio.create_task(trabajador_cola_tx())

    logging.info(f"✅ Bridge 100% Operativo con Atom AEMET Canarias.")

    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        if interface: interface.close()
        await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBridge detenido.")
```
Guarda el archivo (en nano: `Ctrl+O`, `Enter`, `Ctrl+X`).

---

## FASE 4: Configuración del Servicio Automático (Systemd)
Para que arranque solo al encender Proxmox.

**1. Crear el archivo del servicio:**
```bash
sudo nano /etc/systemd/system/meshbridge.service
```

**2. Pegar esta configuración:**
```ini
[Unit]
Description=Bridge Meshtastic Telegram
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/meshtastic_bridge
ExecStart=/opt/meshtastic_bridge/meshtastic_env/bin/python /opt/meshtastic_bridge/bridge_meshtastic_telegram.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```
*(Nota: Hemos ajustado las rutas asumiendo que seguiste el paso 2 de crear la carpeta `/opt/meshtastic_bridge`)*. Guarda y sal.

**3. Activar y lanzar:**
```bash
systemctl daemon-reload
systemctl enable meshbridge.service
systemctl start meshbridge.service
```
**Para ver la consola en directo en cualquier momento:** `journalctl -fu meshbridge`

---

## FASE 5: Configurar Menú en Telegram (@BotFather)
Ve a Telegram, abre el chat con **@BotFather**, usa el comando `/setcommands`, elige tu bot y pega este bloque:
```text
help - Muestra las opciones y ayuda
ping - Comprueba la conexion del nodo
nodos - Nodos locales por RF
tiempo - Clima actual en la zona
mar - Estado del oleaje
alerta - Avisos de la AEMET
```

---

## FASE 6: Backups de Seguridad
1. **Configuración del nodo físico:**
   Ve a `/opt/meshtastic_bridge`, activa el entorno (`source meshtastic_env/bin/activate`) y guarda la configuración de la placa:
   ```bash
   meshtastic --export-config > backup_nodo_meshtastic.yaml
   ```
2. **Copia de seguridad del Servidor:** En la interfaz web de Proxmox, selecciona tu LXC, ve a "Backup" y haz un respaldo manual. Esto guarda tu sistema operativo, las librerías y el código de Python de una sola vez.