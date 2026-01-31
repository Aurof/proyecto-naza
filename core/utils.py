# core/utils.py
import google.generativeai as genai
from django.conf import settings
from google.cloud import texttospeech, speech
import os
from datetime import timedelta
from django.utils import timezone
from .models import ProgresoUsuario
from io import BytesIO
from django.http import HttpResponse
from django.template.loader import get_template
from xhtml2pdf import pisa
import json
import logging

logger = logging.getLogger('core')

# Configuración de Gemini (usando tu API Key)
# Asegúrate de poner tu API Key en settings.py como GEMINI_API_KEY
genai.configure(api_key=settings.GEMINI_API_KEY)



def texto_a_voz_bytes(texto, voice_code='es-US-Wavenet-A'):
    """Convierte texto a audio MP3 (bytes) usando Google Cloud"""
    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=texto)
    
    # Configuración de voz
    lang_code = "-".join(voice_code.split("-")[:2])
    voice = texttospeech.VoiceSelectionParams(language_code=lang_code, name=voice_code, ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL)
    audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)

    response = client.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)
    return response.audio_content

def actualizar_progreso(user):
    """
    Calcula XP, subida de nivel y rachas.
    Retorna un diccionario con los cambios para notificar al frontend.
    """
    progreso, created = ProgresoUsuario.objects.get_or_create(usuario=user)
    hoy = timezone.now().date()
    ayer = hoy - timedelta(days=1)
    
    eventos = {
        'subio_nivel': False,
        'racha_aumentada': False,
        'xp_ganada': 10 # 10 puntos por mensaje
    }

    # 1. Lógica de Rachas (Solo se actualiza una vez al día)
    if progreso.ultima_interaccion < hoy:
        if progreso.ultima_interaccion == ayer:
            # Si practicó ayer, aumenta racha
            progreso.racha_actual += 1
            eventos['racha_aumentada'] = True
        elif progreso.ultima_interaccion < ayer and not created:
            # Si dejó pasar días, reinicia a 1
            progreso.racha_actual = 1
        else:
            # Primera vez hoy (o usuario nuevo)
            if progreso.racha_actual == 0: progreso.racha_actual = 1
            
        progreso.ultima_interaccion = hoy

    # 2. Lógica de XP y Niveles
    # Fórmula simple: Cada 100 XP subes de nivel
    progreso.experiencia += eventos['xp_ganada']
    nuevo_nivel = (progreso.experiencia // 100) + 1
    
    if nuevo_nivel > progreso.nivel:
        progreso.nivel = nuevo_nivel
        eventos['subio_nivel'] = True
    
    progreso.save()
    
    # Añadimos el estado actual para mostrarlo
    eventos['nivel_actual'] = progreso.nivel
    eventos['xp_actual'] = progreso.experiencia
    eventos['racha_actual'] = progreso.racha_actual
    
    return eventos

def render_to_pdf(template_src, context_dict={}):
    """
    Función auxiliar para convertir un template HTML a PDF
    """
    template = get_template(template_src)
    html  = template.render(context_dict)
    result = BytesIO()
    
    # Generar el PDF
    pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), result)
    
    if not pdf.err:
        return HttpResponse(result.getvalue(), content_type='application/pdf')
    return None

