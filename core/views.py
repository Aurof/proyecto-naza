# core/views.py

import json
import base64
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.core.mail import send_mail # <--- Importante
from django.conf import settings # <--- FIXED
import random # <--- Importante
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from google.cloud import texttospeech, speech
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.models import User
from django.db.models import Q, Exists, OuterRef
from .models import AlertaSistema
from .utils import render_to_pdf, generar_quiz_gemini
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth import logout
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404
from django.contrib import messages

# Importamos nuestros modelos y formularios
from .models import Conversacion, Mensaje, RegistroError, ConfiguracionVoz, ProgresoUsuario, ErrorPronunciacion, Vocabulario
from .forms import RegistroForm
# Importamos la lógica de IA
from .utils import obtener_respuesta_gemini, texto_a_voz_bytes, actualizar_progreso


# ---------------------------------------------------------
# SECCIÓN 1: AUTENTICACIÓN Y VISTAS PRINCIPALES
# ---------------------------------------------------------



def landing(request):
    """
    Página de inicio. 
    Nota: Quitamos la redirección automática para que el usuario logueado 
    pueda ver la landing, pero los botones HTML ahora serán inteligentes.
    """
    return render(request, 'core/landing.html')

def register(request):
    if request.method == 'POST':
        form = RegistroForm(request.POST)
        if form.is_valid():
            user = form.save()
            
            # --- NUEVA LÓGICA DE VERIFICACIÓN ---
            # 1. Generar código
            codigo = str(random.randint(100000, 999999))
            
            # 2. Guardar en perfil (ProgresoUsuario)
            progreso, _ = ProgresoUsuario.objects.get_or_create(usuario=user)
            progreso.codigo_verificacion = codigo
            progreso.cuenta_verificada = False
            progreso.save()
            
            # 3. Enviar Correo
            asunto = "Verifica tu cuenta en Naza Bot"
            # Renderizamos HTML
            from django.template.loader import render_to_string
            html_message = render_to_string('core/email_verification.html', {
                'user': user,
                'codigo': codigo
            })
            plain_message = f"Tu código de verificación es: {codigo}"
            
            try:
                send_mail(
                    asunto, 
                    plain_message, 
                    settings.EMAIL_HOST_USER, 
                    [user.email], 
                    html_message=html_message # <--- HTML
                )
            except Exception as e:
                print(f"Error enviando correo: {e}")
                # Podríamos mostrar un error, pero dejamos pasar por ahora para no bloquear
            
            # 4. Redirigir a verificación (NO LOGUEAR AÚN)
            request.session['verification_user_id'] = user.id # Guardamos ID temporalmente
            return redirect('verify_email')
            
    else:
        form = RegistroForm()
    return render(request, 'core/register.html', {'form': form})

def verify_email(request):
    """Vista para validar el código"""
    if request.method == 'POST':
        codigo_ingresado = request.POST.get('codigo')
        user_id = request.session.get('verification_user_id')
        
        if not user_id:
            return redirect('login')
            
        user = get_object_or_404(User, id=user_id)
        progreso = user.progresousuario
        
        if codigo_ingresado == progreso.codigo_verificacion:
            # ¡ÉXITO!
            progreso.cuenta_verificada = True
            progreso.codigo_verificacion = None # Limpiamos por seguridad
            progreso.save()
            
            # Logueamos al usuario
            login(request, user)
            del request.session['verification_user_id'] # Limpiamos sesión
            
            return redirect('home')
        else:
            return render(request, 'core/verify_email.html', {'error': 'Código incorrecto', 'email': user.email})
            
    # GET: Mostrar formulario
    user_id = request.session.get('verification_user_id')
    if not user_id:
        return redirect('login')
    
    user = User.objects.get(id=user_id)
    return render(request, 'core/verify_email.html', {'email': user.email})

def resend_verification_code(request):
    """Reenvía el código de verificación al usuario en sesión"""
    user_id = request.session.get('verification_user_id')
    if not user_id:
        messages.error(request, "Sesión expirada. Por favor regístrate nuevamente.")
        return redirect('register')
    
    user = get_object_or_404(User, id=user_id)
    progreso = user.progresousuario
    
    # Reutilizamos el código existente o generamos uno nuevo si se prefiere
    if not progreso.codigo_verificacion:
         progreso.codigo_verificacion = str(random.randint(100000, 999999))
         progreso.save()
    
    codigo = progreso.codigo_verificacion

    # Enviar Correo
    asunto = "Tu código de verificación - Naza Bot"
    # Renderizamos HTML
    from django.template.loader import render_to_string
    html_message = render_to_string('core/email_verification.html', {
        'user': user,
        'codigo': codigo
    })
    plain_message = f"Tu código de verificación es: {codigo}"

    try:
        # LOGGING DE DEPURACIÓN (Temporal)
        with open('email_debug.log', 'a') as f:
            f.write(f"Intento de envío a: {user.email} con USER: {settings.EMAIL_HOST_USER}\n")
            
        send_mail(
            asunto, 
            plain_message, 
            settings.EMAIL_HOST_USER, 
            [user.email],
            html_message=html_message # <--- HTML
        )
        messages.success(request, f"¡Código reenviado a {user.email}!")
    except Exception as e:
        # LOGGING DE ERROR (Temporal)
        with open('email_debug.log', 'a') as f:
            f.write(f"ERROR enviando correo: {str(e)}\nConfiguración detectada: USER={settings.EMAIL_HOST_USER}, HOST={settings.EMAIL_HOST}\n")
            
        print(f"Error reenviando correo: {e}")
        messages.error(request, "Error enviando el correo. Intenta más tarde.")

    return redirect('verify_email')

@login_required
def home(request):
    # 1. Cargar conversaciones
    mis_conversaciones = Conversacion.objects.filter(usuario=request.user).order_by('-fecha_inicio')
    
    # 2. OBTENER EL PROGRESO (CRÍTICO)
    # Usamos get_or_create para que nunca sea None
    progreso, created = ProgresoUsuario.objects.get_or_create(usuario=request.user)

    # --- SEGURIDAD: VERIFICACIÓN DE CORREO OBLIGATORIA ---
    # EXCEPCIÓN: Si es admin (is_superuser) o staff, saltamos la verificación
    if not progreso.cuenta_verificada and not request.user.is_superuser and not request.user.is_staff:
        # Guardamos el ID en sesión para que la vista verify_email sepa a quién verificar
        request.session['verification_user_id'] = request.user.id
        return redirect('verify_email')

    # 3. Enviar al contexto
    context = {
        'chats': mis_conversaciones,
        'progreso': progreso  # <--- ¡ESTA VARIABLE ES LA CLAVE!
    }
    return render(request, 'core/chat.html', context)
# ---------------------------------------------------------
# SECCIÓN 2: LÓGICA DEL CHAT (CEREBRO)
# ---------------------------------------------------------

