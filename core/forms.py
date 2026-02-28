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
        ('en-US-Studio-O', 'Inglés (M) - Studio (Ultra Realista)'),
        ('en-US-Studio-Q', 'Inglés (H) - Studio (Ultra Realista)'),
        ('en-US-Polyglot-1', 'Inglés (H) - Polyglot (Nativo)'),
        ('en-US-Wavenet-C', 'Inglés (M) - WaveNet'), 
        
        # --- ESPAÑOL (EE.UU. / ESPAÑA) ---
        # --- ESPAÑOL (EE.UU. / LATINOAMÉRICA) ---
        ('es-US-Neural2-A', 'Español (H) - Neural2 (Latino)'),
        ('es-US-Neural2-C', 'Español (M) - Neural2 (Latino)'),
        ('es-US-Studio-B', 'Español (H) - Studio (Latino Realista)'),
        ('es-US-Polyglot-1', 'Español (H) - Polyglot (Latino)'),

        # --- ESPAÑOL (ESPAÑA) ---
        ('es-ES-Neural2-A', 'Español (M) - Neural2 (España)'),
        ('es-ES-Neural2-B', 'Español (H) - Neural2 (España)'),
        ('es-ES-Studio-C', 'Español (M) - Studio (España Realista)'),
        ('es-ES-Studio-F', 'Español (H) - Studio (España Realista)'),
        ('es-ES-Polyglot-1', 'Español (H) - Polyglot (Nat)'),

        # --- FRANCÉS (FRANCIA) ---
        ('fr-FR-Studio-A', 'Francés (M) - Studio'),
        ('fr-FR-Studio-D', 'Francés (H) - Studio'),
        ('fr-FR-Polyglot-1', 'Francés (H) - Polyglot'),

        # --- ALEMÁN (ALEMANIA) ---
        ('de-DE-Studio-B', 'Alemán (H) - Studio'),
        ('de-DE-Studio-C', 'Alemán (M) - Studio'),
        ('de-DE-Polyglot-1', 'Alemán (H) - Polyglot'),

        # --- ITALIANO (ITALIA) ---
        ('it-IT-Neural2-A', 'Italiano (M) - Neural2'),
        ('it-IT-Neural2-C', 'Italiano (H) - Neural2'),

        # --- PORTUGUÉS (BRASIL) ---
        ('pt-BR-Neural2-A', 'Portugués (M) - Neural2'),
        ('pt-BR-Neural2-C', 'Portugués (H) - Neural2'),

        # --- JAPONÉS (JAPÓN) ---
        ('ja-JP-Neural2-B', 'Japonés (M) - Neural2'),
        ('ja-JP-Neural2-C', 'Japonés (H) - Neural2'),

        # --- CHINO (MANDARÍN) ---
        ('zh-CN-Wavenet-A', 'Chino (M) - WaveNet'),
        ('zh-CN-Wavenet-B', 'Chino (H) - WaveNet'),

        # --- RUSO (RUSIA) ---
        ('ru-RU-Wavenet-A', 'Ruso (M) - WaveNet'),
        ('ru-RU-Wavenet-B', 'Ruso (H) - WaveNet'),
    ]

    voice_code_tts = forms.ChoiceField(choices=OPCIONES_VOZ, label="Voz del Tutor (Idioma Objetivo)")
    voice_code_native_tts = forms.ChoiceField(choices=OPCIONES_VOZ, label="Voz del Tutor (Idioma Nativo)")
    


    # --- NUEVA LISTA DE IDIOMAS ---
    OPCIONES_IDIOMA = [
        ('Español', 'Español'),
        ('Inglés', 'Inglés'),
        ('Francés', 'Francés'),
        ('Alemán', 'Alemán'),
        ('Italiano', 'Italiano'),
        ('Portugués', 'Portugués'),
        ('Japonés', 'Japonés'),
        ('Chino', 'Chino'),
        ('Ruso', 'Ruso'),
    ]

    idioma_nativo = forms.ChoiceField(choices=OPCIONES_IDIOMA, label="Mi Idioma Nativo")
    idioma_objetivo = forms.ChoiceField(choices=OPCIONES_IDIOMA, label="Quiero Aprender")

    class Meta:
        model = ConfiguracionVoz
        fields = ['voice_code_tts', 'voice_code_native_tts', 'velocidad', 'idioma_nativo', 'idioma_objetivo', 'dias_cooldown']
        widgets = {
            # Slider para la velocidad: 0.5 (Lento) a 1.5 (Rápido)
            'velocidad': forms.NumberInput(attrs={
                'type': 'range', 
                'min': '0.5', 
                'max': '1.5', 
                'step': '0.1', 
                'class': 'range-slider'
            }),
            'dias_cooldown': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '30',
                'placeholder': 'Ej: 3 días'
            }),
        }
        labels = {
            'velocidad': 'Velocidad de Respuesta',
        }