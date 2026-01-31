# core/views.py

import json
import base64
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.core.mail import send_mail # <--- Importante
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
from .utils import render_to_pdf
from django.utils import timezone
from django.contrib.auth import logout
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404
from django.contrib import messages

# Importamos nuestros modelos y formularios
from .models import Conversacion, Mensaje, RegistroError, ConfiguracionVoz, ProgresoUsuario, ErrorPronunciacion
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
            mensaje = f"Hola {user.username},\n\nTu código de verificación es: {codigo}\n\nIngrésalo en la plataforma para activar tu cuenta."
            try:
                send_mail(asunto, mensaje, settings.EMAIL_HOST_USER, [user.email])
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

@login_required
def home(request):
    # 1. Cargar conversaciones
    mis_conversaciones = Conversacion.objects.filter(usuario=request.user).order_by('-fecha_inicio')
    
    # 2. OBTENER EL PROGRESO (CRÍTICO)
    # Usamos get_or_create para que nunca sea None
    progreso, created = ProgresoUsuario.objects.get_or_create(usuario=request.user)

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
            Mensaje.objects.create(conversacion=conversacion, rol='usuario', contenido_texto=user_text)

            # --- CEREBRO (GEMINI) ---
            print("DEBUG: Calling obtaining_respuesta_gemini...")
            gemini_data = obtener_respuesta_gemini([], user_text, detected_lang, scenario, confidence)
            print(f"DEBUG: gemini_data type: {type(gemini_data)}")
            print(f"DEBUG: gemini_data: {gemini_data}")
            
            # Si gemini_data es string (por alguna razón rara), intentamos parsear por seguridad
            if isinstance(gemini_data, str):
                print("DEBUG: gemini_data IS STRING! Parsing manually...")
                gemini_data = json.loads(gemini_data)
            
            bot_text = gemini_data['respuesta_bot']
            idioma_respuesta = gemini_data.get('idioma_respuesta', 'es-ES')

            # Guardar mensaje del Bot
            msg_bot = Mensaje.objects.create(conversacion=conversacion, rol='bot', contenido_texto=bot_text)
            
            # 4. GUARDAR ERRORES (GRAMATICALES Y PRONUNCIACIÓN)
            # FIX: Solo guardamos si REALMENTE hay una corrección (evita crash por null)
            if gemini_data.get('hay_error') and gemini_data.get('correccion'):
                RegistroError.objects.create(
                    usuario=user,
                    mensaje=msg_bot,
                    texto_original=gemini_data.get('texto_original', user_text),
                    texto_corregido=gemini_data.get('correccion'),
                    explicacion_regla=gemini_data.get('explicacion')
                )
            
            # --- NUEVO: GUARDAR ERROR DE PRONUNCIACIÓN ---
            tip_pronunciacion = gemini_data.get('tip_pronunciacion')
            texto_corregido_fonetico = gemini_data.get('texto_corregido_fonetico')

            # FALLBACK DE SEGURIDAD:
            # Si la confianza es baja (< 0.85) y Gemini NO mandó tip, inventamos uno genérico
            # para asegurar que se guarde en el historial.
            print(f"DEBUG PRONUNCIATION: Confidence={confidence}, Tip={tip_pronunciacion}") # DEBUG
            
            if confidence < 0.90 and not tip_pronunciacion:
                tip_pronunciacion = "Intenta vocalizar más claro y pausado."
                print("DEBUG PRONUNCIATION: Generating Fallback Tip") # DEBUG
                if not texto_corregido_fonetico:
                    texto_corregido_fonetico = user_text # Asumimos que quería decir lo mismo si no hubo corrección

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
                     print(f"DEBUG PRONUNCIATION: Saved Error ID {nuevo_error.id} for user {user.username}") # DEBUG
                 except Exception as e:
                     print(f"DEBUG PRONUNCIATION: ERROR SAVING TO DB: {e}") # DEBUG

            # --- VOZ DINÁMICA (Espejo de Género) ---
            # Obtenemos la preferencia del usuario (Ej: Español - Voz Mujer)
            config_voz = ConfiguracionVoz.objects.filter(usuario=user).first()
            voz_preferida = config_voz.voice_code_tts if config_voz else 'es-ES-Standard-A'
            
            # Detectamos si Gemini respondió en Inglés para cambiar la voz
            if idioma_respuesta == 'en-US':
                # Mapeo simple: si prefiere mujer español, usa mujer inglés
                if 'Standard-A' in voz_preferida or 'Standard-C' in voz_preferida: 
                    voice_code = 'en-US-Standard-C' # Mujer
                elif 'Standard-B' in voz_preferida or 'Standard-D' in voz_preferida:
                    voice_code = 'en-US-Standard-D' # Hombre
                else:
                    voice_code = 'en-US-Standard-C'
            else:
                voice_code = voz_preferida

            # Generar el audio
            audio_bytes = texto_a_voz_bytes(bot_text, voice_code)
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')

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
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'POST required'}, status=405)
# ---------------------------------------------------------
# SECCIÓN 3: APIs DE GOOGLE CLOUD (STT y TTS)
# ---------------------------------------------------------

# Cliente STT global para reutilizar conexión
stt_client = speech.SpeechClient()

@csrf_exempt
def speech_to_text_api(request):
    """API para convertir audio del micrófono a texto"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Solo POST'}, status=405)
    try:
        data = json.loads(request.body)
        audio_base64 = data.get('audio_base64')
        language_code = data.get('language_code', 'es-ES')

        if not audio_base64:
            return JsonResponse({'error': 'Falta audio'}, status=400)

        audio_content = base64.b64decode(audio_base64)
        recognition_audio = speech.RecognitionAudio(content=audio_content)
        
        # Configuración para audio web (ajusta según lo que envíe tu JS)
        first_lang = 'es-ES' 
        alternative_langs = ['en-US'] 

        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.MP3,
            sample_rate_hertz=16000,
            language_code=first_lang,
            alternative_language_codes=alternative_langs, # <--- ¡AQUÍ ESTÁ EL TRUCO!
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
    """Renderiza la página completa de historial de errores"""
    # Obtenemos los errores y 'select_related' para traer el título de la conversación eficientemente
    errores = RegistroError.objects.filter(usuario=request.user).select_related('mensaje__conversacion').order_by('-timestamp')
    
    # Reutilizamos la lógica de la sidebar para que no desaparezca
    conversaciones = Conversacion.objects.filter(usuario=request.user).order_by('-fecha_inicio')
    
    context = {
        'errores': errores,
        'chats': conversaciones # Para mantener la sidebar llena
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
            
            # Usamos tu utilidad existente
            audio_bytes = texto_a_voz_bytes(texto, voice_code)
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
    # Obtenemos todos los errores del usuario
    errores = RegistroError.objects.filter(usuario=request.user).order_by('-timestamp')
    
    # Datos para el PDF
    context = {
        'usuario': request.user,
        'errores': errores,
        'fecha_generacion': timezone.now()
    }
    
    # Renderizamos usando un template específico para PDF (simple, fondo blanco)
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