@login_required
def chat_interaction(request):
    """
    Controlador principal del Chat (Versión Final Tesis):
    - Soporte Bilingüe (Detección automática).
    - Soporte de Roleplay (Escenarios).
    - Voz Dinámica (Espejo de género).
    - Gamificación y Registro de Errores.
    """
    if request.method == 'POST':
        try:
            # 1. Decodificar datos del Frontend
            print(f"DEBUG: request.body type: {type(request.body)}")
            data = json.loads(request.body)
            print(f"DEBUG: data type after json.loads: {type(data)}")
            
            user_text = data.get('text')
            user = request.user
            
            # Recibimos el idioma detectado y el ESCENARIO (Roleplay)
            detected_lang = data.get('detected_lang', 'es-ES') 
            scenario = data.get('scenario', 'general') 
            confidence = data.get('confidence', 1.0) 
            
            # --- GESTIÓN DE CONVERSACIÓN ---
            conversation_id = data.get('conversation_id')
            conversacion = None
            
            # Buscar conversación existente
            if conversation_id:
                conversacion = Conversacion.objects.filter(id_conversacion=conversation_id, usuario=user).first()
            
            # Si no existe, crear nueva
            if not conversacion:
                titulo_chat = f"Rol: {scenario.capitalize()}" if scenario != 'general' else f"{user_text[:20]}..."
                conversacion = Conversacion.objects.create(
                    usuario=user,
                    titulo=titulo_chat,
                    idioma_actual='es-en'
                )

            # Guardar el mensaje del Usuario
            mensaje_usuario = Mensaje.objects.create(conversacion=conversacion, rol='usuario', contenido_texto=user_text)

            # --- MEMORIA A CORTO PLAZO (NUEVO) ---
            # Recuperar últimos 30 mensajes (suficiente para una conversación larga sin romper contexto)
            # Gemini 1.5 Flash tiene 1M de tokens, así que 30 mensajes es muy seguro y rápido.
            mensajes_db = Mensaje.objects.filter(conversacion=conversacion).order_by('-timestamp')[1:31] # Saltamos el 0 (actual)
            mensajes_db = reversed(mensajes_db) # Poner en orden cronológico
            
            historial_gemini = []
            for m in mensajes_db:
                role = 'user' if m.rol == 'usuario' else 'model'
                historial_gemini.append({'role': role, 'parts': [m.contenido_texto]})
            
            print(f"DEBUG MEMORY: Sending {len(historial_gemini)} methods of context.")

            # --- MEMORIA A LARGO PLAZO (USER FACTS) ---
            # 1. Recuperar hechos conocidos extraidos de UserFacts
            # (Se importó UserFact arriba? Asegurarse de importar)
            from .models import UserFact # Importación local para evitar líos circulares si los hubiera
            hechos_db = UserFact.objects.filter(usuario=user).values_list('dato', flat=True)
            lista_hechos = list(hechos_db)

            # --- MULTILENGUAJE DINÁMICO ---
            # Recuperar configuración de idioma del usuario
            config_voz = ConfiguracionVoz.objects.filter(usuario=user).first()
            idioma_nativo = config_voz.idioma_nativo if config_voz else 'Español'
            idioma_objetivo = config_voz.idioma_objetivo if config_voz else 'Inglés'

            # --- CEREBRO (GEMINI) ---
            print("DEBUG: Calling obtaining_respuesta_gemini...")
            gemini_data = obtener_respuesta_gemini(
                historial_gemini, 
                user_text, 
                detected_lang, 
                scenario, 
                confidence, 
                user_facts=lista_hechos,
                idioma_nativo=idioma_nativo,
                idioma_objetivo=idioma_objetivo
            )
            print(f"DEBUG: gemini_data type: {type(gemini_data)}")
            print(f"DEBUG: gemini_data: {gemini_data}")
            
            # --- AUDITORIA IA (NUEVO) ---
            if 'auditoria' in gemini_data:
                audit = gemini_data['auditoria']
                mensaje_usuario.es_toxico = audit.get('es_toxico', False)
                mensaje_usuario.categoria_seguridad = audit.get('categoria', 'SAFE')
                mensaje_usuario.confianza_seguridad = audit.get('confianza', 0.0)
                mensaje_usuario.save()
            
            # Si gemini_data es string (por alguna razón rara), intentamos parsear por seguridad
            if isinstance(gemini_data, str):
                print("DEBUG: gemini_data IS STRING! Parsing manually...")
                gemini_data = json.loads(gemini_data)
            
            # --- GUARDAR NUEVOS HECHOS APRENDIDOS ---
            nuevos_datos = gemini_data.get('nuevos_datos_aprendidos', [])
            if nuevos_datos:
                print(f"🧠 MEMORY: Learning new facts: {nuevos_datos}")
                for dato in nuevos_datos:
                    # Evitar duplicados exactos
                    if not UserFact.objects.filter(usuario=user, dato=dato).exists():
                        UserFact.objects.create(usuario=user, dato=dato)

            bot_text = gemini_data['respuesta_bot']
            # --- NUEVO: VOZ PERSONALIZADA ---
            # Usamos el texto con "fillers" para el audio, y el limpio para el chat
            audio_text = gemini_data.get('respuesta_audio', bot_text)
            
            idioma_respuesta = gemini_data.get('idioma_respuesta', 'es-ES')

            # Guardar mensaje del Bot (TEXTO LIMPIO)
            msg_bot = Mensaje.objects.create(conversacion=conversacion, rol='bot', contenido_texto=bot_text)
            
            # 4. GUARDAR ERRORES (GRAMATICALES Y PRONUNCIACIÓN)
            if gemini_data.get('hay_error') and gemini_data.get('correccion'):
                RegistroError.objects.create(
                    usuario=user,
                    mensaje=msg_bot,
                    texto_original=gemini_data.get('texto_original', user_text),
                    texto_corregido=gemini_data.get('correccion'),
                    explicacion_regla=gemini_data.get('explicacion')
                )
            
            # --- GUARDAR ERROR DE PRONUNCIACIÓN ---
            tip_pronunciacion = gemini_data.get('tip_pronunciacion')
            texto_corregido_fonetico = gemini_data.get('texto_corregido_fonetico')

            # --- SRS - GUARDAR VOCABULARIO ---
            nuevas_palabras = gemini_data.get('nuevas_palabras', [])
            if nuevas_palabras:
                try:
                    from .models import Vocabulario
                    for item in nuevas_palabras:
                        palabra = item.get('palabra')
                        traduccion = item.get('traduccion')
                        ejemplo = item.get('ejemplo')
                        
                        if palabra and traduccion:
                            existe = Vocabulario.objects.filter(usuario=user, palabra__iexact=palabra).exists()
                            if not existe:
                                Vocabulario.objects.create(
                                    usuario=user,
                                    palabra=palabra,
                                    traduccion=traduccion,
                                    ejemplo=ejemplo,
                                    nivel_dominio=0
                                )
                except Exception as e:
                    print(f"Error SRS Save: {e}")

            print(f"DEBUG PRONUNCIATION: Confidence={confidence}, Tip={tip_pronunciacion}")

            if tip_pronunciacion:
                 try:
                     nuevo_error = ErrorPronunciacion.objects.create(
                         usuario=user,
                         conversacion=conversacion,
                         texto_original=user_text,
                         texto_corregido_fonetico=texto_corregido_fonetico,
                         tip_fonetico=tip_pronunciacion,
                         confidence=confidence
                     )
                     print(f"DEBUG PRONUNCIATION: Saved Error ID {nuevo_error.id} for user {user.username}")
                 except Exception as e:
                     print(f"DEBUG PRONUNCIATION: ERROR SAVING TO DB: {e}")

            # --- VOZ DINÁMICA (SOPORTE MULTILENGUAJE MEJORADO) ---
            # --- VOZ DINÁMICA (SOPORTE MULTILENGUAJE MEJORADO) ---
            config_voz = ConfiguracionVoz.objects.filter(usuario=user).first()
            
            # 1. Obtener las voces configuradas por el usuario
            voz_target = config_voz.voice_code_tts if config_voz else 'en-US-Studio-O'
            voz_native = config_voz.voice_code_native_tts if config_voz else 'es-ES-Neural2-B'
            
            # 2. Detectar idioma de la respuesta (ISO code, ej: 'es-ES', 'en-US')
            lang_respuesta = idioma_respuesta.split('-')[0].lower() # 'es', 'en'
            
            # 3. Idiomas del usuario (Códigos aproximados)
            # Mapa simple basado en nombres de idioma en BD
            LANG_CODE_MAP = {
                'Inglés': 'en', 'Español': 'es', 'Francés': 'fr', 'Alemán': 'de', 
                'Italiano': 'it', 'Portugués': 'pt', 'Japonés': 'ja', 
                'Chino': 'zh', 'Ruso': 'ru'
            }
            
            user_native_lang = LANG_CODE_MAP.get(config_voz.idioma_nativo, 'es') if config_voz else 'es'
            user_target_lang = LANG_CODE_MAP.get(config_voz.idioma_objetivo, 'en') if config_voz else 'en'

            # 4. Selección de Voz Inteligente
            if lang_respuesta == user_native_lang:
                # Si Naza habla en tu idioma nativo -> Usa tu voz nativa de alta calidad
                voice_code = voz_native
            elif lang_respuesta == user_target_lang:
                 # Si Naza habla en el idioma que aprendes -> Usa la voz del tutor
                voice_code = voz_target
            else:
                # Fallback para terceros idiomas (ej: si aprendes Inglés pero pides una frase en Francés)
                if lang_respuesta == 'en': voice_code = 'en-US-Studio-O'
                elif lang_respuesta == 'es': voice_code = 'es-ES-Studio-C'
                elif lang_respuesta == 'fr': voice_code = 'fr-FR-Studio-A'
                elif lang_respuesta == 'de': voice_code = 'de-DE-Studio-C'
                elif lang_respuesta == 'it': voice_code = 'it-IT-Neural2-A'
                elif lang_respuesta == 'pt': voice_code = 'pt-BR-Neural2-A'
                elif lang_respuesta == 'ja': voice_code = 'ja-JP-Neural2-B'
                elif lang_respuesta == 'zh': voice_code = 'zh-CN-Wavenet-A'
                elif lang_respuesta == 'ru': voice_code = 'ru-RU-Wavenet-A'
                else: voice_code = voz_target # Último recurso 

            # Velocidad de voz
            speaking_rate = float(config_voz.velocidad) if config_voz else 1.0

            # Generar el audio (USA audio_text con fillers)
            try:
                audio_bytes = texto_a_voz_bytes(audio_text, voice_code, speaking_rate)
                audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
            except Exception as e:
                print(f"Error TTS Google: {e}")
                audio_base64 = ""


            # --- GAMIFICACIÓN ---
            datos_juego = actualizar_progreso(user)

            # --- RESPUESTA JSON ---
            return JsonResponse({
                'bot_text': bot_text,
                'audio_base64': audio_base64,
                'correccion': gemini_data.get('correccion') if gemini_data.get('hay_error') else None,
                'explicacion_regla': gemini_data.get('explicacion'),
                'tip_pronunciacion': tip_pronunciacion,
                'texto_corregido_fonetico': texto_corregido_fonetico, # <--- NUEVO CAMPO PARA UI
                'conversation_id': conversacion.id_conversacion,
                'conversation_title': conversacion.titulo,
                'conversation_date': conversacion.fecha_inicio.strftime('%Y-%m-%d %H:%M:%S'),
                'gamification': datos_juego
            })

        except Exception as e:
            print(f"Error CRÍTICO en Chat: {e}")
            # Devolvemos el error en JSON para que el frontend lo muestre (en vez de generic "Error de conexión")
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'POST required'}, status=405)
# ---------------------------------------------------------
# SECCIÓN 3: APIs DE GOOGLE CLOUD (STT y TTS)
# ---------------------------------------------------------

