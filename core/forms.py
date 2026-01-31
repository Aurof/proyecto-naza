# core/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import ConfiguracionVoz

class RegistroForm(UserCreationForm):
    # Añadimos email como campo requerido (Django por defecto solo pide usuario/pass)
    email = forms.EmailField(required=True, help_text="Requerido para recuperar contraseña")

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name']

# --- Formulario de Configuración de Voz (ACTUALIZADO) ---
class ConfiguracionVozForm(forms.ModelForm):
    # Lista curada de voces Standard y WaveNet (Compatibles con Plan Gratuito)
    OPCIONES_VOZ = [
        # --- INGLÉS (EE.UU.) ---
        ('en-US-Standard-B', 'Inglés (H) - Estándar'),
        ('en-US-Standard-C', 'Inglés (M) - Estándar'),
        ('en-US-Wavenet-D', 'Inglés (H) - WaveNet (Alta Calidad)'),
        ('en-US-Wavenet-C', 'Inglés (M) - WaveNet (Alta Calidad)'), # Recomendada
        
        # --- ESPAÑOL (ESPAÑA) ---
        ('es-ES-Standard-B', 'Español (H) - Estándar'),
        ('es-ES-Standard-A', 'Español (M) - Estándar'),
        ('es-ES-Wavenet-B', 'Español (H) - WaveNet (Alta Calidad)'),
        ('es-ES-Wavenet-C', 'Español (M) - WaveNet (Alta Calidad)'), # Recomendada
    ]

    voice_code_tts = forms.ChoiceField(choices=OPCIONES_VOZ, label="Voz del Tutor")
    
    class Meta:
        model = ConfiguracionVoz
        fields = ['voice_code_tts', 'velocidad']
        widgets = {
            # Slider para la velocidad: 0.5 (Lento) a 1.5 (Rápido)
            'velocidad': forms.NumberInput(attrs={
                'type': 'range', 
                'min': '0.5', 
                'max': '1.5', 
                'step': '0.1', 
                'class': 'range-slider'
            }),
        }
        labels = {
            'velocidad': 'Velocidad de Respuesta',
        }