# core/urls.py
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from django.contrib.auth import views as auth_views #

urlpatterns = [
    # Rutas de Autenticación
    path('login/', auth_views.LoginView.as_view(template_name='core/login.html'), name='login'),

    path('register/', views.register, name='register'),
    path('verify-email/', views.verify_email, name='verify_email'),

    # Rutas de la App
    path('', views.landing, name='landing'),
    path('chat/', views.home, name='home'),
    
    # APIs (Las que ya tenías)
    path('api/tts/', views.text_to_speech_api, name='api_tts'),
    path('api/tts_word/', views.tts_word_api, name='tts_word_api'),
    path('api/stt/', views.speech_to_text_api, name='api_stt'),
    path('chat_interaction/', views.chat_interaction, name='chat_interaction'),
    path('api/conversations/<int:conversation_id>/', views.get_conversation_detail, name='get_conversation_detail'),
    path('api/conversations/', views.get_conversations, name='get_conversations'),
    path('perfil/', views.perfil, name='perfil'),
    path('api/settings/voice/', views.update_voice_settings_api, name='api_voice_save'),
    path('api/settings/errors/', views.get_user_errors_api, name='api_errors_get'),
    path('api/pronunciation-errors/', views.get_pronunciation_errors, name='get_pronunciation_errors'),
    path('historial-errores/', views.historial_errores_view, name='historial_errores'),
    path('api/settings/preview-voice/', views.preview_voice_api, name='api_voice_preview'),
    path('dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('dashboard/users/', views.admin_users_list, name='admin_users_list'),
    path('dashboard/users/delete/<int:user_id>/', views.admin_user_delete, name='admin_user_delete'),
    path('dashboard/users/toggle-admin/<int:user_id>/', views.admin_user_toggle_admin, name='admin_user_toggle'),
    path('dashboard/users/<int:user_id>/', views.admin_user_detail, name='admin_user_detail'),
    path('dashboard/audit/', views.admin_audit_logs, name='admin_audit'),
    path('dashboard/broadcast/', views.admin_broadcast, name='admin_broadcast'),
    path('api/alert/', views.get_system_alert, name='api_get_alert'),
    path('export/pdf/', views.export_errors_pdf, name='export_pdf'),
    path('api/leaderboard/', views.get_leaderboard_api, name='api_leaderboard'),
    path('api/settings/game/', views.save_gamification_settings_api, name='api_game_settings'),
    path('logout/', views.logout_view, name='logout'),

    path('reset_password/', 
         auth_views.PasswordResetView.as_view(template_name="core/password_reset.html"), 
         name='password_reset'),

    # 2. Mensaje de "Correo enviado"
    path('reset_password_sent/', 
         auth_views.PasswordResetDoneView.as_view(template_name="core/password_reset_sent.html"), 
         name='password_reset_done'),

    # 3. El enlace que llega al correo (Para poner la nueva clave)
    path('reset/<uidb64>/<token>/', 
         auth_views.PasswordResetConfirmView.as_view(template_name="core/password_reset_form.html"), 
         name='password_reset_confirm'),

    # 4. Mensaje de éxito final
    path('reset_password_complete/', 
         auth_views.PasswordResetCompleteView.as_view(template_name="core/password_reset_done_final.html"), 
         name='password_reset_complete'),

    path('chat/delete/<int:conversation_id>/', views.delete_conversation, name='delete_chat'),

    
]