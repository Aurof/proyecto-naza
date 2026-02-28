from django.db import models
from django.utils import timezone
from datetime import timedelta
from django.db import models
from django.contrib.auth.models import User # Usaremos el User de Django

class ConfiguracionVoz(models.Model):
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)
    voice_code_tts = models.CharField(max_length=50, default='es-US-Wavenet-A', verbose_name="Voz Idioma Objetivo")
    voice_code_native_tts = models.CharField(max_length=50, default='es-ES-Neural2-B', verbose_name="Voz Idioma Nativo")
    velocidad = models.FloatField(default=1.0)
    idioma_preferido = models.CharField(max_length=10, default='es-US')
    
    # Soporte Multilenguaje Universal
    idioma_nativo = models.CharField(max_length=50, default='Español')
    idioma_objetivo = models.CharField(max_length=50, default='Inglés')
    dias_cooldown = models.IntegerField(default=3, verbose_name="Días de espera para repetir Quizzes")

    def __str__(self):
        return f"Configuración de {self.usuario.username}"

class Conversacion(models.Model):
    id_conversacion = models.AutoField(primary_key=True)
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    titulo = models.CharField(max_length=150)
    idioma_actual = models.CharField(max_length=10)
    fecha_inicio = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.titulo

class Mensaje(models.Model):
    ROL_CHOICES = [
        ('usuario', 'Usuario'),
        ('bot', 'Bot'),
    ]
    id_mensaje = models.AutoField(primary_key=True)
    conversacion = models.ForeignKey(Conversacion, on_delete=models.CASCADE, related_name='mensajes')
    rol = models.CharField(max_length=10, choices=ROL_CHOICES)
    contenido_texto = models.TextField()
    audio_url = models.CharField(max_length=255, blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    # --- AUDITORIA IA ---
    es_toxico = models.BooleanField(default=False)
    categoria_seguridad = models.CharField(max_length=50, blank=True, null=True)
    confianza_seguridad = models.FloatField(default=0.0)

    def __str__(self):
        return f"{self.rol} en {self.conversacion.titulo}"

class RegistroError(models.Model):
    id_error = models.AutoField(primary_key=True)
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    mensaje = models.ForeignKey(Mensaje, on_delete=models.CASCADE)
    texto_original = models.TextField()
    texto_corregido = models.TextField()
    explicacion_regla = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Error de {self.usuario.username} en {self.mensaje.id_mensaje}"

class ErrorPronunciacion(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    conversacion = models.ForeignKey(Conversacion, on_delete=models.CASCADE, null=True, blank=True)
    texto_original = models.TextField()
    texto_corregido_fonetico = models.TextField(blank=True, null=True)
    tip_fonetico = models.TextField()
    confidence = models.FloatField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Pronunciación de {self.usuario.username}: {self.texto_original[:20]}"

class AlertaSistema(models.Model):
    mensaje = models.CharField(max_length=255)
    activa = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Alerta: {self.mensaje} ({'Activa' if self.activa else 'Inactiva'})"

class ProgresoUsuario(models.Model):
    usuario = models.OneToOneField(User, on_delete=models.CASCADE)
    nivel = models.IntegerField(default=1)
    experiencia = models.IntegerField(default=0)
    racha_actual = models.IntegerField(default=0)
    ultima_interaccion = models.DateField(default=timezone.now)
    
    # --- NUEVOS CAMPOS DE CONFIGURACIÓN ---
    mostrar_gamificacion = models.BooleanField(default=True, verbose_name="Ver Gamificación en Chat")
    publico_en_leaderboard = models.BooleanField(default=True, verbose_name="Aparecer en Ranking Global")
    
    # --- VERIFICACIÓN DE CORREO ---
    codigo_verificacion = models.CharField(max_length=6, blank=True, null=True)
    cuenta_verificada = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.usuario.username} - Nvl {self.nivel}"

class UserFact(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='hechos')
    dato = models.CharField(max_length=255) # Ej: "Es arquitecto", "Tiene un gato llamado Mishi"
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.usuario.username}: {self.dato}"

class Vocabulario(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='vocabulario')
    palabra = models.CharField(max_length=100)
    traduccion = models.CharField(max_length=150)
    ejemplo = models.TextField(blank=True, null=True)
    # Sistema Leitner simplificado: 
    # 0=Nuevo, 1=1 día, 2=3 días, 3=7 días, 4=14 días, 5=30 días
    nivel_dominio = models.IntegerField(default=0) 
    proximo_repaso = models.DateTimeField(default=timezone.now)
    ultimo_repaso = models.DateTimeField(auto_now_add=True)
    idioma_palabra = models.CharField(max_length=10, default='en-US') # fr-FR, en-US, etc.
    
    def __str__(self):
        return f"{self.palabra} ({self.usuario.username})"

