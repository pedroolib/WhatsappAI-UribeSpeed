from flask import Flask, request
from flask import make_response
from flask_cors import CORS
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import ChatGrant
import openai
import os
import gspread
import json
from oauth2client.service_account import ServiceAccountCredentials
from twilio.rest import Client
import threading
import time
from datetime import datetime, timedelta
import pytz

app = Flask(__name__)
CORS(app)

# Configura OpenAI
client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# Configura Twilio
twilio_account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
twilio_auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
service_sid = os.environ.get("TWILIO_CONVERSATION_SERVICE_SID")
twilio_client = Client(twilio_account_sid, twilio_auth_token)

# Usuarios permitidos en el Inbox webapp (identity)
usuarios_permitidos = {
    "Pedro Librado" : "talleruribe1",
    "Bot Uribe Speed" : "talleruribe1",
    "Joan Pedro" : "talleruribe1"
}

# Diccionario de imágenes para servicios
imagenes_servicios = {
    "Cambio de Aceite": "https://i.ibb.co/xS8M9vPK/CAM-AM.jpg",
    "Afinación Mayor": "https://i.ibb.co/xS8M9vPK/CAM-AM.jpg",
    "Servicio de Frenos": "https://i.ibb.co/3gqgSrD/Frenos-Anti-Cong.jpg",
    "Servicio Anticongelante": "https://i.ibb.co/3gqgSrD/Frenos-Anti-Cong.jpg",
    "Servicio de Aire Acondicionado": "https://i.ibb.co/JZ1zjqc/Aire-LICUAC.jpg",
    "Limpieza y Servicio al Cuerpo de Aceleración": "https://i.ibb.co/JZ1zjqc/Aire-LICUAC.jpg",
    "Servicio de Transmisión Automática con Cedazo": "https://i.ibb.co/F4NVPFRW/Transmision.jpg",
    "Servicio de Transmisión Automática sin Cedazo": "https://i.ibb.co/F4NVPFRW/Transmision.jpg",
    "Limpieza de Inyectores": "https://i.ibb.co/7xP0q81s/INYEC.jpg",
    "Servicio al Sistema de Inyección": "https://i.ibb.co/7xP0q81s/INYEC.jpg",
}

# Prompt base
prompt_sistema = """
Eres un asistente de WhatsApp para el taller Uribe Speed Tune Up. Solo puedes responder si el cliente pregunta por:

1. El precio del cambio de aceite (según año, marca, modelo y cilindros del auto)
2. Los horarios del taller
3. Las ubicaciones del taller
4. Cuáles son los servicios que maneja el taller y que incluye cada uno o mas informacion de cada servicio
5. Saludos y despedidas
6. Si el cliente quiere agendar una cita
7. Metodos de pago del taller

Cuando un cliente quiere agendar una cita, pídele los siguientes datos:
- Su nombre completo
- Servicio que desea (solo si no está claro por el contexto de la conversación)
- Datos del vehiculo (solo si no está claro por el contexto de la conversación)
- Día y hora que le gustaría agendar la cita
- Sucursal del taller

No confirmes citas ni digas que ya está agendada. Solo menciona que un asesor confirmará la disponibilidad y te dará seguimiento. 

Si el cliente pregunta solo por el **precio** de un servicio como "Afinación Mayor" o cualquier otro que no sea cambio de aceite, NO uses la herramienta `mas_info_servicio`. Solo usa esa herramienta si el cliente quiere saber qué **incluye** un servicio o pide **más detalles** sobre qué se hace. Si pregunta solo por el precio, responde que un asesor lo atenderá pronto excepto si es de cambio de aceite.

Si el cliente vuelve a preguntar por otro servicio o vehiculo después de que ya se mostró uno, cambia el contexto y responde para el nuevo servicio o vehiculo mencionado.

Cuando un cliente pide precio de cambio de aceite, necesitas que proporcione estos 4 datos: **año, marca, modelo y cilindros**.  
**Ignora versiones del modelo** (como "EX", "Sport", "Advance", etc.). Solo considera la marca (como Honda, Nissan) y el modelo principal (como Civic, Sentra).  
Por ejemplo, si dice "Civic EX" o "Sentra Advance", solo toma "Civic" o "Sentra" como modelo. No pidas la versión.

Si no da todos los datos necesarios, pídele los que falten de forma amable, dando seguimiento a la conversación.

Si pregunta algo fuera de esos temas, responde de forma amable diciendo que un asesor lo atenderá pronto 👨‍🔧. Puedes usar frases diferentes, pero siempre transmite que alguien del equipo lo ayudará con eso. No inventes una respuesta si no está entre los temas permitidos.

Siempre responde en español, de manera clara, amable y humana. Puedes utilizar emojis para hacer más atractivo el mensaje.

Información del taller Uribe Speed Tune Up:

- Horarios:
  - Lunes a viernes: 8 a.m.–6 p.m.
  - Sábado: 8 a.m.–3 p.m.
  - Domingo: Cerrado.

- Ubicaciones:
  1. Calle Río Culiacán esquina con Av. República de Ecuador 950, Cuauhtémoc Nte, 21200 Mexicali, B.C.
    https://maps.app.goo.gl/uXFdv2ovXKdscUde8
  
  2. C. Granada 489, Residencial Madrid, 21353 Mexicali, B.C.
    https://maps.app.goo.gl/7wkkkFndL7fGjpmZ9

- Métodos de pago:
  - 💵 Efectivo
  - 💳 Tarjeta de crédito o débito

- Servicios:
  - 🛢️ Cambio de Aceite
  - 🧰 Afinación mayor
  - 🚦 Servicio de Frenos
  - 🦿 Cambio de Amortiguadores
  - 🌡️ Servicio Anticongelante
  - ❄️ Servicio de Aire Acondicionado
  - ⚙️ Limpieza y Servicio al Cuerpo de Aceleración
  - 🛠️ Servicio de Transmisión Automática con Cedazo
  - 🔁 Servicio de Transmisión Automática sin Cedazo
  - 💨 Limpieza de Inyectores
  - 🧪 Servicio al Sistema de Inyección

Los mensajes que ha escrito el cliente hasta ahora son:

"""

