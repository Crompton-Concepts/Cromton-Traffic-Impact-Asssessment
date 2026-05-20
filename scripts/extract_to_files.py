import os

base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
html_path = os.path.join(base, 'index.html')

html = open(html_path, encoding='utf-8').read()
lines = html.split('\n')

# Part A: lines 1-20 (0-indexed 0-19) — head metadata before <style>
part_a = lines[0:20]
# CSS is lines 21-4005 (0-indexed 20-4004), <style> at idx 20, </style> at idx 4005
# Part B: HTML body content, lines 4007-6424 (0-indexed 4006-6423)
part_b = lines[4006:6424]
# Inline JS block 1: 6425-30655 (0-indexed 6424-30654), block 2: 30656-31081 (0-indexed 30655-31080)
# Part D: Firebase SDK + local scripts, from line 31082 onward (0-indexed 31081+)
part_d = lines[31081:]

stylesheet_tag = '  <link rel="stylesheet" href="styles.css">'
app_script_tag = '<script src="app.js"></script>'

new_lines = part_a + [stylesheet_tag] + part_b + [app_script_tag] + part_d
new_html = '\n'.join(new_lines)

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(new_html)

print(f'index.html rewritten: {len(new_html):,} chars, {new_html.count(chr(10)):,} lines')

# Verify
vlines = new_html.split('\n')
for i, line in enumerate(vlines, 1):
    s = line.strip()
    if ('styles.css' in s or s == app_script_tag.strip()
            or 'gstatic' in s or 'firebase-config' in s or '</body>' in s):
        print(f'  Line {i}: {s[:100]}')
