
import os

file_path = 'core/static/css/chat.css'
mobile_css = """
/* --- RESPONSIVE MOBILE OPTIMIZATION --- */
@media screen and (max-width: 768px) {

    /* 1. Sidebar Off-canvas */
    .sidebar {
        position: fixed;
        left: -100%;
        /* Hidden by default */
        top: 0;
        bottom: 0;
        width: 80%;
        max-width: 300px;
        z-index: 3000;
        transition: left 0.3s ease-in-out;
        box-shadow: 5px 0 15px rgba(0, 0, 0, 0.5);
    }

    .sidebar.open {
        left: 0;
    }

    /* Overlay for sidebar */
    #sidebar-overlay {
        position: fixed;
        top: 0;
        left: 0;
        width: 100vw;
        height: 100vh;
        background: rgba(0, 0, 0, 0.7);
        z-index: 2900;
        display: none;
        backdrop-filter: blur(2px);
    }

    #sidebar-overlay.active {
        display: block;
    }

    /* 2. Main Layout Adjustment */
    .orb-container {
        width: 100%;
        height: 100vh;
        padding-top: 60px;
        /* Space for top bars */
    }

    /* 3. Gamification Bar Compact */
    .gamification-bar {
        top: 10px;
        width: 90%;
        justify-content: center;
        gap: 8px;
        flex-wrap: wrap;
        /* Allow wrap on very small screens */
    }

    .stat-pill {
        padding: 6px 10px;
        font-size: 0.8rem;
    }

    /* Hide text labels on really small screens if needed, keeping icons/numbers */
    /* .stat-pill span:last-child { display: none; } */

    /* 4. Scenario Selector Adjustment */
    .scenario-selector {
        top: 65px;
        /* Below gamification bar */
        left: 50%;
        transform: translateX(-50%);
        width: auto;
        padding: 6px 12px;
        font-size: 0.85rem;
        white-space: nowrap;
    }

    .scenario-selector:hover {
        /* Remove hover transform on touch to prevent sticky hover states */
        transform: translateX(-50%);
    }

    /* 5. Mobile Menu Button (Hamburger) */
    #mobile-menu-btn {
        display: flex !important;
        /* Force show */
        position: absolute;
        top: 15px;
        left: 15px;
        z-index: 2800;
        /* Below sidebar but above orb */
        background: rgba(0, 0, 0, 0.5);
        border: 1px solid #444;
        color: white;
        padding: 8px;
        border-radius: 8px;
        cursor: pointer;
    }

    /* 6. Orb & Live Caption adjustments */
    .orb {
        width: 120px;
        height: 120px;
    }

    .orb .material-icons {
        font-size: 3rem;
    }

    #live-caption {
        top: 15%;
        /* Move up a bit */
        font-size: 1.2rem;
        padding: 0 20px;
    }

    /* 7. Chat Messages Area */
    .chat-messages {
        width: 95%;
        top: 50%;
        /* Center vertically approx */
        height: auto;
        max-height: 35vh;
        /* Limit height */
    }

    .message {
        max-width: 100%;
        /* Use full width available in container */
    }

    .bubble {
        padding: 10px;
        font-size: 0.95rem;
    }

    /* 8. Floating Action Buttons (Corner) */
    div[style*="bottom: 20px; right: 20px"] {
        bottom: 15px !important;
        right: 15px !important;
        gap: 8px !important;
    }

    div[style*="bottom: 20px; right: 20px"] button {
        width: 40px !important;
        height: 40px !important;
    }

    /* 9. Drawers (History/Errors) - Full Screen on Mobile */
    .history-drawer,
    .errors-drawer {
        width: 100%;
        right: -100%;
    }

    /* 10. Tutorial Card */
    .tutorial-card {
        width: 90%;
        left: 5%;
        bottom: 20px;
        top: auto;
        /* Force bottom position */
    }
}
"""

try:
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find the corruption point (looking for the start of the spaced out text)
    # The clean file should end with "text-decoration: underline;\n}" ideally
    # But based on the view, it ends with "}" followed immediately by "/ * ..."
    
    # We'll search for the last valid selector block ending
    marker = "text-decoration: underline;"
    idx = content.rfind(marker)
    
    if idx != -1:
        # Find the next closing brace
        brace_idx = content.find('}', idx)
        if brace_idx != -1:
            # Cut everything after the brace
            clean_content = content[:brace_idx+1]
            
            # Write back clean content + mobile css
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(clean_content + "\n\n" + mobile_css)
            print("Successfully fixed chat.css")
        else:
            print("Could not find closing brace after marker")
    else:
        print("Could not find marker text-decoration: underline;")

except Exception as e:
    print(f"Error: {e}")
