import http.client, urllib.request, urllib.parse

HOST = "127.0.0.1"
PORT = 5050

# Auth with correct password
cj = urllib.request.HTTPCookieProcessor()
opener = urllib.request.build_opener(cj)
form = urllib.parse.urlencode({"password": "000000"}).encode()
req = urllib.request.Request("http://127.0.0.1:5050/auth/sungsan1", data=form)
rsp = opener.open(req)
print("Auth:", rsp.status, "->", rsp.url)

# Get files page
rsp = opener.open("http://127.0.0.1:5050/files/sungsan1")
html = rsp.read().decode("utf-8")
print("Files:", rsp.status, len(html), "chars")
print("Has usage-bar:", "usage-bar" in html)
print("Has entries:", "file-table" in html)

# Check for error
if "Internal Server Error" in html or "Traceback" in html:
    import re
    m = re.search(r"<pre>(.*?)</pre>", html, re.DOTALL)
    if m:
        print("ERROR:", m.group(1)[:500])
    else:
        print("Has error:", html[-500:])
elif "비밀번호" in html and "인증" in html:
    print("Still on auth page - login failed!")
else:
    print("Page OK")
