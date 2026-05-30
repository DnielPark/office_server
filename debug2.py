s = open("E:\\project\\full_page.html", encoding="utf-8").read()

# Find content div
idx = s.find('<div class="content">')
print("Found content at:", idx)
after = s[idx:]
print(after[:800])
