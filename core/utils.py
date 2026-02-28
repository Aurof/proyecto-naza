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
import threading

logger = logging.getLogger('core')

# --- SISTEMA DE ROTACIÓN DE API KEYS ---
_api_keys = getattr(settings, 'GEMINI_API_KEYS', []) or [settings.GEMINI_API_KEY]
_key_index = 0
_key_lock = threading.Lock()

def _get_next_api_key():
    """Round-robin: devuelve la siguiente API key disponible."""
    global _key_index
    with _key_lock:
        key = _api_keys[_key_index % len(_api_keys)]
        _key_index += 1
        logger.info(f"[API Key] Usando API Key #{(_key_index - 1) % len(_api_keys) + 1} de {len(_api_keys)}")
        return key

def _configure_genai(api_key):
    """Configura genai con una API key específica."""
    genai.configure(api_key=api_key)

# Configuración inicial con la primera key
_configure_genai(_api_keys[0])


def texto_a_voz_bytes(texto, voice_code='es-US-Wavenet-A', speaking_rate=1.0):
    """Convierte texto a audio MP3 (bytes) usando Google Cloud"""
    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=texto)
    
    # Configuración de voz
    lang_code = "-".join(voice_code.split("-")[:2])
    voice = texttospeech.VoiceSelectionParams(language_code=lang_code, name=voice_code)
    
    # Configuración de audio (Incluyendo velocidad)
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=speaking_rate
    )

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
    pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), result, encoding='UTF-8')
    
    if not pdf.err:
        return HttpResponse(result.getvalue(), content_type='application/pdf')
    return None

