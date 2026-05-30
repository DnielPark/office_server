import http.client, urllib.request, urllib.parse

HOST = "127.0.0.1"
PORT = 5050

# Auth
cj = urllib.request.HTTPCookieProcessor()
opener = urllib.request.build_opener(cj)
form = urllib.parse.urlencode({"password": "000000"}).encode()
req = urllib.request.Request("http://127.0.0.1:5050/auth/sungsan1", data=form)
opener.open(req)

# Get files page
rsp = opener.open("http://127.0.0.1:5050/files/sungsan1")
raw = rsp.read()
html = raw.decode("utf-8")

# Write full HTML for inspection
with open("E:\\project\\full_page.html", "w", encoding="utf-8") as f:
    f.write(html)

print("Written:", len(html), "bytes")
print("Contains topbar:", "topbar" in html)
print("Contains usage-bar-wrap:", "usage-bar-wrap" in html)
print("Contains file-table:", "file-table" in html)
print("Contains file-tbody:", "file-tbody" in html)
print("Contains empty-state:", "empty-state" in html)
print("Contains '비어 있습니다':", "비어 있습니다" in html)

# Check between usage bar close and content
idx = html.find("usage-text")
if idx >= 0:
    section = html[idx:idx+500]
    with open("E:\\project\\section_check.txt", "w", encoding="utf-8") as f:
        f.write(section)
    print("Section written")
