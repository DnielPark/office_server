"""
file_server_external.py  —  대외용 웹 파일 서버
포트  : 5050
공유  : E:\openshare
"""

from flask import (Flask, render_template, send_from_directory, send_file,
                   request, redirect, url_for, session, abort, jsonify, make_response)
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
import secrets, os, io, zipfile, json, smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))

SHARED_FOLDER = Path(r"E:\openshare")

# ── .env 로드 ─────────────────────────────────
load_dotenv()

# ── 시작 시 .env 누락 키 점검 ─────────────────
REQUIRED_KEYS = ["SUNGSAN1_PW", "SUNGSAN2_PW", "GUDONG1_PW", "GUDONG2_PW"]
missing = [k for k in REQUIRED_KEYS if not os.getenv(k)]
if missing:
    raise RuntimeError(f"[ERROR] .env에 다음 키가 없습니다: {', '.join(missing)}")

# ── 토큰 파일 경로 ───────────────────────────
TOKENS_FILE = Path(__file__).parent / "local_tokens.json"

# ── 토큰 헬퍼 ─────────────────────────────────
def load_tokens():
    if not TOKENS_FILE.exists():
        return {"allowed_emails": [], "tokens": {}, "pending_verifications": {}}
    try:
        with open(TOKENS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"allowed_emails": [], "tokens": {}, "pending_verifications": {}}

def save_tokens(data):
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_allowed_email(email):
    data = load_tokens()
    return email.lower() in [e.lower() for e in data.get("allowed_emails", [])]

def get_email_by_token(token):
    data = load_tokens()
    for email, info in data.get("tokens", {}).items():
        if info.get("token") == token:
            return email
    return None

def invalidate_token(email):
    data = load_tokens()
    data["tokens"].pop(email, None)
    save_tokens(data)