# Cliente STT global para reutilizar conexión (inicializado lazy)
stt_client = None

@csrf_exempt
def speech_to_text_api(request):
    """API para convertir audio del micrófono a texto"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Solo POST'}, status=405)

    global stt_client
    if stt_client is None:
        try:
            stt_client = speech.SpeechClient()
        except Exception as e:
            return JsonResponse({'error': f'STT init error: {str(e)}'}, status=500)

    try:
        data = json.loads(request.body)
        audio_base64 = data.get('audio_base64')
        language_code = data.get('language_code', 'es-ES')

        if not audio_base64:
            return JsonResponse({'error': 'Falta audio'}, status=400)

        audio_content = base64.b64decode(audio_base64)
        recognition_audio = speech.RecognitionAudio(content=audio_content)
        
        # --- CONFIGURACIÓN DINÁMICA DE IDIOMA (STT) ---
        # 1. Mapeo de nombres de idioma (BD) a Códigos Google (ISO)
        LANG_MAP = {
            'Español': 'es-ES', 'Inglés': 'en-US', 'Francés': 'fr-FR',
            'Alemán': 'de-DE', 'Italiano': 'it-IT', 'Portugués': 'pt-BR',
            'Japonés': 'ja-JP', 'Chino': 'zh-CN', 'Ruso': 'ru-RU'
        }

        # 2. Valores por defecto
        primary_lang = 'es-ES'
        alternative_langs = ['en-US']

        # 3. Intentar sacar la configuración real del usuario
        if request.user.is_authenticated:
            try:
                # Importación local para evitar ciclos si fuera necesario, aunque ya está arriba
                config_voz = ConfiguracionVoz.objects.filter(usuario=request.user).first()
                if config_voz:
                    # Prioridad 1: El idioma que quiere APRENDER (ej: Francés)
                    primary_lang = LANG_MAP.get(config_voz.idioma_objetivo, 'es-ES')
                    
                    # Prioridad 2: Su idioma nativo (ej: Español)
                    native_lang = LANG_MAP.get(config_voz.idioma_nativo, 'es-ES')
                    
                    # Construimos lista de alternatives (sin duplicados)
                    alts = set([native_lang, 'en-US', 'es-ES'])
                    if primary_lang in alts: alts.remove(primary_lang) # Quitar si ya es el primario
                    alternative_langs = list(alts)[:3] # Google permite máx 3
            except Exception as e:
                print(f"Error cargando config de voz usuario: {e}")

        # 4. Configurar Google Cloud STT
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.MP3,
            sample_rate_hertz=16000,
            language_code=primary_lang, # <--- ¡AHORA ES DINÁMICO! (ej: fr-FR)
            alternative_language_codes=alternative_langs, # <--- Escucha también en su idioma nativo
            enable_automatic_punctuation=True
        )

        # 2. Reconocimiento
        response = stt_client.recognize(config=config, audio=recognition_audio)

        transcript = ""
        detected_lang = "es-ES" # Por defecto
        confidence = 0.0

        if response.results:
            result = response.results[0]
            alternative = result.alternatives[0]
            
            transcript = alternative.transcript
            confidence = alternative.confidence
            
            # Google nos dice qué idioma detectó realmente
            if result.language_code:
                detected_lang = result.language_code

        print(f"🎤 STT DEBUG: Transcript='{transcript}' | Conf={confidence} | Lang={detected_lang}")

        # Devolvemos el texto Y el idioma detectado
        return JsonResponse({
            'transcript': transcript, 
            'detected_lang': detected_lang,
            'confidence': confidence
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def text_to_speech_api(request):
    """API para convertir texto a audio (usada para pruebas directas)"""
    # Esta función usa la utilidad que ya definimos en utils.py para no repetir código
    if request.method != 'POST':
        return JsonResponse({'error': 'Solo POST'}, status=405)
    try:
        data = json.loads(request.body)
        texto = data.get('text')
        voice_code = data.get('voice_code', 'es-US-Wavenet-A')
        
        if not texto:
            return JsonResponse({'error': 'Falta texto'}, status=400)

        audio_bytes = texto_a_voz_bytes(texto, voice_code)
        audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
        
        return JsonResponse({'audio_base64': audio_base64})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def get_conversation_detail(request, conversation_id):
    """API para obtener los mensajes de una conversación específica"""
    try:
        # 1. Buscamos la conversación y aseguramos que pertenezca al usuario
        conversacion = Conversacion.objects.get(id_conversacion=conversation_id, usuario=request.user)
        
        # 2. Obtenemos los mensajes ordenados cronológicamente
        mensajes = conversacion.mensajes.all().order_by('timestamp')
        
        # 3. Convertimos a datos simples (lista de diccionarios) para JSON
        mensajes_data = []
        for msg in mensajes:
            mensajes_data.append({
                'rol': msg.rol,
                'contenido': msg.contenido_texto,
                'audio_url': msg.audio_url # Por si guardamos audios en el futuro
            })
            
        # 4. Obtenemos los errores de esta conversación
        errores = RegistroError.objects.filter(mensaje__conversacion=conversacion).order_by('timestamp')
        errores_data = []
        for error in errores:
            errores_data.append({
                'original': error.texto_original,
                'corregido': error.texto_corregido,
                'explicacion': error.explicacion_regla,
                'fecha': error.timestamp.strftime("%H:%M")
            })

        return JsonResponse({'mensajes': mensajes_data, 'errores': errores_data, 'titulo': conversacion.titulo})
        
    except Conversacion.DoesNotExist:
        return JsonResponse({'error': 'Conversación no encontrada'}, status=404)

@login_required
def get_pronunciation_errors(request):
    conversation_id = request.GET.get('conversation_id')
    
    if conversation_id:
        errores = ErrorPronunciacion.objects.filter(usuario=request.user, conversacion_id=conversation_id).order_by('-timestamp')[:50]
    else:
        # Si no hay ID, devolvemos todo (o vacío, según preferencia, pero todo es mejor por si acaso)
        errores = ErrorPronunciacion.objects.filter(usuario=request.user).order_by('-timestamp')[:50]

    data = []
    for error in errores:
        data.append({
            'texto_original': error.texto_original,
            'texto_corregido_fonetico': error.texto_corregido_fonetico,
            'tip_fonetico': error.tip_fonetico,
            'confidence': error.confidence,
            'timestamp': error.timestamp.strftime('%H:%M')
        })
    
    return JsonResponse({'errors': data})


@login_required
def get_conversations(request):
    """API para obtener todas las conversaciones del usuario"""
    try:
        # 1. Obtenemos todas las conversaciones del usuario
        conversaciones = Conversacion.objects.filter(usuario=request.user).order_by('-fecha_inicio')
        
        # 2. Convertimos a datos simples (lista de diccionarios) para JSON
        conversaciones_data = []
        for conversacion in conversaciones:
            conversaciones_data.append({
                'id': conversacion.id_conversacion,
                'titulo': conversacion.titulo,
                'ultima_interaccion': conversacion.fecha_inicio.strftime('%Y-%m-%d %H:%M:%S')
            })

            
        return JsonResponse({'conversaciones': conversaciones_data})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

from .forms import ConfiguracionVozForm # <-- Asegúrate de importar esto

@login_required
def perfil(request):
    # Intentamos obtener la config, si no existe, se crea una por defecto
    config, created = ConfiguracionVoz.objects.get_or_create(usuario=request.user)

    if request.method == 'POST':
        form = ConfiguracionVozForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            return redirect('home') # O redirigir a 'perfil' para mostrar mensaje de éxito
    else:
        form = ConfiguracionVozForm(instance=config)

    return render(request, 'core/profile.html', {'form': form})

@login_required
def update_voice_settings_api(request):
    """API para guardar configuración de voz vía AJAX"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            config, _ = ConfiguracionVoz.objects.get_or_create(usuario=request.user)
            
            config.voice_code_tts = data.get('voice_code', config.voice_code_tts)
            config.voice_code_native_tts = data.get('voice_code_native', config.voice_code_native_tts)
            config.velocidad = float(data.get('speed', config.velocidad))
            config.save()
            
            return JsonResponse({'status': 'ok'})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'POST required'}, status=400)

