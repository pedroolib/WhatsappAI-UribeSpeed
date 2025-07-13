from flask import Flask, request, jsonify
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
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Configura OpenAI
client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# Configura Twilio
twilio_account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
twilio_auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
twilio_client = Client(twilio_account_sid, twilio_auth_token)

# Usuarios permitidos en el Inbox webapp (identity)
usuarios_permitidos = [
    "Pedro Librado",
    "Joan Pedro"
]

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
4. Qué incluye o cuales son los servicios que maneja el taller
5. Saludos y despedidas

Si el cliente no da todos los datos necesarios para el cambio de aceite (año, marca, modelo y cilindros), pídele los que falten dando seguimiento a la conversación.

Si pregunta algo fuera de esos temas, responde:
"Un asesor te responderá en un momento para darte más información sobre eso 👨‍🔧"

Siempre responde en español, de manera clara, amable y humana. Puedes utilizar emojis para hacer más atractivo el mensaje.

Información del taller Uribe Speed Tune Up:

- Horarios:
  - Lunes a viernes: 8 a.m.–6 p.m.
  - Sábado: 8 a.m.–3 p.m.
  - Domingo: Cerrado.

- Ubicaciones:
  1. Calle Río Culiacán esquina con Av. República de Ecuador 950, Cuauhtémoc Nte, 21200 Mexicali, B.C.
  2. C. Granada 489, Residencial Madrid, 21353 Mexicali, B.C.

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
sheet = gc.open_by_key("1oW6ERLY99pOvxLibre54wfPylGb6l_wvEXz0hshBkcw").sheet1
rows = sheet.get_all_records()

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

# Enviar mensaje directamente por la API de WhatsApp (no se verá en Flex)
def enviar_mensaje_whatsapp_directo(numero, texto, mediaUrl=None):
    try:
        if mediaUrl:
            twilio_client.messages.create(
                from_='whatsapp:+16084708949',
                to=numero,
                body=texto,
                media_url=[mediaUrl]
            )
        else:
            twilio_client.messages.create(
                from_='whatsapp:+16084708949',
                to=numero,
                body=texto
            )
        print("Mensaje enviado por WhatsApp API (no visible en Flex)")
    except Exception as e:
        print("Error enviando mensaje con WhatsApp API:", e)

# Normalizar número de teléfono
def normalizar_numero(numero):
    """Normaliza el número de teléfono para usarlo como friendly_name"""
    if numero.startswith("whatsapp:"):
        return numero
    return f"whatsapp:{numero}"

# Buscar conversación existente por número de teléfono
def buscar_conversacion_existente(numero_whatsapp):
    """Busca una conversación existente usando el número como friendly_name"""
    try:
        numero_normalizado = normalizar_numero(numero_whatsapp)
        conversaciones = twilio_client.conversations.v1.conversations.list(limit=100)

        for conv in conversaciones:
            if conv.friendly_name == numero_normalizado:
                print(f"✅ Conversación encontrada: {conv.sid} para {numero_normalizado}")
                return conv.sid

        print(f"❌ No se encontró conversación para {numero_normalizado}")
        return None
    except Exception as e:
        print(f"Error buscando conversación existente: {e}")
        return None

# Verificar si un participante ya existe en la conversación
def participante_existe(conversation_sid, identity=None, address=None):
    """Verifica si un participante ya existe en la conversación"""
    try:
        participantes = twilio_client.conversations.v1.conversations(conversation_sid).participants.list()

        for participante in participantes:
            if identity and participante.identity == identity:
                return True
            if address and participante.messaging_binding and participante.messaging_binding.get('address') == address:
                return True

        return False
    except Exception as e:
        print(f"Error verificando participante: {e}")
        return False

# Agregar usuarios permitidos a la conversación
def agregar_usuarios_permitidos(conversation_sid):
    """Agrega todos los usuarios permitidos a la conversación si no están ya"""
    for usuario in usuarios_permitidos:
        try:
            if not participante_existe(conversation_sid, identity=usuario):
                twilio_client.conversations.v1.conversations(conversation_sid).participants.create(
                    identity=usuario
                )
                print(f"✅ Usuario {usuario} agregado a la conversación {conversation_sid}")
            else:
                print(f"👤 Usuario {usuario} ya existe en la conversación {conversation_sid}")
        except Exception as e:
            print(f"❌ Error agregando usuario {usuario}: {e}")

# Crear conversación única para un número
def crear_conversacion_unica(numero_whatsapp):
    """Crea una nueva conversación única para el número de teléfono"""
    try:
        numero_normalizado = normalizar_numero(numero_whatsapp)

        # Crear la conversación con el número como friendly_name
        conversacion = twilio_client.conversations.v1.conversations.create(
            friendly_name=numero_normalizado
        )

        print(f"✅ Nueva conversación creada: {conversacion.sid} para {numero_normalizado}")

        # Agregar el participante de WhatsApp
        try:
            twilio_client.conversations.v1.conversations(conversacion.sid).participants.create(
                messaging_binding_address=numero_normalizado,
                messaging_binding_proxy_address=os.environ.get("TWILIO_WHATSAPP_NUMBER")
            )
            print(f"✅ Participante WhatsApp agregado: {numero_normalizado}")
        except Exception as e:
            print(f"❌ Error agregando participante WhatsApp: {e}")

        # Agregar usuarios permitidos
        agregar_usuarios_permitidos(conversacion.sid)

        return conversacion.sid
    except Exception as e:
        print(f"❌ Error creando conversación para {numero_whatsapp}: {e}")
        return None