# Conexión a Google Sheets
scope = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/drive'
]
creds = ServiceAccountCredentials.from_json_keyfile_name(
    'credenciales.json', scope)
gc = gspread.authorize(creds)
spreadsheet = gc.open_by_key("1oW6ERLY99pOvxLibre54wfPylGb6l_wvEXz0hshBkcw")
sheet = spreadsheet.sheet1
rows = sheet.get_all_records()
sheet_eventos = spreadsheet.worksheet("Estadísticas")

# Función para registrar eventos en Google Sheets
def registrar_evento(numero, tipo_evento):
    zona = pytz.timezone("America/Tijuana")
    ahora = datetime.now(zona)
    timestamp = ahora.strftime("%Y-%m-%d %H:%M")
    try:
        sheet_eventos.append_row([timestamp, numero, tipo_evento])
        print(f"Evento registrado: {timestamp} | {numero} | {tipo_evento}")
    except Exception as e:
        print(f"Error al registrar evento en Sheets: {e}")

# Memoria por usuario
memoria = {}

# Buscar precio en Google Sheets
def buscar_precio(a, m, mo, c):
    for row in rows:
        if (str(row['AÑO']).strip() == str(a).strip() and str(
                row['MARCA']).strip().lower() == str(m).strip().lower() and
                str(row['MODELO']).strip().lower() == str(mo).strip().lower()
                and str(row['CILINDROS']).strip() == str(c).strip()):
            sint = row.get('ACEITE SINTETICO PRECIO', 'No disponible')
            semi = row.get('ACEITE SEMISINTETICO PRECIO', 'No disponible')
            return sint, semi
    return None, None

# Agregar usuarios permitidos a la conversación
def agregar_usuarios_permitidos(conversation_sid):
    #Agrega todos los usuarios permitidos a la conversación si no están ya
    for usuario, clave in usuarios_permitidos.items():
        try:
            participantes = twilio_client.conversations.v1.services(service_sid).conversations(conversation_sid).participants.list()

            usuario_existe = any(p.identity == usuario for p in participantes)

            if not usuario_existe:
                twilio_client.conversations.v1.services(service_sid).conversations(conversation_sid).participants.create(
                    identity=usuario
                )
                print(f"✅ Usuario {usuario} agregado a la conversación {conversation_sid}")
            else:
                print(f"👤 Usuario {usuario} ya existe en la conversación {conversation_sid}")

        except Exception as e:
            print(f"❌ Error agregando usuario {usuario}: {e}")