# =============================================
# SISTEMA DE QUIZZES
# =============================================

class Quiz(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='quizzes')
    titulo = models.CharField(max_length=200)
    idioma_tag = models.CharField(max_length=50)  # Ej: "Inglés", "Francés"
    num_preguntas = models.IntegerField(default=8)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Quiz: {self.titulo} ({self.usuario.username})"

    def mejor_puntaje(self):
        """Retorna el mejor puntaje obtenido en este quiz, o None"""
        mejor = self.intentos.filter(completado=True).order_by('-puntaje').first()
        return mejor.puntaje if mejor else None

    def ultimo_intento(self):
        """Retorna el último intento completado"""
        return self.intentos.filter(completado=True).order_by('-fecha').first()

    def get_dias_cooldown(self):
        """Retorna los días de cooldown configurados por el usuario (default 3)"""
        if hasattr(self.usuario, 'configuracionvoz'):
            return self.usuario.configuracionvoz.dias_cooldown
        return 3

    def puede_reintentar(self):
        """True si han pasado los días configurados desde el último intento"""
        ultimo = self.ultimo_intento()
        if not ultimo:
            return True
        
        # Lógica Dinámica: Usar la confi del usuario en tiempo real
        dias_esp = self.get_dias_cooldown()
        fecha_desbloqueo = ultimo.fecha + timedelta(days=dias_esp)
        
        return timezone.now() >= fecha_desbloqueo

    def dias_para_reintentar(self):
        """Días restantes para poder reintentar (cálculo dinámico)"""
        ultimo = self.ultimo_intento()
        if not ultimo:
            return 0
            
        dias_esp = self.get_dias_cooldown()
        fecha_desbloqueo = ultimo.fecha + timedelta(days=dias_esp)
        
        if timezone.now() >= fecha_desbloqueo:
            return 0
            
        delta = fecha_desbloqueo - timezone.now()
        return max(0, delta.days + 1)


class QuizPregunta(models.Model):
    CATEGORIA_CHOICES = [
        ('vocabulario', 'Vocabulario'),
        ('gramatica', 'Gramática'),
        ('conjugacion', 'Conjugación'),
    ]
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='preguntas')
    numero = models.IntegerField()  # Orden: 1, 2, 3...
    pregunta = models.TextField()
    opcion_a = models.CharField(max_length=255)
    opcion_b = models.CharField(max_length=255)
    opcion_c = models.CharField(max_length=255)
    opcion_d = models.CharField(max_length=255)
    respuesta_correcta = models.IntegerField()  # 0=A, 1=B, 2=C, 3=D
    explicacion = models.TextField(blank=True)
    categoria = models.CharField(max_length=20, choices=CATEGORIA_CHOICES, default='vocabulario')

    class Meta:
        ordering = ['numero']

    def __str__(self):
        return f"Q{self.numero}: {self.pregunta[:40]}..."

    def get_opciones(self):
        return [self.opcion_a, self.opcion_b, self.opcion_c, self.opcion_d]

    def letra_correcta(self):
        return ['A', 'B', 'C', 'D'][self.respuesta_correcta]


class IntentoQuiz(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='intentos')
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='intentos_quiz')
    puntaje = models.FloatField(default=0)  # 0-100
    fecha = models.DateTimeField(auto_now_add=True)
    completado = models.BooleanField(default=False)
    disponible_desde = models.DateTimeField(null=True, blank=True)  # Cooldown: now + 3 días

    def __str__(self):
        return f"Intento de {self.usuario.username} en {self.quiz.titulo}: {self.puntaje}%"


class RespuestaIntento(models.Model):
    intento = models.ForeignKey(IntentoQuiz, on_delete=models.CASCADE, related_name='respuestas')
    pregunta = models.ForeignKey(QuizPregunta, on_delete=models.CASCADE)
    respuesta_usuario = models.IntegerField()  # 0=A, 1=B, 2=C, 3=D
    es_correcta = models.BooleanField(default=False)

    def __str__(self):
        estado = "✓" if self.es_correcta else "✗"
        return f"{estado} Q{self.pregunta.numero}"

class Nota(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notas')
    contenido = models.TextField()
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Nota de {self.usuario.username}: {self.contenido[:20]}..."