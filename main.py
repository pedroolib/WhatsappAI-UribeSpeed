from flask import Flask, request
import openai
import os
import gspread
import json
from oauth2client.service_account import ServiceAccountCredentials
from twilio.rest import Client

app = Flask(__name__)

# Configura OpenAI
client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# Configura Twilio
twilio_account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
twilio_auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
twilio_client = Client(twilio_account_sid, twilio_auth_token)

# Prompt base
prompt_sistema = """
Eres un asistente de WhatsApp para el taller Uribe Speed Tune Up. Solo puedes responder si el cliente pregunta por:

1. El precio del cambio de aceite (según año, marca, modelo y cilindros del auto)
2. Los horarios del taller
3. Las ubicaciones del taller
4. Qué incluye un servicio del taller

Si el cliente no da todos los datos necesarios para el cambio de aceite (año, marca, modelo y cilindros), pídele los que falten dando seguimiento a la conversación.

Si pregunta algo fuera de esos temas, responde:
"Un asesor te responderá en un momento para darte más información sobre eso 👨‍🔧"

Siempre responde en español, de manera clara, amable y humana. Puedes utilizar emojis para hacer más atractivo el mensaje.

Información del taller Uribe Speed Tune Up:

- Horarios:
  - Lunes a viernes: 8 a.m.–6 p.m.
  - Sábado: 8 a.m.–3 p.m.
  - Domingo: Cerrado.

- Ubicaciones:
  1. Calle Río Culiacán esquina con Av. República de Ecuador 950, Cuauhtémoc Nte, 21200 Mexicali, B.C.
  2. C. Granada 489, Residencial Madrid, 21353 Mexicali, B.C.

- Servicios:
  - 🔧 Tune Up General: Ajuste completo para que tu motor funcione como nuevo.
  - 🚦 Cambio de Balatas Generales: Seguridad garantizada con frenos en perfecto estado.
  - ❄️ Servicio de Anticongelante: Protege tu motor en cualquier clima.
  - Y más servicios relacionados al mantenimiento preventivo de tu auto.

Los mensajes que ha escrito el cliente hasta ahora son:
"""


# Conexión a Google Sheets
scope = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/drive'
]
creds = ServiceAccountCredentials.from_json_keyfile_name('credenciales.json', scope)
gc = gspread.authorize(creds)
sheet = gc.open_by_key("1oW6ERLY99pOvxLibre54wfPylGb6l_wvEXz0hshBkcw").sheet1
rows = sheet.get_all_records()

# Memoria por usuario
memoria = {}

def buscar_precio(a, m, mo, c):
    for row in rows:
        if (str(row['AÑO']).strip() == str(a).strip() and
            str(row['MARCA']).strip().lower() == str(m).strip().lower() and
            str(row['MODELO']).strip().lower() == str(mo).strip().lower() and
            str(row['CILINDROS']).strip() == str(c).strip()):
            sint = row.get('ACEITE SINTETICO PRECIO', 'No disponible')
            semi = row.get('ACEITE SEMISINTETICO PRECIO', 'No disponible')
            return sint, semi
    return None, None

@app.route('/webhook', methods=['POST'])
def webhook():
    req = request.form.to_dict() or request.json

    # No responder a un mensaje enviado por el agente
    author = req.get('From', '') 
    if author != '' and not author.startswith("whatsapp:"):
        print("Mensaje del agente, no responde el bot")
        return "Mensaje del agente ignorado", 200

    # Datos del mensaje recibidos
    print("Datos recibidos:", req)

    mensaje = req.get('Body', '')
    numero = req.get('From', '')
    conversation_sid = req.get('ConversationSid', None)

    # Memoria por usuario de toda la conversación
    if numero not in memoria:
        memoria[numero] = []

    memoria[numero].append({"role": "user", "content": mensaje})

    # Respuesta de GPT
    try:
        respuesta_gpt = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "system",
                "content": prompt_sistema
            }] + memoria[numero],
            tools=[{
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
            }],
            tool_choice="auto"
        )

        mensaje_gpt = respuesta_gpt.choices[0].message

        # Si GPT tiene todos los datos busca el precio en sheets y responde
        if mensaje_gpt.tool_calls:
            argumentos = json.loads(mensaje_gpt.tool_calls[0].function.arguments)
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
                    f"Puedes venir sin necesidad de cita y te atendemos al instante 🏎️ 💨"
                )
                memoria[numero] = []  # Borra historial después de cotizar
            else:
                final = "No encontré ese vehículo en mi base de datos 🚗. Un asesor te ayudará pronto 👨‍🔧"
                memoria[numero] = []
        else:
            final = mensaje_gpt.content
            memoria[numero].append({"role": "assistant", "content": final})

    except Exception as e:
        print("Error:", e)
        final = "Tuvimos un problema con tu mensaje. Intenta más tarde o espera a que un asesor te apoye 😊"
        memoria[numero] = []

    # Envía la respuesta usando Conversations API para que se vea en Flex
    if conversation_sid:
        twilio_client.conversations.v1.conversations(conversation_sid).messages.create(
            body=final
        )
    else:
        print("No se recibió ConversationSid, no se pudo enviar respuesta con Conversations API")

    return "OK", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