@login_required
def get_user_errors_api(request):
    """API para obtener el historial de errores gramaticales"""
    # Obtenemos los últimos 20 errores
    errores = RegistroError.objects.filter(usuario=request.user).order_by('-timestamp')[:20]
    
    data = []
    for error in errores:
        data.append({
            'original': error.texto_original,
            'corregido': error.texto_corregido,
            'explicacion': error.explicacion_regla,
            'fecha': error.timestamp.strftime("%d/%m %H:%M")
        })
    return JsonResponse({'errores': data})

@login_required
def historial_errores_view(request):
    """Renderiza la página completa de historial de errores con filtros"""
    # 1. Obtener conversación seleccionada (filtro)
    conversation_id = request.GET.get('conversation_id')
    selected_chat = None

    # Base QuerySet
    errores = RegistroError.objects.filter(usuario=request.user).select_related('mensaje__conversacion').order_by('-timestamp')

    # Aplicar filtro si existe
    if conversation_id:
        errores = errores.filter(mensaje__conversacion__id_conversacion=conversation_id)
        selected_chat = get_object_or_404(Conversacion, id_conversacion=conversation_id, usuario=request.user)
    
    # 2. Obtener lista de chats para el dropdown (solo los que tienen errores sería ideal, pero todos está bien)
    conversaciones = Conversacion.objects.filter(usuario=request.user).order_by('-fecha_inicio')
    
    context = {
        'errores': errores,
        'chats': conversaciones,
        'selected_chat': selected_chat, # Para resaltar en UI
    }
    return render(request, 'core/errors_full.html', context)