# Enviar mensaje como Bot Uribe Speed
def enviar_mensaje_como_bot(conversation_sid, mensaje):
    """Envía un mensaje como el Bot Uribe Speed en la conversación"""
    try:
        twilio_client.conversations.v1.services(service_sid).conversations(conversation_sid).messages.create(
            author="Bot Uribe Speed",
            body=mensaje
        )
        print(f"✅ Mensaje enviado como Bot Uribe Speed a conversación {conversation_sid}")
        return True
    except Exception as e:
        print(f"❌ Error enviando mensaje como bot: {e}")
        return False

# Enviar imagen directamente por la API de WhatsApp (no se verá en el inbox)
def enviar_imagen_whatsapp_directo(numero, mediaUrl=None):
    try:
        if mediaUrl:
            twilio_client.messages.create(
                from_='whatsapp:+16084708949',
                to=numero,
                media_url=[mediaUrl]
            )
        print("Mensaje enviado por WhatsApp API (no visible en Inbox)")
    except Exception as e:
        print("Error enviando mensaje con WhatsApp API:", e)

# Función para limpiar conversaciones antiguas
def limpiar_memoria_inactiva():
    while True:
        tiempo_limite = timedelta(days=3)
        ahora = datetime.now()
        inactivos = []

        for numero, datos in memoria.items():
            ultima = datos.get("ultima_interaccion")
            if ultima and ahora - ultima > tiempo_limite:
                inactivos.append(numero)

        for numero in inactivos:
            print(f"🧹 Borrando memoria de {numero} por inactividad")
            del memoria[numero]

        time.sleep(3600)  # espera 1 hora antes de volver a revisar

