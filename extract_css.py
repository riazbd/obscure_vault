import os

def extract_css():
    with open('ui/index.html', 'r', encoding='utf-8') as f:
        lines = f.readlines()

    style_start = -1
    style_end = -1
    for i, line in enumerate(lines):
        if '<style>' in line:
            style_start = i
        elif '</style>' in line:
            style_end = i
            break

    if style_start != -1 and style_end != -1:
        css_content = lines[style_start+1:style_end]
        os.makedirs('ui/css', exist_ok=True)
        with open('ui/css/main.css', 'w', encoding='utf-8') as f:
            f.writelines(css_content)
        
        new_html = lines[:style_start] + ['<link rel="stylesheet" href="css/main.css">\n'] + lines[style_end+1:]
        with open('ui/index.html', 'w', encoding='utf-8') as f:
            f.writelines(new_html)
        print("CSS extracted successfully.")
    else:
        print("Could not find <style> tags.")

if __name__ == "__main__":
    extract_css()