# --- 2. API PARA PREVIEW DE VOZ ---
@login_required
def preview_voice_api(request):
    """Genera un audio corto para probar la voz seleccionada"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            voice_code = data.get('voice_code')
            
            # Texto de prueba según el idioma de la voz
            if 'es-ES' in voice_code:
                texto = "Hola, así es como sueno. ¿Te gusta esta voz?"
            else:
                texto = "Hello, this is how I sound. Do you like this voice?"
            
            # Obtener velocidad (opcional, por defecto 1.0)
            speed = float(data.get('speed', 1.0))
            
            # Usamos tu utilidad existente
            audio_bytes = texto_a_voz_bytes(texto, voice_code, speed)
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
            
            return JsonResponse({'audio_base64': audio_base64})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'POST required'}, status=400)

# core/views.py

# Función para verificar si es administrador
def es_admin(user):
    return user.is_superuser

@user_passes_test(es_admin)
def admin_dashboard(request):
    """
    Vista de Dashboard con Métricas Clave para la Tesis.
    """
    # 1. KPIs
    total_usuarios = User.objects.count()
    total_conversaciones = Conversacion.objects.count()
    total_errores = RegistroError.objects.count()
    
    # 2. Gráfica 1: Errores detectados por día
    # CORRECCIÓN AQUÍ: Cambiamos Count('id') por Count('id_error')
    errores_por_fecha = RegistroError.objects.annotate(date=TruncDate('timestamp')) \
        .values('date') \
        .annotate(count=Count('id_error')) \
        .order_by('date')
        
    fechas_labels = [e['date'].strftime("%d/%m") for e in errores_por_fecha]
    errores_data = [e['count'] for e in errores_por_fecha]

    # 3. Gráfica 2: Usuarios más activos
    # Aquí contamos mensajes relacionados. Django maneja esto bien, pero por seguridad
    # el Count cuenta las relaciones.
    top_usuarios = User.objects.annotate(num_msgs=Count('conversacion__mensajes')) \
        .order_by('-num_msgs')[:5]
        
    users_labels = [u.username for u in top_usuarios]
    users_data = [u.num_msgs for u in top_usuarios]

    context = {
        'total_usuarios': total_usuarios,
        'total_conversaciones': total_conversaciones,
        'total_errores': total_errores,
        'chart_fechas': json.dumps(fechas_labels),
        'chart_errores': json.dumps(errores_data),
        'chart_users_labels': json.dumps(users_labels),
        'chart_users_data': json.dumps(users_data),
    }
    
    return render(request, 'core/dashboard.html', context)

# core/views.py


# --- GESTIÓN DE USUARIOS (TABLA) ---
@user_passes_test(es_admin)
def admin_users_list(request):
    """Lista todos los usuarios para gestión"""
    usuarios = User.objects.all().order_by('-date_joined')
    return render(request, 'core/admin_users_list.html', {'usuarios': usuarios})

@user_passes_test(es_admin)
def admin_user_delete(request, user_id):
    """Elimina un usuario"""
    user = get_object_or_404(User, id=user_id)
    if user.is_superuser and user == request.user:
        messages.error(request, "No puedes eliminarte a ti mismo.")
    else:
        user.delete()
        messages.success(request, "Usuario eliminado correctamente.")
    return redirect('admin_users_list')

@user_passes_test(es_admin)
def admin_user_toggle_admin(request, user_id):
    """Convierte usuario normal en Admin y viceversa"""
    user = get_object_or_404(User, id=user_id)
    if user == request.user:
        messages.error(request, "No puedes quitarte tus propios permisos.")
    else:
        user.is_superuser = not user.is_superuser
        user.is_staff = not user.is_staff # Necesario para entrar al admin de Django también
        user.save()
        status = "Admin" if user.is_superuser else "Usuario"
        messages.success(request, f"Ahora {user.username} es {status}.")
    return redirect('admin_users_list')

# --- EXPEDIENTE DETALLADO (INDIVIDUAL) ---
@user_passes_test(es_admin)
def admin_user_detail(request, user_id):
    """Ver errores y chats de un usuario específico"""
    usuario = get_object_or_404(User, id=user_id)
    
    # Sus errores
    errores = RegistroError.objects.filter(usuario=usuario).order_by('-timestamp')
    
    # Sus conversaciones
    conversaciones = Conversacion.objects.filter(usuario=usuario).count()
    
    # Idioma preferido (de su config)
    try:
        config = usuario.configuracionvoz
        idioma = "Inglés" if "en-US" in config.voice_code_tts else "Español"
    except:
        idioma = "No configurado"

    context = {
        'target_user': usuario,
        'errores': errores,
        'total_chats': conversaciones,
        'idioma_pref': idioma
    }
    return render(request, 'core/admin_user_detail.html', context)


@user_passes_test(es_admin)
def admin_audit_logs(request):
    """
    Auditoría Avanzada: Búsqueda, Filtros y Detección de Errores.
    """
    # 1. Base de la consulta
    mensajes = Mensaje.objects.select_related('conversacion', 'conversacion__usuario') \
                      .order_by('-timestamp')

    # 2. Lógica de Búsqueda (Filtro)
    query = request.GET.get('q')
    if query:
        mensajes = mensajes.filter(
            Q(contenido_texto__icontains=query) | 
            Q(conversacion__usuario__username__icontains=query)
        )

    # 3. FILTRO IA (NUEVO)
    filtro_ia = request.GET.get('filtro_ia')
    if filtro_ia == 'toxic':
        mensajes = mensajes.filter(es_toxico=True)
    elif filtro_ia == 'sexual':
         mensajes = mensajes.filter(categoria_seguridad='SEXUALLY_EXPLICIT')
    elif filtro_ia == 'hate':
         mensajes = mensajes.filter(categoria_seguridad='HATE_SPEECH')

    # 3. Optimización: Detectar si el mensaje tiene un error asociado
    # Esto crea un campo booleano 'has_error' en cada objeto mensaje
    subquery_error = RegistroError.objects.filter(mensaje=OuterRef('pk'))
    mensajes = mensajes.annotate(has_error=Exists(subquery_error))

    # Limitamos a 100 resultados DESPUÉS de filtrar
    mensajes = mensajes[:100]
    
    context = {
        'mensajes': mensajes,
        'query': query or '' # Para mantener el texto en la barra de búsqueda
    }
    
    return render(request, 'core/admin_audit.html', context)

@user_passes_test(es_admin)
def admin_broadcast(request):
    """Permite al admin crear o apagar alertas globales"""
    if request.method == 'POST':
        mensaje = request.POST.get('mensaje')
        accion = request.POST.get('accion') # 'publicar' o 'apagar'
        
        # Primero desactivamos todas las anteriores para que solo haya 1 activa
        AlertaSistema.objects.all().update(activa=False)
        
        if accion == 'publicar' and mensaje:
            AlertaSistema.objects.create(mensaje=mensaje, activa=True)
            messages.success(request, "Alerta publicada a todos los usuarios.")
        else:
            messages.info(request, "Alertas desactivadas.")
            
        return redirect('admin_broadcast')

    # Obtener la alerta activa actual (si existe)
    alerta_actual = AlertaSistema.objects.filter(activa=True).last()
    return render(request, 'core/admin_broadcast.html', {'alerta': alerta_actual})

# --- API PÚBLICA: CONSULTAR ALERTAS (Para el Chat) ---
@login_required
def get_system_alert(request):
    """El chat llama a esto para saber si hay notificaciones"""
    alerta = AlertaSistema.objects.filter(activa=True).last()
    if alerta:
        return JsonResponse({'mensaje': alerta.mensaje, 'activa': True})
    return JsonResponse({'activa': False})

@login_required
def export_errors_pdf(request):
    """Genera un PDF con el historial de errores para imprimir"""
    # 1. Filtro opcional
    conversation_id = request.GET.get('conversation_id')
    selected_chat_title = "Resumen General"

    errores = RegistroError.objects.filter(usuario=request.user).select_related('mensaje__conversacion').order_by('-timestamp')

    if conversation_id:
        errores = errores.filter(mensaje__conversacion__id_conversacion=conversation_id)
        chat = get_object_or_404(Conversacion, id_conversacion=conversation_id, usuario=request.user)
        selected_chat_title = f"Reporte: {chat.titulo}"
    
    # Datos para el PDF
    context = {
        'usuario': request.user,
        'errores': errores,
        'fecha_generacion': timezone.now(),
        'report_title': selected_chat_title
    }
    
    # Renderizamos usando un template específico para PDF
    return render_to_pdf('core/pdf_template.html', context)

@login_required
def get_leaderboard_api(request):
    """Devuelve el Top 10"""
    
    # 1. FIX: Asegurar que EL USUARIO ACTUAL tenga su registro creado
    # Si no existía, lo crea ahora mismo para que aparezca en la lista
    ProgresoUsuario.objects.get_or_create(usuario=request.user)

    # 2. Obtener Top 10
    top_players = ProgresoUsuario.objects.filter(publico_en_leaderboard=True)\
                                         .select_related('usuario')\
                                         .order_by('-experiencia')[:10]
    
    data = []
    for p in top_players:
        data.append({
            'username': p.usuario.username,
            'xp': p.experiencia,
            'nivel': p.nivel,
            'es_yo': p.usuario == request.user # Bool para resaltar
        })
    return JsonResponse({'leaderboard': data})

@login_required
def save_gamification_settings_api(request):
    """Guarda las preferencias de gamificación"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            progreso = request.user.progresousuario
            progreso.mostrar_gamificacion = data.get('mostrar', True)
            progreso.publico_en_leaderboard = data.get('publico', True)
            progreso.save()
            return JsonResponse({'status': 'ok'})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'POST required'}, status=400)