# Endpoint para recibir mensajes de WhatsApp
@app.route('/webhook', methods=['POST'])
def webhook():
    req = request.form.to_dict() or request.json

    numero = req.get('Author', '')
    mensaje = req.get('Body', '')
    conversation_sid = req.get('ConversationSid', None)

    print(f"📨 Mensaje recibido de {numero} (autor: {numero}): {mensaje}")

    # Si el mensaje viene de un agente o del bot, ignorar
    if numero and numero in usuarios_permitidos:
        print("Mensaje del agente, no responde el bot")
        registrar_evento(numero, "Mensaje de agente")
        return "Mensaje del agente ignorado", 200

    registrar_evento(numero, "Mensaje de cliente")
    
    # Agregar usuarios permitidos a la conversación si no están
    try:
        agregar_usuarios_permitidos(conversation_sid)
    except Exception as e:
        print(f"❌ Error agregando usuarios permitidos: {e}")

    # Inicializar memoria si no existe
    if numero not in memoria:
        memoria[numero] = {
            "mensajes": [],
            "esperando_asesor": False,
            "ultima_interaccion": datetime.now()
        }

    # Añadir mensaje a la memoria
    memoria[numero]["mensajes"].append({"role": "user", "content": mensaje})

    final = "Tuvimos un problema con tu mensaje. Intenta más tarde o espera a que un asesor te apoye 😊"

    try:
        respuesta_gpt = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": prompt_sistema}] + memoria[numero]["mensajes"],
            tools=[
                {
                  "type": "function",
                  "function": {
                    "name": "buscar_precio",
                    "description": (
                        "Busca el precio del cambio de aceite en Google Sheets. "
                        "El modelo debe ser solo el nombre principal, sin versión (por ejemplo, 'Civic', no 'Civic EX'). "
                        "La marca y el modelo deben ir sin acentos. "
                        "Ejemplos válidos: año='2018', marca='nissan', modelo='sentra', cilindros='4'."
                    ),
                    "parameters": {
                      "type": "object",
                      "properties": {
                        "año": {
                          "type": "string",
                          "description": "Año del vehículo, por ejemplo '2018'."
                        },
                        "marca": {
                          "type": "string",
                          "description": "Marca del vehículo, sin acentos. Por ejemplo: 'nissan'."
                        },
                        "modelo": {
                          "type": "string",
                          "description": "Modelo principal del vehículo, sin versión ni acento. Por ejemplo: 'sentra'."
                        },
                        "cilindros": {
                          "type": "string",
                          "description": "Número de cilindros. Ejemplo: '4'."
                        }
                      },
                      "required": ["año", "marca", "modelo", "cilindros"]
                    }
                  }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "mas_info_servicio",
                        "description": "Detecta si el usuario quiere saber qué se hace en un servicio específico",
                        "parameters": {
                          "type": "object",
                          "properties": {
                            "servicio": {
                              "type": "string",
                              "description": "Nombre exacto del servicio que el usuario quiere conocer",
                              "enum": [
                                  "Cambio de Aceite",
                                  "Afinación Mayor",
                                  "Servicio de Frenos",
                                  "Servicio Anticongelante",
                                  "Servicio de Aire Acondicionado",
                                  "Limpieza y Servicio al Cuerpo de Aceleración",
                                  "Servicio de Transmisión Automática con Cedazo",
                                  "Servicio de Transmisión Automática sin Cedazo",
                                  "Limpieza de Inyectores",
                                  "Servicio al Sistema de Inyección"
                              ]
                            }
                          },
                          "required": ["servicio"]
                        }
                    }
                }
            ],
            tool_choice="auto"
        )

        mensaje_gpt = respuesta_gpt.choices[0].message

        if mensaje_gpt.tool_calls:
            tool_call = mensaje_gpt.tool_calls[0]
            argumentos = json.loads(tool_call.function.arguments)

            if tool_call.function.name == "buscar_precio":
                sint, semi = buscar_precio(
                    str(argumentos['año']),
                    str(argumentos['marca']).lower(),
                    str(argumentos['modelo']).lower(),
                    str(argumentos['cilindros'])
                )
                if sint and semi:
                    final = (
                        f"El cambio de aceite para tu {argumentos['marca'].title()} {argumentos['modelo'].title()} {argumentos['año']} "
                        f"({argumentos['cilindros']} cilindros), cuesta:\n\n"
                        f"🔧 Sintético: {sint}\n"
                        f"🔧 Semisintético: {semi}\n\n"
                        f"Puedes venir sin necesidad de cita y te atendemos al instante 🏎️💨. O dime si prefieres que agendemos una cita 😉"
                    )
                    registrar_evento(numero, "Cotización Enviada")
                else:
                    final = "No encontré ese vehículo en mi base de datos 🚗. Un asesor te ayudará pronto 👨‍🔧"
                    registrar_evento(numero, "Fallo en Cotización")

            elif tool_call.function.name == "mas_info_servicio":
                servicio = argumentos["servicio"]
                url_imagen = imagenes_servicios.get(servicio)
                if url_imagen:
                    # Enviar imagen como Bot Uribe Speed
                    final = f"Esto es lo que incluye el {servicio} 🛠️ ¿Te gustaría agendar una cita? 📅"
                    enviar_imagen_whatsapp_directo(numero, url_imagen)
                    enviar_mensaje_como_bot(conversation_sid, final)
                    memoria[numero]["mensajes"].append({"role": "assistant", "content": final})
                    registrar_evento(numero, "Información de Servicio")
                    return "OK", 200
                else:
                    final = "No encontré ese servicio en mi catálogo. Un asesor te apoyará pronto 👨‍🔧"
                memoria[numero]["mensajes"].append({"role": "assistant", "content": final})
        else:
            final = mensaje_gpt.content
            registrar_evento(numero, "Mensaje del bot")

    except Exception as e:
        print(f"❌ Error procesando mensaje: {e}")
        registrar_evento(numero, "Error en procesamiento")
        final = "Tuvimos un problema con tu mensaje. Intenta más tarde o espera a que un asesor te apoye 😊"

    # Enviar respuesta como Bot Uribe Speed y guardar en memoria el mensaje del bot
    enviar_mensaje_como_bot(conversation_sid, final)
    memoria[numero]["mensajes"].append({"role": "assistant", "content": final})

    return "OK", 200

# Endpoint para generar token de Twilio desde el frontend
@app.route('/token', methods=['GET'])
def generar_token():
    identity = request.args.get('identity')
    password = request.args.get('password')

    if not identity or not password:
        return make_response('Faltan datos', 400)

    if identity not in usuarios_permitidos:
        return make_response('Usuario no autorizado', 403)

    if usuarios_permitidos[identity] != password:
        return make_response('Credenciales incorrectas', 401)

    account_sid = os.environ['TWILIO_ACCOUNT_SID']
    api_key_sid = os.environ['TWILIO_API_KEY_SID']
    api_key_secret = os.environ['TWILIO_API_KEY_SECRET']

    token = AccessToken(account_sid, api_key_sid, api_key_secret, identity=identity)
    chat_grant = ChatGrant(service_sid=service_sid)
    token.add_grant(chat_grant)

    jwt = token.to_jwt()
    return make_response(jwt, 200)

if __name__ == '__main__':
    threading.Thread(target=limpiar_memoria_inactiva, daemon=True).start()
    app.run(host='0.0.0.0', port=5000)