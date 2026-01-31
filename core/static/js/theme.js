// core/static/js/theme.js

document.addEventListener('DOMContentLoaded', () => {
    // 1. Cargar Tema Guardado al iniciar
    const savedTheme = localStorage.getItem('naza-theme') || 'dark';
    applyTheme(savedTheme);

    // 2. Vincular botón (si existe en la página)
    const themeBtn = document.getElementById('theme-btn');
    if (themeBtn) {
        themeBtn.addEventListener('click', toggleTheme);
    }
});

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    applyTheme(newTheme);
    localStorage.setItem('naza-theme', newTheme);
}

function applyTheme(theme) {
    // 1. Aplicar al documento (CSS Variables)
    document.documentElement.setAttribute('data-theme', theme);

    // 2. Actualizar Icono/Texto (si existen)
    const icon = document.getElementById('theme-icon');
    const text = document.getElementById('theme-text');

    if (icon && text) {
        if (theme === 'light') {
            icon.innerText = 'light_mode';
            text.innerText = 'Modo Claro';
            icon.style.color = '#FBC02D'; // Sun Yellow
        } else {
            icon.innerText = 'dark_mode';
            text.innerText = 'Modo Oscuro';
            icon.style.color = '#BB86FC'; // Moon Purple
        }
    }
}