def logout_view(request):
    """
    Cierra la sesión del usuario y redirige a la Landing Page.
    Acepta GET para facilitar el uso en enlaces HTML.
    """
    logout(request)
    return redirect('landing')

@login_required
@csrf_exempt
def tts_word_api(request):
    """Genera audio (TTS) para una palabra o frase corta."""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            text = data.get('text')
            lang = data.get('lang', 'en-US') # Por defecto inglés

            if not text:
                return JsonResponse({'error': 'No text provided'}, status=400)

            # Voz por defecto para ejemplos (puedes personalizarla)
            voice_code = 'en-US-Wavenet-D' if lang == 'en-US' else 'es-ES-Wavenet-C'

            # Generar audio
            audio_bytes = texto_a_voz_bytes(text, voice_code)
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')

            return JsonResponse({'audio_base64': audio_base64})

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'POST required'}, status=405)

@login_required
@require_POST # Solo permite peticiones POST por seguridad
def delete_conversation(request, conversation_id):
    """Elimina una conversación específica del usuario"""
    chat = get_object_or_404(Conversacion, id_conversacion=conversation_id, usuario=request.user)
    chat.delete()
    return JsonResponse({'status': 'deleted', 'id': conversation_id})

@login_required
def repaso_vocabulario(request):
    """
    Vista SRS para repasar vocabulario (Flashcards).
    Algoritmo: Muestra palabras donde proximo_repaso <= ahora.
    """
    from datetime import timedelta
    from django.utils import timezone
    from .models import Vocabulario

    now = timezone.now()
    # 1. Obtener palabras pendientes
    palabras_pendientes = Vocabulario.objects.filter(
        usuario=request.user,
        proximo_repaso__lte=now
    ).order_by('proximo_repaso')
    
    # 2. Si es POST, procesar respuesta (Easy, Hard, etc.)
    if request.method == 'POST':
        vocab_id = request.POST.get('vocab_id')
        calificacion = request.POST.get('calificacion') # 'facil', 'bien', 'dificil'
        
        vocab = get_object_or_404(Vocabulario, id=vocab_id, usuario=request.user)
        
        # Algoritmo SRS Simplificado
        dias_extra = 0
        if calificacion == 'facil':
            # Subir nivel, aumentar intervalo drásticamente
            vocab.nivel_dominio = min(5, vocab.nivel_dominio + 1)
            dias_extra = [1, 3, 7, 14, 30, 60][vocab.nivel_dominio]
        
        elif calificacion == 'bien':
            # Mantener nivel o subir poco
            dias_extra = [1, 2, 4, 7, 15, 30][vocab.nivel_dominio]
            
        else: # 'dificil' u 'olvide'
            # Reiniciar
            vocab.nivel_dominio = max(0, vocab.nivel_dominio - 1)
            dias_extra = 0 # Repasar hoy mismo o mañana (0 = ahora, pero pondremos 1 min para UX)
            
        # Calcular nueva fecha
        if dias_extra == 0:
            nuevas_fecha = now + timedelta(minutes=1) # Repasar en 1 min si falló
        else:
            nuevas_fecha = now + timedelta(days=dias_extra)
            
        vocab.proximo_repaso = nuevas_fecha
        vocab.save()
        
        return JsonResponse({'status': 'ok'})

    # Obtener configuración de voz (SOLO FALLBACK)
    target_lang = 'en-US' 
    if palabras_pendientes.exists():
        current_word = palabras_pendientes.first()
        target_lang = current_word.idioma_palabra 
        # Si por alguna razón está vacío, usar config global
        if not target_lang:
             from .models import ConfiguracionVoz
             try:
                config = ConfiguracionVoz.objects.get(usuario=request.user)
                target_lang = "-".join(config.voice_code_tts.split('-')[:2]) 
             except:
                target_lang = 'en-US'

    return render(request, 'core/repaso_vocabulario.html', {
        'palabras': palabras_pendientes,
        'count': palabras_pendientes.count(),
        'target_lang': target_lang
    })


# ---------------------------------------------------------
# SECCIÓN: SISTEMA DE QUIZZES
# ---------------------------------------------------------

from .models import Quiz, QuizPregunta, IntentoQuiz, RespuestaIntento
from .utils import generar_quiz_gemini
from datetime import timedelta

