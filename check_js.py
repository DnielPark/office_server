# Check for template errors in the rendered HTML
s = open("E:\\project\\full_page.html", encoding="utf-8").read()

# Look for potential issues in JavaScript sections
# Find all script blocks
import re

# Check for < in JavaScript (outside of strings)
scripts = re.findall(r'<script>(.*?)</script>', s, re.DOTALL)
for i, script in enumerate(scripts):
    # Check for problematic </ in strings (template literals)
    if "</" in script:
        print(f"Script block {i}: Contains '</' - potential issue!")
        # Find the context
        for j, line in enumerate(script.split('\n')):
            if '</' in line:
                print(f"  Line {j}: {line.strip()[:100]}")

# Also check the error param script section
idx = s.find("error") 
if idx > 0:
    section = s[idx-20:idx+200]
    with open("E:\\project\\section_error.txt", "w", encoding="utf-8") as f:
        f.write(section)

print("Done checking")
