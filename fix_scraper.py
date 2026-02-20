filepath = r'c:\Users\20203525\Documents\2025 2026\WB4U\wb4y-webscraper\Tableau post approach\scraper4.py'
with open(filepath, 'r') as f:
    content = f.read()

# Fix the page.click() syntax 
old = 'await page.click("canvas, svg, [data-viz-content]", {"position": {"x": 80, "y": 58}})'
new = 'await page.click("canvas, svg, [data-viz-content]", position={"x": 80, "y": 58})'

if old in content:
    content = content.replace(old, new)
    with open(filepath, 'w') as f:
        f.write(content)
    print('✓ Fixed: page.click() syntax error')
else:
    print('Pattern not found - checking for variations...')
    if 'await page.click' in content:
        print('Found page.click() call but pattern differs')
        # Show the actual line
        for i, line in enumerate(content.split('\n')):
            if 'await page.click' in line:
                print(f'Line {i+1}: {line}')
