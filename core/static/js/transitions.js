/**
 * Naza - Page Transition System
 * Smooth fade-out/fade-in between internal pages.
 * Self-contained: injects its own CSS so it works on ANY page.
 */
(function () {
    'use strict';

    const TRANSITION_DURATION = 300; // ms

    // --- INJECT CSS (so it works on every page, even without chat.css) ---
    const style = document.createElement('style');
    style.textContent = `
        @keyframes naza-page-enter {
            from { opacity: 0; transform: translateY(12px); }
            to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes naza-page-exit {
            from { opacity: 1; transform: translateY(0); }
            to   { opacity: 0; transform: translateY(-10px); }
        }
        body.page-enter {
            animation: naza-page-enter ${TRANSITION_DURATION}ms ease-out forwards;
        }
        body.page-exit {
            animation: naza-page-exit ${TRANSITION_DURATION}ms ease-in forwards;
            pointer-events: none !important;
        }
    `;
    document.head.appendChild(style);

    // --- FADE-IN on page load ---
    document.addEventListener('DOMContentLoaded', () => {
        document.body.classList.add('page-enter');
        setTimeout(() => {
            document.body.classList.remove('page-enter');
        }, TRANSITION_DURATION + 50);
    });

    // --- FADE-OUT on link click ---
    document.addEventListener('click', (e) => {
        const anchor = e.target.closest('a');
        if (!anchor) return;

        const href = anchor.getAttribute('href');

        // Skip: no href, anchors, javascript:, external, new tabs, downloads
        if (!href) return;
        if (href.startsWith('#')) return;
        if (href.startsWith('javascript:')) return;
        if (href.startsWith('http') && !href.includes(window.location.host)) return;
        if (anchor.target === '_blank') return;
        if (anchor.hasAttribute('download')) return;

        // Skip if modifier keys are held (Ctrl+click opens new tab, etc.)
        if (e.ctrlKey || e.metaKey || e.shiftKey) return;

        e.preventDefault();

        // Apply exit animation
        document.body.classList.add('page-exit');

        // Navigate after animation completes
        setTimeout(() => {
            window.location.href = href;
        }, TRANSITION_DURATION);
    });

    // --- Handle browser back/forward (bfcache) ---
    window.addEventListener('pageshow', (e) => {
        if (e.persisted) {
            document.body.classList.remove('page-exit');
            document.body.classList.add('page-enter');
            setTimeout(() => {
                document.body.classList.remove('page-enter');
            }, TRANSITION_DURATION + 50);
        }
    });
})();