@login_required
def quiz_dashboard(request):
    """Dashboard de Quizzes: lista todos los quizzes del usuario con score acumulativo."""
    quizzes = Quiz.objects.filter(usuario=request.user).order_by('-fecha_creacion')
    
    # Calcular score acumulativo (promedio de TODOS los intentos completados)
    intentos_completados = IntentoQuiz.objects.filter(
        usuario=request.user, completado=True
    )
    total_intentos = intentos_completados.count()
    
    if total_intentos > 0:
        suma_puntajes = sum(i.puntaje for i in intentos_completados)
        score_acumulativo = round(suma_puntajes / total_intentos, 1)
    else:
        score_acumulativo = None
    
    # --- NUEVOS DATOS PARA DASHBOARD UNIFICADO (PHASE 3) ---
    # 1. Progreso del Usuario (Nivel, XP, Racha)
    progreso, _ = ProgresoUsuario.objects.get_or_create(usuario=request.user)
    
    # 2. Flashcards Pendientes (SRS)
    flashcards_pendientes = Vocabulario.objects.filter(
        usuario=request.user,
        proximo_repaso__lte=timezone.now()
    ).count()

    # 3. Leaderboard (Top 5 XP)
    leaderboard = ProgresoUsuario.objects.filter(
        publico_en_leaderboard=True
    ).select_related('usuario').order_by('-experiencia')[:5]

    # --- PHASE 7: NEW WIDGET DATA ---
    
    today = timezone.now().date()
    
    # 4. Streak Calendar (last 30 days activity heatmap)
    thirty_days_ago = today - timedelta(days=29)
    
    # Get conversation dates
    convo_dates = Conversacion.objects.filter(
        usuario=request.user,
        fecha_inicio__date__gte=thirty_days_ago
    ).values('fecha_inicio__date').annotate(count=Count('id_conversacion'))
    
    # Get quiz attempt dates
    quiz_dates = IntentoQuiz.objects.filter(
        usuario=request.user,
        completado=True,
        fecha__date__gte=thirty_days_ago
    ).values('fecha__date').annotate(count=Count('id'))
    
    # Merge into a single dict {date_str: activity_count}
    activity_map = {}
    for entry in convo_dates:
        d = entry['fecha_inicio__date'].isoformat()
        activity_map[d] = activity_map.get(d, 0) + entry['count']
    for entry in quiz_dates:
        d = entry['fecha__date'].isoformat()
        activity_map[d] = activity_map.get(d, 0) + entry['count']
    
    # Build 30-day calendar list
    calendar_data = []
    for i in range(30):
        day = thirty_days_ago + timedelta(days=i)
        day_str = day.isoformat()
        calendar_data.append({
            'date': day_str,
            'day_num': day.day,
            'weekday': day.strftime('%a'),
            'count': activity_map.get(day_str, 0),
        })
    
    # 5. Weekly Progress (last 7 days breakdown)
    seven_days_ago = today - timedelta(days=6)
    weekly_data = []
    day_labels = {'Mon': 'Lun', 'Tue': 'Mar', 'Wed': 'Mié', 'Thu': 'Jue', 'Fri': 'Vie', 'Sat': 'Sáb', 'Sun': 'Dom'}
    
    for i in range(7):
        day = seven_days_ago + timedelta(days=i)
        convos = Conversacion.objects.filter(
            usuario=request.user, fecha_inicio__date=day
        ).count()
        quizzes_day = IntentoQuiz.objects.filter(
            usuario=request.user, completado=True, fecha__date=day
        ).count()
        en_label = day.strftime('%a')
        weekly_data.append({
            'label': day_labels.get(en_label, en_label),
            'date': day.isoformat(),
            'convos': convos,
            'quizzes': quizzes_day,
            'total': convos + quizzes_day,
        })
    
    max_weekly = max((d['total'] for d in weekly_data), default=1) or 1
    
    # 6. Achievement Badges
    total_convos = Conversacion.objects.filter(usuario=request.user).count()
    total_mensajes = Mensaje.objects.filter(conversacion__usuario=request.user, rol='usuario').count()
    total_vocab = Vocabulario.objects.filter(usuario=request.user).count()
    total_quizzes_completed = IntentoQuiz.objects.filter(usuario=request.user, completado=True).count()
    has_perfect = IntentoQuiz.objects.filter(usuario=request.user, completado=True, puntaje=100).exists()
    
    badges = [
        {'icon': 'chat', 'name': 'Primera Conversación', 'desc': 'Inicia tu primera conversación', 'unlocked': total_convos >= 1},
        {'icon': 'quiz', 'name': 'Primer Quiz', 'desc': 'Completa tu primer quiz', 'unlocked': total_quizzes_completed >= 1},
        {'icon': 'local_fire_department', 'name': 'Racha de 7', 'desc': 'Mantén una racha de 7 días', 'unlocked': progreso.racha_actual >= 7},
        {'icon': 'emoji_events', 'name': 'Score Perfecto', 'desc': 'Obtén 100% en un quiz', 'unlocked': has_perfect},
        {'icon': 'menu_book', 'name': '50 Palabras', 'desc': 'Aprende 50 palabras nuevas', 'unlocked': total_vocab >= 50},
        {'icon': 'military_tech', 'name': 'Nivel 5', 'desc': 'Alcanza el nivel 5', 'unlocked': progreso.nivel >= 5},
        {'icon': 'forum', 'name': '100 Mensajes', 'desc': 'Envía 100 mensajes', 'unlocked': total_mensajes >= 100},
        {'icon': 'school', 'name': '10 Quizzes', 'desc': 'Completa 10 quizzes', 'unlocked': total_quizzes_completed >= 10},
    ]
    badges_unlocked = sum(1 for b in badges if b['unlocked'])
    
    # 7. Daily Goals (today's progress)
    convos_today = Conversacion.objects.filter(
        usuario=request.user, fecha_inicio__date=today
    ).count()
    quizzes_today = IntentoQuiz.objects.filter(
        usuario=request.user, completado=True, fecha__date=today
    ).count()
    flashcards_today = Vocabulario.objects.filter(
        usuario=request.user, ultimo_repaso__date=today
    ).count()
    
    daily_goals = [
        {'icon': 'chat', 'label': 'Conversaciones', 'current': min(convos_today, 3), 'target': 3, 'pct': min(100, round(convos_today / 3 * 100))},
        {'icon': 'quiz', 'label': 'Quizzes', 'current': min(quizzes_today, 1), 'target': 1, 'pct': min(100, round(quizzes_today / 1 * 100))},
        {'icon': 'style', 'label': 'Flashcards', 'current': min(flashcards_today, 5), 'target': 5, 'pct': min(100, round(flashcards_today / 5 * 100))},
    ]
    
    # 8. Skill Progress (accuracy per QuizPregunta category)
    skill_progress = []
    for cat_code, cat_name in [('vocabulario', 'Vocabulario'), ('gramatica', 'Gramática'), ('conjugacion', 'Conjugación')]:
        total_resp = RespuestaIntento.objects.filter(
            intento__usuario=request.user,
            intento__completado=True,
            pregunta__categoria=cat_code
        ).count()
        correct_resp = RespuestaIntento.objects.filter(
            intento__usuario=request.user,
            intento__completado=True,
            pregunta__categoria=cat_code,
            es_correcta=True
        ).count()
        accuracy = round(correct_resp / total_resp * 100) if total_resp > 0 else 0
        skill_progress.append({
            'name': cat_name,
            'accuracy': accuracy,
            'total': total_resp,
            'correct': correct_resp,
        })

    # Preparar datos de quizzes con info de estado
    quizzes_data = []
    for quiz in quizzes:
        mejor = quiz.mejor_puntaje()
        puede_reintentar = quiz.puede_reintentar()
        dias_restantes = quiz.dias_para_reintentar()
        num_intentos = quiz.intentos.filter(completado=True).count()
        
        quizzes_data.append({
            'quiz': quiz,
            'mejor_puntaje': mejor,
            'puede_reintentar': puede_reintentar,
            'dias_restantes': dias_restantes,
            'num_intentos': num_intentos,
        })
    
    context = {
        'quizzes_data': quizzes_data,
        'score_acumulativo': score_acumulativo,
        'total_intentos': total_intentos,
        'total_quizzes': quizzes.count(),
        
        # Phase 3 Contexts
        'progreso': progreso,
        'flashcards_pendientes': flashcards_pendientes,
        'leaderboard': leaderboard,
        'user': request.user,
        
        # Phase 7 Contexts
        'calendar_data': calendar_data,
        'weekly_data': weekly_data,
        'max_weekly': max_weekly,
        'badges': badges,
        'badges_unlocked': badges_unlocked,
        'badges_total': len(badges),
        'daily_goals': daily_goals,
        'skill_progress': skill_progress,
    }
    return render(request, 'core/quiz_dashboard.html', context)