def obtener_respuesta_gemini(historial_chat, texto_usuario, idioma_detectado='es-ES', scenario='general', confidence=1.0, user_facts=[], idioma_nativo='Español', idioma_objetivo='Inglés'):
    """
    Cerebro con Soporte de Roleplay, MEMORIA A LARGO PLAZO y MULTILENGUAJE DINÁMICO.
    """
    
    # 1. DICCIONARIO DE ROLES
    roles = {
        'general': f"""
        ERES: Naza, un amigo cercano, curioso y conversador. 
        TU OBJETIVO: Mantener la conversación viva y ayudar al usuario a practicar {idioma_objetivo} hablando de temas interesantes.
        ESTILO: Amigable, casual, empático y PROACTIVO.
        CLAVE: Siempre termina tus respuestas con una PREGUNTA relacionada para obligar al usuario a seguir hablando.
        Si el usuario da respuestas cortas, saca un tema nuevo (viajes, comida, futuro, hobbies).
        NO actúes como un profesor aburrido. Sé un compañero de charla genial.
        """,
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
        "max_output_tokens": 4096, 
        "response_mime_type": "application/json",
    }
    
    # INSTRUCCIÓN EXTRA PARA PRONUNCIACIÓN
    instruccion_pronunciacion = ""
    if confidence < 0.85:
        instruccion_pronunciacion = f"""
        ¡ATENCIÓN! El sistema de reconocimiento de voz reporta confianza media/baja ({confidence}).
        
        ACCIÓN REQUERIDA PARA PRONUNCIACIÓN (MANDATORIO):
        1. EL CAMPO 'tip_pronunciacion' NO PUEDE SER NULL. DEBES GENERARLO.
        2. Tu prioridad es DETECTAR la palabra que el usuario INTENTÓ decir. Adivínala por el contexto fonético.
        3. ASUME SIEMPRE que hubo un error de articulación del usuario, NO asumas ruido.
        4. GENERA un consejo TÉCNICO sobre cómo poner la boca/lengua para esa palabra adivinada.
           - Ejemplo: "Tu 'Drink' sonó como 'Dreenk'. Acorta la 'i' y marca la 'k' final fuerte."
        5. IMPORTANTE: Aunque no estés 100% seguro, MEJOR DAR UN CONSEJO SOBRE LA PALABRA MÁS PROBABLE QUE NO DECIR NADA.
        """

    # --- INYECCIÓN DE MEMORIA A LARGO PLAZO ---
    contexto_memoria = ""
    if user_facts:
        lista_hechos = "\n    - ".join(user_facts)
        contexto_memoria = f"""
        LO QUE YA SABES DEL USUARIO (Memoria a Largo Plazo):
        - {lista_hechos}
        
        ¡Usa esta información para personalizar tu respuesta! Pregunta sobre esto si viene al caso.
        """

    # --- PROMPT MAESTRO ACTUALIZADO ---
    system_prompt = f"""
    {personalidad_seleccionada}
    
    {contexto_memoria}
    
    CONTEXTO TÉCNICO:
    - El usuario es hablante nativo de {idioma_nativo} aprendiendo {idioma_objetivo}.
    - El usuario te habló en: {idioma_detectado}.
    - Calidad de audio/pronunciación (0-1): {confidence}.
    
    {instruccion_pronunciacion}
    
    REGLAS DE INTERACCIÓN (IMPORTANTE):
    1. Mantén SIEMPRE tu personaje ({scenario}).
    
    2. IDIOMA DE RESPUESTA (IMPORTANTE - NO NEGOCIABLE):
       - SIEMPRE responde en {idioma_objetivo}. Este es el idioma que el usuario está aprendiendo.
       - Si el usuario te habla en {idioma_nativo}, respóndele en {idioma_objetivo} de todas formas.
       - Usa {idioma_nativo} ÚNICAMENTE para: correcciones gramaticales ('correccion', 'explicacion'), consejos de pronunciación ('tip_pronunciacion'), y respuestas a preguntas meta-lingüísticas ("¿cómo se dice X?").
       - NUNCA respondas en {idioma_nativo} como lengua principal de la conversación.
       - Si mezcla idiomas: responde en {idioma_objetivo} de todas formas.
       
    3. DINÁMICA DE CONVERSACIÓN:
       - Tus respuestas deben ser naturales, no enciclopédicas.
       - ¡IMPORTANTE! SIEMPRE termina tu turno con una pregunta abierta para el usuario.
       - Si el tema decae, propón uno nuevo de inmediato.
    4. CORRECCIONES:
       - Si el usuario intenta hablar {idioma_objetivo} y comete errores, corrígelo amablemente.

    5. PERSONALIDAD DE VOZ (IMPORTANTE):
       - Genera el campo 'respuesta_audio' con un tono MUY natural y humano.
       - Usa "fillers" y vacilaciones propias de {idioma_objetivo} (el idioma de la conversación).
       - Ejemplos (Inglés): "Um...", "Well...", "You know...", "I mean...", "Oh my gosh!".
       - Ejemplos (Francés): "Euh...", "Bon...", "Tu vois...", "Eh bien..."
       - Ejemplos (Alemán): "Äh...", "Also...", "Na ja...", "Weißt du..."
       - NO exageres, pero que no suene a robot leyendo un guion.
       - MANTÉN 'respuesta_bot' LIMPIO para leer.

    6. MODO PREGUNTA/RESPUESTA (META-APRENDIZAJE):
       - Si el usuario pregunta "¿Cómo se dice X?" o "¿Qué significa Y?":
         - El 'respuesta_bot' responde brevemente EN {idioma_objetivo} (da el término/frase en el idioma objetivo).
         - Usa el campo 'explicacion' para dar la explicación clara en {idioma_nativo}.
         - Da siempre un ejemplo en contexto en {idioma_objetivo}.

    7. CORRECCIONES:
       - Si el usuario intenta hablar en {idioma_objetivo} y comete errores, corrígelo amablemente.
       - Los campos 'correccion' y 'explicacion' deben estar SIEMPRE en {idioma_nativo}.
       - Si 'tip_pronunciacion' está activo, 'correccion' = versión gramaticalmente perfecta de lo que intentó decir.
       
    5. IMPORTANTE: NO USES EMOJIS NUNCA. El sistema de Texto-a-Voz los lee y arruina la experiencia.
    
    6. MEMORIA (Long Term Memory):
       - Si el usuario menciona CUALQUIER dato personal (Nombre, Profesión, Hobbies, Gustos, Mascotas, Familia), EXTRÁELO.
       - Ejemplo: "Me gusta la pizza con piña" -> Guardar: "Le gusta la pizza con piña".
       - Ejemplo: "Soy Víctor" -> Guardar: "Se llama Víctor".
       - Añádelo a la lista 'nuevos_datos_aprendidos' en el JSON.
       - NO guardes cosas temporales como "tengo hambre ahora", pero SÍ preferencias permanentes.

    7. VOCABULARIO (SRS):
        - Extrae 1-3 palabras o frases CLAVE que hayas usado en tu respuesta y que sean útiles para el usuario (Nivel {idioma_objetivo}).
        - Campo 'nuevas_palabras': [
            {{ "palabra": "Bonjour", "traduccion": "Hola", "ejemplo": "Bonjour, comment ça va?" }}
        ]

    8. AUDITORÍA DE SEGURIDAD (NUEVO):
       - Analiza el input del USUARIO.
       - Detecta si es: TOXIC, SEXUALLY_EXPLICIT, HATE_SPEECH, HARASSMENT o SAFE.
       - Asigna un valor de confianza (0.0 a 1.0) de que sea dañino.

    FORMATO DE RESPUESTA JSON (Estricto):
    {{
        "respuesta_bot": "Texto limpio para LEER (sin muletillas)",
        "respuesta_audio": "Texto para HABLAR (Con 'um', 'eh', repeticiones naturales y calidez)", 
        "idioma_respuesta": "Código ISO estándar (en-US, es-ES, fr-FR, etc.)",
        "hay_error": true/false,
        "texto_original": "...",
        "correccion": "...",
        "explicacion": "Explicación breve en {idioma_nativo}",
        "tip_pronunciacion": "Consejo fonético EN {idioma_nativo} (o null)",
        "texto_corregido_fonetico": "...",
        "nuevos_datos_aprendidos": [],
        "nuevas_palabras": [],
        "auditoria": {{
            "es_toxico": true/false,
            "categoria": "SAFE/SEXUAL/HATE/TOXIC",
            "confianza": 0.0
        }}
    }}
    """
    
    # 2. Configurar Modelo con ROTACIÓN DE API KEYS
    last_error = None
    for attempt in range(len(_api_keys)):
        api_key = _get_next_api_key()
        _configure_genai(api_key)
        
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            generation_config=generation_config,
            system_instruction=system_prompt
        )

        try:
            # 3. Iniciar Chat con Historial (Memoria)
            chat_session = model.start_chat(history=historial_chat)
            
            # 4. Enviar MENSAJE ACTUAL
            response = chat_session.send_message(texto_usuario)
            
            cleaned_text = response.text.replace('```json', '').replace('```', '').strip()
            
            # INTENTO DE PARSEO SEGURO
            parsed_data = json.loads(cleaned_text)
            return parsed_data
            
        except json.JSONDecodeError:
            logger.error(f"Error JSON Gemini (Key #{attempt+1}): {cleaned_text[:200]}...", exc_info=True)
            return {
                "respuesta_bot": "Sorry, I got cut off. Could you say that again?",
                "idioma_respuesta": "en-US",
                "hay_error": False,
                "tip_pronunciacion": None,
                "texto_corregido_fonetico": None
            }
        except Exception as e:
            last_error = str(e)
            logger.warning(f"⚠️ API Key #{attempt+1} falló: {last_error}. Intentando siguiente key...")
            continue  # Intentar con la siguiente key
    
    # Si todas las keys fallaron
    logger.error(f"❌ Todas las API keys fallaron. Último error: {last_error}")
    return {
        "respuesta_bot": f"Error: Todas las API keys están agotadas. Último error: {last_error}",
        "idioma_respuesta": "en-US",
        "hay_error": False,
        "tip_pronunciacion": None,
        "texto_corregido_fonetico": None
    }