def send_verification_email(to_email, verify_link, code):
    """SMTP로 인증 메일 발송"""
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "465"))
    smtp_ssl = os.getenv("SMTP_SSL", "True").lower() == "true"
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user)

    # SMTP 미설정 시 콘솔 로그 (개발용)
    if not smtp_user or not smtp_pass:
        print(f"[DEV] 인증 메일: {to_email}")
        print(f"[DEV] 링크: {verify_link}")
        print(f"[DEV] 코드: {code}")
        return True

    subject = "[세모나라 파일서버] 로컬 폴더 인증 메일"

    html = f"""
    <html><body style="font-family: sans-serif; background: #f4f4f4; padding: 32px;">
    <div style="max-width: 520px; margin: 0 auto; background: #fff; border-radius: 12px; padding: 40px;">
      <h2 style="margin-top: 0; color: #222;">🔑 로컬 폴더 인증</h2>
      <p style="color: #555; line-height: 1.6; font-size: 14px;">
        아래 버튼을 클릭하면 로컬 폴더에 접속할 수 있는 토큰이 발급됩니다.
      </p>
      <div style="text-align: center; margin: 28px 0;">
        <a href="{verify_link}" style="
          display: inline-block;
          background: #2f81f7;
          color: #fff;
          font-size: 15px;
          font-weight: 600;
          text-decoration: none;
          padding: 14px 36px;
          border-radius: 8px;
        ">✅ 인증하고 접속하기</a>
      </div>
      <p style="color: #888; font-size: 12px;">
        또는 브라우저에서 다음 링크를 직접 열어주세요:<br>
        <a href="{verify_link}" style="color: #2f81f7; word-break: break-all;">{verify_link}</a>
      </p>
      <p style="color: #888; font-size: 12px; margin-top: 20px;">
        인증 코드: <strong>{code}</strong> (10분 후 만료)
      </p>
      <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;">
      <p style="color: #aaa; font-size: 11px;">
        본 메일은 요청하신 경우에만 발송됩니다. 요청하지 않았다면 무시해주세요.
      </p>
    </div></body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html"))

    try:
        if smtp_ssl:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx) as server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_from, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_from, [to_email], msg.as_string())
        print(f"[MAIL] 인증 메일 발송 완료 → {to_email}")
        return True
    except Exception as e:
        print(f"[MAIL ERROR] {e}")
        return False

def get_token_from_request():
    """요청에서 토큰 추출 (쿠키 → 헤더 순)"""
    return request.cookies.get("local_token") or request.headers.get("X-Local-Token", "")

# ── 공구 설정 ─────────────────────────────────
PROJECTS = {
    "sungsan1": {"name": "성산1공구", "password": os.getenv("SUNGSAN1_PW")},
    "sungsan2": {"name": "성산2공구", "password": os.getenv("SUNGSAN2_PW")},
    "gudong1":  {"name": "구동1공구", "password": os.getenv("GUDONG1_PW")},
    "gudong2":  {"name": "구동2공구", "password": os.getenv("GUDONG2_PW")},
}

# ─────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────
def fmt_size(size):
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.1f} TB"

def is_authenticated(project_key):
    return session.get(f"auth_{project_key}") is True

def get_entries(folder: Path, project_key: str, sub: str):
    entries = []
    try:
        for item in sorted(folder.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            rel = f"{sub}/{item.name}".lstrip("/") if sub else item.name
            mtime = datetime.fromtimestamp(item.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            size = fmt_size(item.stat().st_size) if item.is_file() else "—"
            entries.append({
                "name": item.name,
                "rel_path": rel,
                "is_dir": item.is_dir(),
                "mtime": mtime,
                "size": size,
            })
    except PermissionError:
        pass
    return entries

def build_breadcrumbs(sub: str):
    parts = [p for p in sub.split("/") if p]
    crumbs = []
    for i, part in enumerate(parts):
        crumbs.append({"name": part, "path": "/".join(parts[:i+1])})
    return crumbs

def safe_path(base: Path, subpath: str) -> Path:
    target = base / subpath if subpath else base
    try:
        target.resolve().relative_to(base.resolve())
    except ValueError:
        abort(403)
    return target

# ─────────────────────────────────────────────
# 페이지 라우트
# ─────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", projects=PROJECTS)

@app.route("/auth/<project_key>", methods=["GET", "POST"])
def auth(project_key):
    if project_key not in PROJECTS:
        return redirect(url_for("index"))

    info = PROJECTS[project_key]
    error = False

    if request.method == "POST":
        if request.form.get("password", "") == info["password"]:
            session[f"auth_{project_key}"] = True
            return redirect(url_for("files", project_key=project_key))
        error = True

    return render_template("auth.html", project_name=info["name"], error=error)

@app.route("/files/<project_key>", defaults={"subpath": ""})
@app.route("/files/<project_key>/<path:subpath>")
def files(project_key, subpath):
    if project_key not in PROJECTS:
        return redirect(url_for("index"))
    if not is_authenticated(project_key):
        return redirect(url_for("auth", project_key=project_key))

    base = SHARED_FOLDER / project_key
    target = safe_path(base, subpath)

    if target.is_file():
        return send_from_directory(target.parent, target.name, as_attachment=True)
    if not target.is_dir():
        abort(404)

    entries = get_entries(target, project_key, subpath)
    breadcrumbs = build_breadcrumbs(subpath)
    parent_path = "/".join(subpath.split("/")[:-1]) if subpath else None

    return render_template(
        "files.html",
        project_key=project_key,
        project_name=PROJECTS[project_key]["name"],
        entries=entries,
        current_path=subpath,
        breadcrumbs=breadcrumbs,
        parent_path=parent_path,
    )

# ─────────────────────────────────────────────
# 내부망 전용 (IP 인증 없음)
# ─────────────────────────────────────────────
LOCAL_PREFIXES = ["127.0.0.1", "192.168.", "10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.", "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31."]

def is_local_ip():
    ip = request.remote_addr or ""
    return any(ip.startswith(p) for p in LOCAL_PREFIXES)


@app.route("/local", defaults={"subpath": ""})
@app.route("/local/<path:subpath>")
def local_browse(subpath):
    if not is_local_ip():
        token = get_token_from_request()
        if not token or not get_email_by_token(token):
            return redirect(url_for("local_auth"))

    target = safe_path(SHARED_FOLDER, subpath)

    if target.is_file():
        return send_from_directory(target.parent, target.name, as_attachment=True)
    if not target.is_dir():
        abort(404)

    entries = get_entries(target, "local", subpath)
    breadcrumbs = build_breadcrumbs(subpath)
    parent_path = "/".join(subpath.split("/")[:-1]) if subpath else None

    return render_template(
        "local.html",
        entries=entries,
        current_path=subpath,
        breadcrumbs=breadcrumbs,
        parent_path=parent_path,
    )


@app.route("/upload/<project_key>", defaults={"subpath": ""}, methods=["POST"])
@app.route("/upload/<project_key>/<path:subpath>", methods=["POST"])
def upload(project_key, subpath):
    if project_key not in PROJECTS:
        return redirect(url_for("index"))
    if not is_authenticated(project_key):
        return redirect(url_for("auth", project_key=project_key))

    base = SHARED_FOLDER / project_key
    target = safe_path(base, subpath)

    for f in request.files.getlist("files"):
        if f.filename:
            f.save(str(target / Path(f.filename).name))

    return redirect(url_for("files", project_key=project_key, subpath=subpath))

@app.route("/logout/<project_key>")
def logout(project_key):
    session.pop(f"auth_{project_key}", None)
    return redirect(url_for("index"))

@app.errorhandler(404)
def not_found(_):
    return redirect(url_for("index"))

# ─────────────────────────────────────────────
# 로컬 폴더 이메일 인증 라우트
# ─────────────────────────────────────────────

import time


@app.route("/local/auth")
def local_auth():
    """이메일 인증 페이지"""
    return render_template("local_auth.html")


@app.route("/local/send-verification", methods=["POST"])
def local_send_verification():
    """AJAX: 인증 메일 발송 요청"""
    data = request.get_json(force=True)
    email = data.get("email", "").strip().lower()

    if not email or "@" not in email:
        return jsonify({"ok": False, "msg": "올바른 이메일을 입력해주세요."})

    if not is_allowed_email(email):
        return jsonify({"ok": False, "msg": "등록되지 않은 이메일입니다. 관리자에게 문의하세요."})

    # 인증 코드 생성 (16자 hex, 10분 만료)
    code = secrets.token_hex(16)
    expires_at = time.time() + 600

    # 저장
    tokendata = load_tokens()
    tokendata.setdefault("pending_verifications", {})[email] = {
        "code": code,
        "expires_at": expires_at
    }
    save_tokens(tokendata)

    local_domain = os.getenv("LOCAL_DOMAIN", "http://localhost:5050")
    verify_link = f"{local_domain}/local/verify?email={email}&code={code}"

    ok = send_verification_email(email, verify_link, code)
    if ok:
        return jsonify({"ok": True, "msg": "인증 메일이 발송되었습니다."})
    else:
        return jsonify({"ok": False, "msg": "메일 발송에 실패했습니다. 관리자에게 문의하세요."})


@app.route("/local/verify")
def local_verify():
    """이메일 인증 링크 처리 → 토큰 발급"""
    email = request.args.get("email", "").strip().lower()
    code = request.args.get("code", "").strip()

    if not email or not code:
        return "잘못된 접근입니다.", 400

    tokendata = load_tokens()
    pending = tokendata.get("pending_verifications", {}).get(email)

    if not pending:
        return "인증 요청이 없습니다. 다시 시도해주세요.", 400

    if pending["code"] != code:
        return "올바르지 않은 인증 코드입니다.", 400

    if time.time() > pending["expires_at"]:
        tokendata["pending_verifications"].pop(email, None)
        save_tokens(tokendata)
        return "인증 코드가 만료되었습니다. 다시 인증해주세요.", 410

    # 인증 성공! 새 토큰 발행 (기존 무효화)
    new_token = secrets.token_hex(48)
    tokendata["tokens"][email] = {
        "token": new_token,
        "created_at": datetime.now().isoformat()
    }
    tokendata["pending_verifications"].pop(email, None)
    save_tokens(tokendata)

    print(f"[TOKEN] 토큰 발행: {email} → {new_token[:16]}...")

    # 쿠키 저장 후 리다이렉트
    resp = make_response(redirect(url_for("local_browse")))
    resp.set_cookie(
        "local_token", new_token,
        max_age=30*24*3600,
        httponly=True,
        secure=False,
        samesite="Lax",
        path="/"
    )
    return resp


@app.route("/local/logout")
def local_logout():
    """토큰 삭제 + 쿠키 제거"""
    token = get_token_from_request()
    email = get_email_by_token(token)
    if email:
        invalidate_token(email)
    resp = make_response(redirect(url_for("local_auth")))
    resp.delete_cookie("local_token", path="/")
    return resp

# ─────────────────────────────────────────────
# API 라우트 (JS fetch 전용)
# ─────────────────────────────────────────────

@app.route("/api/mkdir", methods=["POST"])
def api_mkdir():
    data = request.get_json()
    project_key = data.get("project", "")
    subpath     = data.get("path", "")
    folder_name = data.get("folder_name", "").strip()

    if project_key not in PROJECTS:
        return jsonify({"ok": False, "msg": "잘못된 프로젝트입니다."})
    if not is_authenticated(project_key):
        return jsonify({"ok": False, "msg": "인증이 필요합니다."})
    if not folder_name:
        return jsonify({"ok": False, "msg": "폴더명을 입력하세요."})

    base = SHARED_FOLDER / project_key
    target = safe_path(base, subpath)
    new_folder = target / folder_name

    if new_folder.exists():
        return jsonify({"ok": False, "msg": "이미 존재하는 폴더입니다."})

    try:
        new_folder.mkdir(parents=False)
        return jsonify({"ok": True, "msg": f"'{folder_name}' 폴더가 생성되었습니다."})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})


@app.route("/api/delete", methods=["POST"])
def api_delete():
    data = request.get_json()
    project_key = data.get("project", "")
    subpath     = data.get("path", "")

    if project_key not in PROJECTS:
        return jsonify({"ok": False, "msg": "잘못된 프로젝트입니다."})
    if not is_authenticated(project_key):
        return jsonify({"ok": False, "msg": "인증이 필요합니다."})

    base = SHARED_FOLDER / project_key
    target = safe_path(base, subpath)

    if not target.exists():
        return jsonify({"ok": False, "msg": "존재하지 않는 파일/폴더입니다."})

    try:
        if target.is_file():
            target.unlink()
            return jsonify({"ok": True, "msg": "파일이 삭제되었습니다."})
        elif target.is_dir():
            contents = list(target.iterdir())
            if contents:
                return jsonify({"ok": False, "msg": "내부 파일 삭제후 폴더 삭제하세요!!"})
            target.rmdir()
            return jsonify({"ok": True, "msg": "폴더가 삭제되었습니다."})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})


@app.route("/api/download-selected", methods=["POST"])
def api_download_selected():
    data = request.get_json()
    project_key = data.get("project", "")
    paths = data.get("paths", [])

    if project_key not in PROJECTS:
        return jsonify({"ok": False, "msg": "잘못된 프로젝트입니다."}), 400
    if not is_authenticated(project_key):
        return jsonify({"ok": False, "msg": "인증이 필요합니다."}), 401
    if not paths:
        return jsonify({"ok": False, "msg": "선택된 파일이 없습니다."}), 400

    base = SHARED_FOLDER / project_key
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            target = safe_path(base, p)
            if target.is_file():
                zf.write(str(target), Path(p).name)

    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name="files.zip",
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)