// core/static/js/main.js

const recordBtn = document.getElementById('record-btn');
const statusText = document.getElementById('status-text');
const messagesBox = document.getElementById('messages-box');
let mediaRecorder;
let audioChunks = [];

// Función para obtener el CSRF token de Django
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

// 1. Configurar grabación de audio
recordBtn.addEventListener('click', async () => {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop();
        recordBtn.classList.remove('recording');
        statusText.innerText = "Procesando...";
    } else {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);
            audioChunks = [];

            mediaRecorder.ondataavailable = event => audioChunks.push(event.data);

            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/mp3' }); // O webm
                procesarAudio(audioBlob);
            };

            mediaRecorder.start();
            recordBtn.classList.add('recording');
            statusText.innerText = "Escuchando... (Presiona de nuevo para enviar)";
        } catch (err) {
            console.error("Error al acceder al micrófono:", err);
            statusText.innerText = "Error: No se detectó micrófono.";
        }
    }
});

// 2. Enviar Audio al Backend
async function procesarAudio(audioBlob) {
    // Convertir Blob a Base64
    const reader = new FileReader();
    reader.readAsDataURL(audioBlob);
    reader.onloadend = async () => {
        const base64Audio = reader.result.split(',')[1]; // Quitar cabecera data:audio...

        // PASO A: Voz a Texto (STT)
        // Usamos la API que creamos en views.py
        const sttResponse = await fetch('/api/stt/', {
            method: 'POST',
            body: JSON.stringify({ audio_base64: base64Audio, language_code: 'es-ES' }), // Ajustar idioma
            headers: { 'X-CSRFToken': getCookie('csrftoken') }
        });
        const sttData = await sttResponse.json();

        if (sttData.transcript) {
            agregarMensaje('user', sttData.transcript);

            // PASO B: Enviar Texto a Chat (Gemini) -> Recibir Respuesta + Audio
            enviarAlChat(sttData.transcript);
        } else {
            statusText.innerText = "No te entendí bien, intenta de nuevo.";
        }
    };
}

async function enviarAlChat(texto) {
    statusText.innerText = "El Bot está pensando...";

    // Llamamos a la vista principal chat_interaction
    // Nota: Necesitas crear una URL para chat_interaction en urls.py si no la tienes
    const chatResponse = await fetch('/chat_interaction/', {
        method: 'POST',
        body: JSON.stringify({
            text: texto,
            conversation_id: 1, // Hardcodeado por ahora para prueba
            user_id: 1
        }),
        headers: { 'X-CSRFToken': getCookie('csrftoken') }
    });

    const data = await chatResponse.json();

    if (data.bot_text) {
        agregarMensaje('bot', data.bot_text);
        statusText.innerText = "Listo.";

        // PASO C: Reproducir Audio
        if (data.audio_base64) {
            const audio = new Audio("data:audio/mp3;base64," + data.audio_base64);
            audio.play();
        }
    }
}

function agregarMensaje(rol, texto) {
    const div = document.createElement('div');
    div.classList.add('message', rol);
    div.innerHTML = `<div class="bubble">${texto}</div>`;
    messagesBox.appendChild(div);
    messagesBox.scrollTop = messagesBox.scrollHeight;
}