def obtener_respuesta_gemini(historial_chat, texto_usuario, idioma_detectado='es-ES', scenario='general', confidence=1.0):
    """
    Cerebro con Soporte de Roleplay.
    scenario: 'general', 'cafe', 'airport', 'interview', 'doctor'
    Ahora recibe 'confidence'. Si es bajo (< 0.75), genera un tip de pronunciación.
    """
    
    # 1. DICCIONARIO DE ROLES
    roles = {
        'general': "Eres Naza, un amigo y tutor de inglés experto. Habla de cualquier tema.",
        
        'cafe': """
        ACTÚA COMO: Un mesero impaciente en una cafetería ocupada de Londres.
        TU OBJETIVO: Tomar la orden del cliente (el usuario).
        CONTEXTO: Es por la mañana, hay mucho ruido.
        NO te salgas del personaje. Si el usuario habla de otra cosa, vuelve al tema del café.
        """,
        
        'airport': """
        ACTÚA COMO: Un oficial de inmigración estricto en el aeropuerto JFK de Nueva York.
        TU OBJETIVO: Decidir si dejas entrar al usuario al país.
        PREGUNTAS CLAVE: ¿Propósito del viaje? ¿Cuánto tiempo se queda? ¿Dónde se aloja?
        Sé formal y serio.
        """,
        
        'interview': """
        ACTÚA COMO: Un reclutador de Google haciendo una entrevista de trabajo.
        TU OBJETIVO: Evaluar las habilidades blandas del candidato.
        Pregunta sobre sus fortalezas, debilidades y por qué quiere el trabajo.
        """,
        
        'doctor': """
        ACTÚA COMO: Un doctor amable en una clínica.
        TU OBJETIVO: Diagnosticar qué le duele al paciente.
        Pregunta síntomas, desde cuándo le duele, etc.
        """
    }

    personalidad_seleccionada = roles.get(scenario, roles['general'])

    # Configuración del modelo
    generation_config = {
        "temperature": 0.7,
        "top_p": 0.95,
        "top_k": 40,
        "max_output_tokens": 4096, # Aumentado de 1024 para evitar cortes en JSON largos
        "response_mime_type": "application/json",
    }
    
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        generation_config=generation_config,
    )

    # ... (Prompt construction remains the same) ...

    # INSTRUCCIÓN EXTRA PARA PRONUNCIACIÓN
    instruccion_pronunciacion = ""
    if confidence < 0.90:
        instruccion_pronunciacion = """
        ¡ATENCIÓN! El sistema de reconocimiento de voz tuvo dificultades para entender al usuario (Confianza baja).
        Esto indica una MALA PRONUNCIACIÓN o una frase mal interpretada por el STT.
        
        ACCIÓN REQUERIDA:
        1. Identifica la palabra o frase más difícil de lo que dijo el usuario.
        2. Intenta deducir qué QUISO DECIR el usuario basándote en la fonética y el contexto.
           Ejemplo: Si el texto es "I want to dream coffee", probablemente quiso decir "I want to drink coffee".
        3. En el campo JSON 'texto_corregido_fonetico', pon esa frase corregida (lo que debió ser).
        4. En el campo JSON 'tip_pronunciacion', escribe el consejo fonético. ¡ES OBLIGATORIO!
        5. Sé amable, no regañes.
        IMPORTANTE: Si la confianza es baja, el campo 'tip_pronunciacion' NO PUEDE SER NULL. Debes generar un consejo.
        """

    # --- PROMPT MAESTRO ACTUALIZADO ---
    system_prompt = f"""
    {personalidad_seleccionada}
    
    CONTEXTO TÉCNICO:
    - El usuario es hablante nativo de ESPAÑOL aprendiendo INGLÉS.
    - El usuario te habló en: {idioma_detectado}.
    - Calidad de audio/pronunciación (0-1): {confidence}.
    
    {instruccion_pronunciacion}
    
    REGLAS DE INTERACCIÓN (IMPORTANTE):
    1. Mantén SIEMPRE tu personaje ({scenario}).
    2. Responde en INGLÉS (salvo que el usuario esté muy perdido en Español).
    3. CORRECCIONES:
       - Aunque actúes como mesero/policía, sigues siendo un tutor en el fondo.
       - Si el usuario comete un error gramatical grave, llena los campos JSON de 'correccion' y 'explicacion' (en Español).
       - PERO tu 'respuesta_bot' (audio) debe seguir en personaje en Inglés, ignorando el error para no romper la inmersión.
       
    4. IMPORTANTE: NO USES EMOJIS NUNCA. El sistema de Texto-a-Voz los lee y arruina la experiencia.

    FORMATO DE RESPUESTA JSON (Estricto):
    {{
        "respuesta_bot": "Texto hablado por el personaje",
        "idioma_respuesta": "en-US",
        "hay_error": true/false,
        "texto_original": "...",
        "correccion": "...",
        "explicacion": "Explicación breve en ESPAÑOL",
        "tip_pronunciacion": "Consejo fonético (o null)",
        "texto_corregido_fonetico": "La frase que el usuario probablemente quiso decir (o null)"
    }}
    """
    
    # Construimos el mensaje para enviar
    chat_content = f"{system_prompt}\n\nUsuario dice: {texto_usuario}"
    
    try:
        response = model.generate_content(chat_content)
        cleaned_text = response.text.replace('```json', '').replace('```', '').strip()
        
        # INTENTO DE PARSEO SEGURO
        parsed_data = json.loads(cleaned_text)
        return parsed_data # Devolvemos directamente el DICT, no el string
        
    except json.JSONDecodeError:
        logger.error(f"Error JSON Gemini (Posible corte): {cleaned_text[:200]}...", exc_info=True)
        # Fallback si el JSON viene roto (ej. token limit)
        return {
            "respuesta_bot": "Sorry, I got cut off. Could you say that again?",
            "idioma_respuesta": "en-US",
            "hay_error": False,
            "tip_pronunciacion": None,
            "texto_corregido_fonetico": None
        }
    except Exception as e:
        logger.error(f"Error General Gemini API: {str(e)}", exc_info=True)
        return {
            "respuesta_bot": "Connection error. Please try again.",
            "idioma_respuesta": "en-US",
            "hay_error": False,
            "tip_pronunciacion": None,
            "texto_corregido_fonetico": None
        }