@login_required
def generar_quiz_api(request):
    """API: Genera un quiz usando Gemini basado en las conversaciones del usuario."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    try:
        user = request.user
        
        # 1. Obtener configuración de idioma
        config_voz = ConfiguracionVoz.objects.filter(usuario=user).first()
        idioma_nativo = config_voz.idioma_nativo if config_voz else 'Español'
        idioma_objetivo = config_voz.idioma_objetivo if config_voz else 'Inglés'
        
        # 2. Recopilar mensajes de TODAS las conversaciones recientes
        mensajes = Mensaje.objects.filter(
            conversacion__usuario=user
        ).order_by('-timestamp')[:200]  # Últimos 200 mensajes
        
        if mensajes.count() < 5:
            return JsonResponse({
                'error': 'Necesitas al menos 5 mensajes de conversación para generar un quiz. ¡Sigue practicando!'
            }, status=400)
        
        mensajes_texto = []
        for m in mensajes:
            prefix = "Usuario" if m.rol == 'usuario' else "Bot"
            mensajes_texto.append(f"{prefix}: {m.contenido_texto}")
        
        # 3. Generar quiz con Gemini
        num_preguntas = 8
        quiz_data = generar_quiz_gemini(
            mensajes_texto, idioma_objetivo, idioma_nativo, num_preguntas
        )
        
        if not quiz_data:
            return JsonResponse({'error': 'Error generando el quiz. Intenta de nuevo.'}, status=500)
        
        # 4. Guardar en BD
        titulo = quiz_data.get('titulo', f'Quiz de {idioma_objetivo}')
        quiz = Quiz.objects.create(
            usuario=user,
            titulo=titulo,
            idioma_tag=idioma_objetivo,
            num_preguntas=len(quiz_data.get('preguntas', []))
        )
        
        for p in quiz_data.get('preguntas', []):
            opciones = p.get('opciones', ['', '', '', ''])
            QuizPregunta.objects.create(
                quiz=quiz,
                numero=p.get('numero', 1),
                pregunta=p.get('pregunta', ''),
                opcion_a=opciones[0] if len(opciones) > 0 else '',
                opcion_b=opciones[1] if len(opciones) > 1 else '',
                opcion_c=opciones[2] if len(opciones) > 2 else '',
                opcion_d=opciones[3] if len(opciones) > 3 else '',
                respuesta_correcta=p.get('respuesta_correcta', 0),
                explicacion=p.get('explicacion', ''),
                categoria=p.get('categoria', 'vocabulario')
            )
        
        return JsonResponse({
            'status': 'ok',
            'quiz_id': quiz.id,
            'titulo': titulo,
            'num_preguntas': quiz.num_preguntas
        })
    
    except Exception as e:
        logger.error(f"Error generando quiz: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def tomar_quiz(request, quiz_id):
    """GET: Renderiza el quiz. POST: Evalúa respuestas y guarda intento."""
    quiz = get_object_or_404(Quiz, id=quiz_id, usuario=request.user)
    preguntas = quiz.preguntas.all()
    
    if request.method == 'GET':
        context = {
            'quiz': quiz,
            'preguntas': preguntas,
            'puede_reintentar': quiz.puede_reintentar(),
            'dias_restantes': quiz.dias_para_reintentar(),
            'ultimo_intento': quiz.ultimo_intento(),
        }
        return render(request, 'core/tomar_quiz.html', context)
    
    if request.method == 'POST':
        # Verificar cooldown
        if not quiz.puede_reintentar():
            return JsonResponse({
                'error': f'Este quiz estará disponible en {quiz.dias_para_reintentar()} días.'
            }, status=403)
        
        # Crear intento
        intento = IntentoQuiz.objects.create(
            quiz=quiz,
            usuario=request.user,
            completado=False
        )
        
        correctas = 0
        total = preguntas.count()
        
        for pregunta in preguntas:
            # Las respuestas vienen como "pregunta_1", "pregunta_2", etc.
            respuesta_key = f'pregunta_{pregunta.numero}'
            respuesta_usuario = request.POST.get(respuesta_key)
            
            if respuesta_usuario is not None:
                respuesta_int = int(respuesta_usuario)
                es_correcta = (respuesta_int == pregunta.respuesta_correcta)
                
                if es_correcta:
                    correctas += 1
                
                RespuestaIntento.objects.create(
                    intento=intento,
                    pregunta=pregunta,
                    respuesta_usuario=respuesta_int,
                    es_correcta=es_correcta
                )
        
        # Calcular puntaje
        puntaje = round((correctas / total) * 100, 1) if total > 0 else 0
        
        # Guardar intento compeltado
        intento.puntaje = puntaje
        intento.completado = True
        
        # GAMIFICACIÓN: Otorgar XP por completar intento
        xp_ganada = 50
        progreso, _ = ProgresoUsuario.objects.get_or_create(usuario=request.user)
        progreso.experiencia += xp_ganada
        progreso.racha_actual += 1 # Aumentar racha por actividad (opcional)
        progreso.ultima_interaccion = timezone.now()
        
        # Level Up Check (Simple: cada 1000 XP sube nivel, o formula actual)
        xp_necesaria = progreso.nivel * 500
        subio_nivel = False
        if progreso.experiencia >= xp_necesaria:
            progreso.nivel += 1
            progreso.experiencia -= xp_necesaria
            subio_nivel = True
            
        progreso.save()
        
        # Guardar info en sesión para mostrar en resultado
        request.session['quiz_rewards'] = {
            'xp': xp_ganada,
            'levelup': subio_nivel,
            'nivel_nuevo': progreso.nivel
        }

        # La fecha de desbloqueo ahora es dinámica en el modelo, no necesitamos guardarla aquí.
        # Solo guardamos para referencia si se desea, o lo dejamos null.
        # intento.disponible_desde = ... (IGNORADO POR MODELO)
        intento.save()
        
        return redirect('resultado_quiz', intento_id=intento.id)

@login_required
def resultado_quiz(request, intento_id):
    intento = get_object_or_404(IntentoQuiz, id=intento_id, usuario=request.user)
    return render(request, 'core/quiz_result.html', {'intento': intento})

# =============================================
# SISTEMA DE NOTAS Y Q&A
# =============================================
from .models import Nota

@login_required
def get_notes_api(request):
    """Retorna todas las notas del usuario"""
    notas = Nota.objects.filter(usuario=request.user).order_by('-fecha_creacion')
    data = [{
        'id': n.id, 
        'contenido': n.contenido, 
        'fecha': n.fecha_creacion.strftime('%d/%m/%Y')
    } for n in notas]
    return JsonResponse({'notas': data})

@csrf_exempt
@login_required
def save_note_api(request):
    """Guarda una nueva nota"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            contenido = data.get('contenido')
            if contenido:
                nota = Nota.objects.create(usuario=request.user, contenido=contenido)
                return JsonResponse({'status': 'success', 'id': nota.id})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'error': 'POST required'}, status=405)

@csrf_exempt
@login_required
def delete_note_api(request, note_id):
    """Elimina una nota"""
    if request.method == 'DELETE':
        try:
            nota = get_object_or_404(Nota, id=note_id, usuario=request.user)
            nota.delete()
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'error': 'DELETE required'}, status=405)
    
    # GET: Verificar cooldown
    puede_reintentar = quiz.puede_reintentar()
    dias_restantes = quiz.dias_para_reintentar()
    ultimo_intento = quiz.ultimo_intento()
    
    context = {
        'quiz': quiz,
        'preguntas': preguntas,
        'puede_reintentar': puede_reintentar,
        'dias_restantes': dias_restantes,
        'ultimo_intento': ultimo_intento,
    }
    return render(request, 'core/tomar_quiz.html', context)


@login_required
def resultado_quiz(request, intento_id):
    """Muestra resultados detallados de un intento de quiz."""
    intento = get_object_or_404(IntentoQuiz, id=intento_id, usuario=request.user)
    respuestas = intento.respuestas.select_related('pregunta').all()
    
    # Preparar datos detallados
    detalle = []
    for r in respuestas:
        opciones = r.pregunta.get_opciones()
        detalle.append({
            'numero': r.pregunta.numero,
            'pregunta': r.pregunta.pregunta,
            'opciones': opciones,
            'respuesta_usuario': r.respuesta_usuario,
            'respuesta_correcta': r.pregunta.respuesta_correcta,
            'es_correcta': r.es_correcta,
            'explicacion': r.pregunta.explicacion,
            'categoria': r.pregunta.get_categoria_display(),
            'letra_usuario': ['A', 'B', 'C', 'D'][r.respuesta_usuario],
            'letra_correcta': r.pregunta.letra_correcta(),
            'texto_usuario': opciones[r.respuesta_usuario] if r.respuesta_usuario < len(opciones) else '?',
            'texto_correcta': opciones[r.pregunta.respuesta_correcta] if r.pregunta.respuesta_correcta < len(opciones) else '?',
        })
    
    correctas = sum(1 for r in respuestas if r.es_correcta)
    total = respuestas.count()
    
    context = {
        'intento': intento,
        'quiz': intento.quiz,
        'detalle': detalle,
        'correctas': correctas,
        'total': total,
        'puntaje': intento.puntaje,
        'rewards': request.session.pop('quiz_rewards', None), # Recuperar y borrar rewards
    }
    return render(request, 'core/resultado_quiz.html', context)
