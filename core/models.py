from django.db import models
from django.utils import timezone
from django.db import models
from django.contrib.auth.models import User # Usaremos el User de Django

class ConfiguracionVoz(models.Model):
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)
    voice_code_tts = models.CharField(max_length=50, default='es-US-Wavenet-A')
    velocidad = models.FloatField(default=1.0)
    idioma_preferido = models.CharField(max_length=10, default='es-US')

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