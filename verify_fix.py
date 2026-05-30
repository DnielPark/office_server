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

with open("E:\\project\\full_page.html", "w", encoding="utf-8") as f:
    f.write(html)

print("script count:", html.count("<script>"))
print("/script count:", html.count("</script>"))
print("Match:", html.count("<script>") == html.count("</script>"))
print("Size:", len(html), "bytes")
print("Has content:", "content" in html)
print("Has file-table:", "file-table" in html)