# Obtener o crear conversación única
def obtener_o_crear_conversacion_unica(numero_whatsapp):
    """Obtiene una conversación existente o crea una nueva única para el número"""
    numero_normalizado = normalizar_numero(numero_whatsapp)

    # Buscar conversación existente
    conversation_sid = buscar_conversacion_existente(numero_normalizado)

    if conversation_sid:
        # Asegurarse de que los usuarios permitidos estén en la conversación
        agregar_usuarios_permitidos(conversation_sid)
        return conversation_sid

    # No existe, crear una nueva
    return crear_conversacion_unica(numero_normalizado)

# Limpiar conversaciones antiguas
def limpiar_conversaciones_antiguas(max_conversaciones=90, conservar=50):
    try:
        conversaciones = twilio_client.conversations.v1.conversations.list(limit=200)
        if len(conversaciones) <= max_conversaciones:
            return

        # Reemplazar None por una fecha antigua (para que se vayan al principio al ordenar)
        conversaciones_ordenadas = sorted(
            conversaciones,
            key=lambda c: c.date_created or datetime(2000, 1, 1)
        )

        a_borrar = conversaciones_ordenadas[:len(conversaciones) - conservar]

        for conv in a_borrar:
            try:
                twilio_client.conversations.v1.conversations(conv.sid).delete()
                print(f"🗑️ Conversación {conv.sid} eliminada")
            except Exception as e:
                print(f"❌ No se pudo eliminar conversación {conv.sid}: {e}")

    except Exception as e:
        print(f"Error al limpiar conversaciones: {e}")

# Endpoint para recibir mensajes de WhatsApp
@app.route('/webhook', methods=['POST'])
def webhook():
    req = request.form.to_dict() or request.json

    author = req.get('From', '')
    if author != '' and not author.startswith("whatsapp:"):
        print("Mensaje del agente, no responde el bot")
        return "Mensaje del agente ignorado", 200

    mensaje = req.get('Body', '')
    numero = req.get('From', '')
    conversation_sid = req.get('ConversationSid', None)

    print(f"📨 Mensaje recibido de {numero}: {mensaje}")

    # Si no hay ConversationSid, obtener o crear conversación única
    if not conversation_sid:
        conversation_sid = obtener_o_crear_conversacion_unica(numero)
        if not conversation_sid:
            print("❌ No se pudo obtener ni crear conversación")
            return "Error creando conversación", 500

    # Inicializar memoria si no existe
    if numero not in memoria:
        memoria[numero] = {
            "mensajes": [],
            "esperando_asesor": False
        }

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
                        "description": "Busca el precio del cambio de aceite en Google Sheets",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "año": {"type": "string"},
                                "marca": {"type": "string"},
                                "modelo": {"type": "string"},
                                "cilindros": {"type": "string"}
                            },
                            "required": ["año", "marca", "modelo", "cilindros"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "detectar_servicio",
                        "description": "Detecta si el usuario quiere saber qué incluye un servicio específico",
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
                        f"Puedes venir sin necesidad de cita y te atendemos al instante 🏎️ 💨. Si prefieres agendar, también se puede 😉"
                    )
                else:
                    final = "No encontré ese vehículo en mi base de datos 🚗. Un asesor te ayudará pronto 👨‍🔧"
                memoria[numero]["mensajes"] = []

            elif tool_call.function.name == "detectar_servicio":
                servicio = argumentos["servicio"]
                url_imagen = imagenes_servicios.get(servicio)
                if url_imagen:
                    enviar_mensaje_whatsapp_directo(numero, f"Esto es lo que incluye el {servicio} 👆", url_imagen)
                    memoria[numero]["mensajes"] = []
                    return "OK", 200
                else:
                    final = "No encontré ese servicio en mi catálogo. Un asesor te apoyará pronto 👨‍🔧"
                memoria[numero]["mensajes"] = []

        else:
            final = mensaje_gpt.content
            memoria[numero]["mensajes"].append({"role": "assistant", "content": final})

    except Exception as e:
        print(f"❌ Error procesando mensaje: {e}")
        final = "Tuvimos un problema con tu mensaje. Intenta más tarde o espera a que un asesor te apoye 😊"
        memoria[numero]["mensajes"] = []

    # Enviar respuesta a través de Twilio Conversations
    try:
        twilio_client.conversations.v1.conversations(conversation_sid).messages.create(body=final)
        print(f"✅ Respuesta enviada a conversación {conversation_sid}")
    except Exception as e:
        print(f"❌ Error enviando respuesta: {e}")

    return "OK", 200

# Endpoint para generar token de Twilio desde el frontend
@app.route('/token', methods=['GET'])
def generar_token():
    identity = request.args.get('identity')

    if not identity:
        return make_response('Falta identity', 400)

    if identity not in usuarios_permitidos:
        return make_response('Usuario no autorizado', 403)

    account_sid = os.environ['TWILIO_ACCOUNT_SID']
    api_key_sid = os.environ['TWILIO_API_KEY_SID']
    api_key_secret = os.environ['TWILIO_API_KEY_SECRET']
    service_sid = os.environ['TWILIO_CONVERSATION_SERVICE_SID']

    token = AccessToken(account_sid, api_key_sid, api_key_secret, identity=identity)
    chat_grant = ChatGrant(service_sid=service_sid)
    token.add_grant(chat_grant)

    jwt = token.to_jwt()
    return make_response(jwt, 200)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)