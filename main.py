from flask import Flask, request
import openai
import os
import gspread
import json
from oauth2client.service_account import ServiceAccountCredentials
from urllib.parse import parse_qs

app = Flask(__name__)

# Configura OpenAI
client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# Prompt base
prompt_sistema = """
Eres un asistente de WhatsApp para el taller Uribe Speed Tune Up. Solo puedes responder si el cliente pregunta por:

1. El precio del cambio de aceite (según año, marca, modelo y cilindros del auto)
2. Los horarios del taller
3. Las ubicaciones del taller
4. Qué incluye un servicio como afinación, cambio de balatas o anticongelante

Si el cliente no da todos los datos necesarios para el cambio de aceite (año, marca, modelo y cilindros), pídele los que falten dando seguimiento a la conversacion.

Si pregunta algo fuera de esos temas, responde:
"Un asesor te responderá en un momento para darte más información sobre eso."

Siempre responde en español, de manera clara, amable y humana. Puedes utilizar emojis para hacer mas atractivo el mensaje.

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


def buscar_precio(a, m, mo, c):
    for row in rows:
        
        if (str(row['AÑO']).strip() == a and row['MARCA'].strip().lower() == m
                and row['MODELO'].strip().lower() == mo
                and str(row['CILINDROS']).strip() == c):
            sint = row.get('ACEITE SINTETICO PRECIO', 'No disponible')
            semi = row.get('ACEITE SEMISINTETICO PRECIO', 'No disponible')
            return sint, semi
    return None, None


@app.route('/webhook', methods=['POST'])
def webhook():
    req = request.form.to_dict()
    print("Datos recibidos:", req)

    # Si llega todo junto en un solo campo 'body', parsear manualmente
    if 'body' in req and ('Body' not in req or 'From' not in req):
        parsed = parse_qs(req['body'])
        req['Body'] = parsed.get('Body', [''])[0]
        req['From'] = parsed.get('From', [''])[0]

    print("Datos corregidos:", {
        'Body': req.get('Body'),
        'From': req.get('From')
    })

    mensaje = req.get('Body', '')
    numero = req.get('From', '')

    if numero not in memoria:
        memoria[numero] = []

    memoria[numero].append({"role": "user", "content": mensaje})

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
                    "description":
                    "Busca el precio del cambio de aceite en Google Sheets",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "año": {
                                "type": "string"
                            },
                            "marca": {
                                "type": "string"
                            },
                            "modelo": {
                                "type": "string"
                            },
                            "cilindros": {
                                "type": "string"
                            }
                        },
                        "required": ["año", "marca", "modelo", "cilindros"]
                    }
                }
            }],
            tool_choice="auto")

        mensaje_gpt = respuesta_gpt.choices[0].message

        if mensaje_gpt.tool_calls:
            argumentos = json.loads(
                mensaje_gpt.tool_calls[0].function.arguments)
            sint, semi = buscar_precio(argumentos['año'],
                                       argumentos['marca'].lower(),
                                       argumentos['modelo'].lower(),
                                       argumentos['cilindros'])
            if sint and semi:
                final = (
                    f"El cambio de aceite para tu {argumentos['marca'].title()} {argumentos['modelo'].title()} {argumentos['año']} "
                    f"({argumentos['cilindros']} cilindros) cuesta:\n"
                    f"- Aceite sintético: {sint}\n"
                    f"- Aceite semisintético: {semi}")
                memoria[numero] = []  # Borra historial después de cotizar
            else:
                final = "No encontré ese vehículo en mi base de datos. Un asesor te ayudará pronto."
                memoria[numero] = []
        else:
            final = mensaje_gpt.content
            memoria[numero].append({"role": "assistant", "content": final})

    except Exception as e:
        print("Error:", e)
        final = "Hubo un error al procesar tu mensaje. Intenta más tarde."
        memoria[numero] = []

    respuesta = json.dumps({"body": final})
    print("Respuesta enviada a Twilio:", respuesta)
    return respuesta, 200, {'Content-Type': 'application/json'}


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