def generar_quiz_gemini(mensajes_texto, idioma_objetivo, idioma_nativo='Español', num_preguntas=8):
    """
    Genera un quiz de selección simple basado en las conversaciones del usuario.
    Retorna una lista de preguntas con opciones y respuesta correcta.
    """
    generation_config = {
        "temperature": 0.8,
        "top_p": 0.95,
        "top_k": 40,
        "max_output_tokens": 4096,
        "response_mime_type": "application/json",
    }

    # Construir contexto de conversaciones
    contexto_conversaciones = "\n".join(mensajes_texto[:100])  # Máx 100 mensajes

    system_prompt = f"""
    Eres un generador de quizzes educativos para aprendizaje de idiomas.
    
    CONTEXTO:
    - El usuario habla {idioma_nativo} y está aprendiendo {idioma_objetivo}.
    - A continuación tienes fragmentos de sus conversaciones recientes de práctica.
    - Usa las conversaciones SOLO para extraer vocabulario, estructuras gramaticales y conjugaciones que el usuario practicó.
    
    CONVERSACIONES DEL USUARIO:
    {contexto_conversaciones}
    
    REGLAS PARA GENERAR EL QUIZ:
    1. Las preguntas deben evaluar HABILIDADES LINGÜÍSTICAS: vocabulario, gramática, conjugación y traducción.
    2. NUNCA hagas preguntas sobre preferencias, opiniones u datos personales del usuario (ej: "¿qué bebida prefiere?", "¿a dónde viajó?").
    3. NUNCA hagas preguntas de trivia o comprensión sobre el contenido de las conversaciones.
    4. Cada pregunta tiene EXACTAMENTE 4 opciones (A, B, C, D).
    5. Solo UNA opción es correcta.
    6. Las preguntas deben estar escritas en {idioma_nativo} (para que el usuario las entienda).
    7. Las opciones pueden estar en {idioma_objetivo} si es una pregunta de traducción/vocabulario.
    8. La explicación debe ser clara y educativa, en {idioma_nativo}.
    9. Genera EXACTAMENTE {num_preguntas} preguntas.
    10. Las preguntas deben ir de fácil a difícil.
    11. NO repitas el mismo tipo de pregunta consecutivamente.
    12. Varía los tipos de pregunta para cubrir diferentes habilidades.
    
    TIPOS DE PREGUNTAS PERMITIDOS:
    - "¿Cómo se dice [palabra/{idioma_nativo}] en {idioma_objetivo}?" (Vocabulario)
    - "¿Qué significa '[palabra en {idioma_objetivo}]' en {idioma_nativo}?" (Vocabulario)
    - "¿Cuál es la conjugación correcta de [verbo] en [tiempo verbal]?" (Conjugación)
    - "Completa la oración: 'I ___ to the store yesterday'" (Gramática)
    - "¿Cuál de estas oraciones es gramaticalmente correcta?" (Gramática)
    - "¿Cuál es el sinónimo/antónimo de [palabra]?" (Vocabulario)
    - "Elige la preposición correcta: 'She arrived ___ the airport'" (Gramática)
    - "¿Cuál es el pasado participio de [verbo]?" (Conjugación)
    
    TIPOS DE PREGUNTAS PROHIBIDOS:
    - Preguntas sobre qué dijo el usuario o el bot en la conversación
    - Preguntas sobre preferencias, gustos o hábitos del usuario  
    - Preguntas de comprensión lectora sobre el contenido de los chats
    - Cualquier pregunta cuya respuesta dependa de información personal
    
    FORMATO DE RESPUESTA JSON (Estricto):
    {{
        "titulo": "Quiz descriptivo corto (máx 50 chars)",
        "preguntas": [
            {{
                "numero": 1,
                "pregunta": "Texto de la pregunta",
                "opciones": ["Opción A", "Opción B", "Opción C", "Opción D"],
                "respuesta_correcta": 0,
                "explicacion": "Por qué esta es la respuesta correcta...",
                "categoria": "vocabulario"
            }}
        ]
    }}
    
    IMPORTANTE: respuesta_correcta es el ÍNDICE (0=A, 1=B, 2=C, 3=D).
    IMPORTANTE: categoria debe ser uno de: "vocabulario", "gramatica", "conjugacion".
    """

    last_error = None
    for attempt in range(len(_api_keys)):
        api_key = _get_next_api_key()
        _configure_genai(api_key)

        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            generation_config=generation_config,
            system_instruction=system_prompt
        )

        try:
            response = model.generate_content(
                f"Genera un quiz de {num_preguntas} preguntas basado en las conversaciones proporcionadas."
            )
            
            cleaned_text = response.text.replace('```json', '').replace('```', '').strip()
            parsed_data = json.loads(cleaned_text)
            return parsed_data

        except json.JSONDecodeError as e:
            logger.error(f"Error JSON Quiz Gemini (Key #{attempt+1}): {e}", exc_info=True)
            return None
        except Exception as e:
            last_error = str(e)
            logger.warning(f"[Warning] Quiz API Key #{attempt+1} fallo: {last_error}. Intentando siguiente key...")
            continue
    
    logger.error(f"[Error] Todas las API keys fallaron para Quiz. Ultimo error: {last_error}")
    return None