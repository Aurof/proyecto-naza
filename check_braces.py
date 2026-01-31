
import re

def check_structure(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    open_braces = 0
    close_braces = 0
    
    # Simple count
    open_braces = content.count('{')
    close_braces = content.count('}')
    
    print(f"Total {{: {open_braces}")
    print(f"Total }}: {close_braces}")
    
    if open_braces != close_braces:
        print("MISMATCH DETECTED!")
        diff = open_braces - close_braces
        if diff > 0:
            print(f"Missing {diff} closing braces '}}'.")
        else:
            print(f"Extra {abs(diff)} closing braces '}}'.")
    else:
        print("Braces are balanced.")

    # Check strictly the mobile media query block
    # Assuming it starts at line 1392
    lines = content.splitlines()
    media_start_line = 0
    for i, line in enumerate(lines):
        if "@media screen and (max-width: 768px)" in line:
            media_start_line = i + 1
            break
            
    if media_start_line > 0:
        print(f"Checking media query starting at line {media_start_line}")
        # Count braces from there to expected end
        sub_content = "\n".join(lines[media_start_line-1:])
        o = sub_content.count('{')
        c = sub_content.count('}')
        print(f"In substring from media query to end: {{={o}, }}={c}")

if __name__ == "__main__":
    check_structure(r"c:/Users/victo/PythonProjects/Naza/core/static/css/chat.css")
