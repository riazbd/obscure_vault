import os

def extract_js():
    with open('ui/index.html', 'r', encoding='utf-8') as f:
        lines = f.readlines()

    script_start = -1
    script_end = -1
    for i, line in enumerate(lines):
        if '<script>' in line:
            script_start = i
        elif '</script>' in line:
            script_end = i
            break

    if script_start != -1 and script_end != -1:
        js_content = lines[script_start+1:script_end]
        os.makedirs('ui/js', exist_ok=True)
        with open('ui/js/main.js', 'w', encoding='utf-8') as f:
            f.writelines(js_content)
        
        new_html = lines[:script_start] + ['<script type="module" src="js/main.js"></script>\n'] + lines[script_end+1:]
        with open('ui/index.html', 'w', encoding='utf-8') as f:
            f.writelines(new_html)
        print("JS extracted successfully.")
    else:
        print("Could not find <script> tags.")

if __name__ == "__main__":
    extract_js()
