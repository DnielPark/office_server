"""
file_server_external.py  —  대외용 웹 파일 서버
포트  : 5050
공유  : E:/openshare
"""

from flask import (Flask, render_template, send_from_directory, send_file,
                   request, redirect, url_for, session, abort, jsonify, make_response)
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import secrets, os, io, zipfile, json, smtplib, ssl, random, time, shutil, tempfile
from openai import OpenAI
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from logging.handlers import RotatingFileHandler

# ── 로깅 설정 ─────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

log_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# 파일 로거 (5MB × 3개 = 최대 15MB)
file_handler = RotatingFileHandler(
    str(LOG_DIR / "server.log"),
    maxBytes=5*1024*1024,
    backupCount=3,
    encoding="utf-8"
)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

# 에러 전용 로거
error_handler = RotatingFileHandler(
    str(LOG_DIR / "error.log"),
    maxBytes=5*1024*1024,
    backupCount=3,
    encoding="utf-8"
)
error_handler.setFormatter(log_formatter)
error_handler.setLevel(logging.ERROR)

# 콘솔 로거
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.DEBUG)

# Flask 루트 로거에 핸들러 등록
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(file_handler)
root_logger.addHandler(error_handler)
root_logger.addHandler(console_handler)

# Flask/Werkzeug 로그 레벨 조정
logging.getLogger("werkzeug").setLevel(logging.WARNING)

# ── 파일 작업 이력 ────────────────────────────────
# file_history.json 에 모든 파일 작업(업로드/삭제/이동/복사/폴더생성)을 기록
# 추후 복구/감사 기능 구현을 위한 기반 데이터
HISTORY_FILE = os.path.join(os.path.dirname(__file__), "file_history.json")
HISTORY_MAX = 2000  # 최대 보관 건수 (초과 시 오래된 순 제거)


def _atomic_write_json(path, data):
    """임시 파일로 쓴 뒤 os.replace()로 원자적 교체.
    쓰기 도중 강제 종료돼도 원본 파일은 손상되지 않는다."""
    path = str(path)
    dir_ = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _append_history(action: str, project: str, ip: str, original: str,
                    backup: str = None, extra: dict = None):
    """
    파일 작업 이력을 file_history.json 에 append.
    - action : upload | delete | move | copy | mkdir
    - project: 프로젝트 키 ("sungsan1" 등) 또는 "local"
    - ip     : 요청자 IP
    - original: 작업 대상 (project 기준 상대경로)
    - backup : 삭제/덮어쓰기 시 .backup 경로
    - extra  : 이동/복사 시 dest 등 추가 정보
    """
    record = {
        "action": action,
        "project": project,
        "ip": ip,
        "original": original,
        "backup": backup,
        "extra": extra or {},
        "time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    }
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        else:
            history = []

        history.append(record)

        if len(history) > HISTORY_MAX:
            history = history[-HISTORY_MAX:]

        _atomic_write_json(HISTORY_FILE, history)
    except Exception as e:
        logging.error(f"file_history 기록 실패: {e}")


load_dotenv()  # .env 로드 — app.secret_key 보다 먼저 실행되어야 함

app = Flask(__name__)
_sk = os.getenv("SECRET_KEY")
if not _sk:
    logging.warning("SECRET_KEY 미설정 — 임시 키 사용. 재시작 시 세션이 풀립니다. .env에 SECRET_KEY를 고정하세요.")
    _sk = secrets.token_hex(32)
app.secret_key = _sk
# 업로드 하드 상한 (백스톱). 정상 100MB + 멀티파트 오버헤드 여유 10MB.
app.config['MAX_CONTENT_LENGTH'] = 110 * 1024 * 1024

# ── 요청 로깅 ────────────────────────────────
@app.before_request
def log_request():
    path = request.path
    # 정적 파일/API 노이즈 제외
    if not path.startswith("/static") and not path.startswith("/api/download"):
        logging.info(f"→ {request.method} {path} ({request.remote_addr})")

@app.after_request
def log_response(response):
    path = request.path
    if not path.startswith("/static"):
        logging.info(f"← {response.status_code} {request.method} {path}")
    return response

SHARED_FOLDER = Path(r"E:\openshare")

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
    except Exception:
        return {"allowed_emails": [], "tokens": {}, "pending_verifications": {}}

def save_tokens(data):
    _atomic_write_json(TOKENS_FILE, data)

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
            # .backup 폴더는 UI에서 숨김
            if item.name == ".backup":
                continue
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

# ── 파일명 인코딩 헬퍼 ────────────────────────
def decode_filename(fname):
    """
    브라우저가 CP949로 보낸 한글 파일명 복원.
    Werkzeug가 Latin-1로 잘못 디코딩 → 물음표 등 깨짐 발생.
    깨진 경우에만 latin-1 → cp949 재변환.
    """
    # 물음표 포함 = 인코딩 깨짐
    if "?" in fname or "\ufffd" in fname:
        try:
            return fname.encode("latin-1").decode("cp949")
        except (UnicodeEncodeError, UnicodeDecodeError, LookupError):
            pass
    return fname

# ── 용량 관련 헬퍼 ────────────────────────────
import time as _time

_usage_cache = {}  # {project_key: (timestamp_sec, size_bytes)}

def get_folder_size(path: Path) -> int:
    """폴더 전체 용량 (바이트), .backup 제외"""
    total = 0
    try:
        for item in path.rglob("*"):
            if item.name == ".backup":
                continue
            if item.is_file():
                total += item.stat().st_size
    except (PermissionError, OSError):
        pass
    return total

def get_project_usage(project_key: str) -> dict:
    """프로젝트 사용량 + 최대치 (캐시 30초)"""
    now = _time.time()
    cached = _usage_cache.get(project_key)
    if cached and now - cached[0] < 30:
        used = cached[1]
    else:
        base = SHARED_FOLDER / project_key
        if base.exists():
            used = get_folder_size(base)
        else:
            used = 0
        _usage_cache[project_key] = (now, used)

    max_bytes = int(os.getenv("PROJECT_MAX_SIZE_GB", "10")) * 1024**3
    pct = round(used / max_bytes * 100, 1) if max_bytes > 0 else 0
    return {
        "used": used,
        "max": max_bytes,
        "pct": min(pct, 100),
        "used_str": fmt_size(used),
        "max_str": fmt_size(max_bytes),
        "free_str": fmt_size(max_bytes - used) if used <= max_bytes else "0 B",
    }

# ── 로그인 보안 (자동화 방어) ───────────────
MAX_LOGIN_ATTEMPTS = 3  # 3회 실패 시 덧셈 문제 출제

def generate_math_challenge():
    """두자리수 덧셈 문제 생성"""
    a = random.randint(10, 99)
    b = random.randint(1, 50)
    answer = a + b
    return {"question": f"{a} + {b} = ?", "answer": str(answer)}

def needs_challenge(project_key):
    """현재 세션에서 로그인 시도 횟수 확인"""
    key = f"login_fails_{project_key}"
    return session.get(key, 0) >= MAX_LOGIN_ATTEMPTS

# ─────────────────────────────────────────────
# 페이지 라우트
# ─────────────────────────────────────────────
@app.route("/")
def index():
    resp = make_response(render_template("index.html", projects=PROJECTS))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/devnote")
def devnote():
    resp = make_response(render_template("devnote.html", projects=PROJECTS))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

@app.route("/devnote/flood-defense")
def flood_defense_toc():
    return render_template("flood_defense.html")


@app.route("/devnote/flood-defense/<int:section>")
def flood_defense_section(section):
    if section < 1 or section > 8:
        return redirect(url_for("flood_defense_toc"))
    return render_template(f"flood_defense/section_{section:02d}.html")


@app.route("/devnote/doc-builder")
def doc_builder_index():
    return render_template("doc_builder/index.html")


@app.route("/devnote/doc-builder/sunday")
def doc_builder_sunday():
    return render_template("doc_builder/sunday_chat.html")


@app.route("/devnote/doc-builder/sunday/chat", methods=["POST"])
def doc_builder_sunday_chat():
    """일요일 공사 승인 요청서 채팅 API (Phase 2-fix: DeepSeek V3)"""
    data = request.get_json(force=True)
    messages = data.get("messages", [])

    SUNDAY_CHAT_SYSTEM = (
        "당신은 건설 현장 문서 작성 보조 AI입니다.\n"
        "사용자와 대화하며 일요일 공사 승인 요청서의 필드를 하나씩 채워나갑니다.\n"
        "응답은 반드시 JSON으로만 반환합니다:\n"
        "{\n"
        '  "reply": "사용자에게 보여줄 자연어 메시지",\n'
        '  "fields": {\n'
        '    "work_date": null 또는 "채워진 값",\n'
        '    "work_time": null 또는 "채워진 값",\n'
        '    "location": null 또는 "채워진 값",\n'
        '    "work_reason": null 또는 ["reason_2"],\n'
        '    "main_work_content": null 또는 "채워진 값",\n'
        '    "safety_plan": null 또는 "채워진 값",\n'
        '    "worker_count": null 또는 "채워진 값",\n'
        '    "equipment": null 또는 "채워진 값",\n'
        '    "site_manager": null 또는 "채워진 값",\n'
        '    "emergency_plan": null 또는 "채워진 값"\n'
        "  },\n"
        '  "next_question": "다음으로 물어볼 항목 key 또는 null(완료)"\n'
        "}\n"
        "미입력 필드는 null, 완료된 필드는 이전 값 유지.\n"
        "JSON 외 다른 텍스트 절대 출력 금지."
    )

    try:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return jsonify({
                "reply": "⚠️ DeepSeek API 키가 설정되지 않았습니다. 관리자에게 문의하세요.",
                "fields": {},
                "next_question": None
            })

        client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com"
        )

        api_messages = [{"role": "system", "content": SUNDAY_CHAT_SYSTEM}]
        for m in messages:
            api_messages.append({"role": m["role"], "content": m["content"]})

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=api_messages,
            response_format={"type": "json_object"},
            max_tokens=1000
        )

        result = json.loads(response.choices[0].message.content)
        return jsonify(result)

    except Exception as e:
        app.logger.error(f"DeepSeek API error: {e}")
        return jsonify({
            "reply": "서버 오류가 발생했습니다. 다시 시도해주세요.",
            "fields": {},
            "next_question": None
        })


@app.route("/auth/<project_key>", methods=["GET", "POST"])
def auth(project_key):
    if project_key not in PROJECTS:
        return redirect(url_for("index"))

    info = PROJECTS[project_key]
    error = False
    challenge = None
    challenge_error = None
    fail_key = f"login_fails_{project_key}"

    if request.method == "POST":
        password = request.form.get("password", "")
        user_answer = request.form.get("challenge_answer", "")
        challenge_answer = session.pop(f"challenge_{project_key}", None)

        # 챌린지 검증 (진행 중이면 먼저 확인)
        if challenge_answer is not None:
            if user_answer == challenge_answer:
                # 챌린지 통과 → 비밀번호 검증
                if password == info["password"]:
                    session.pop(fail_key, None)
                    session[f"auth_{project_key}"] = True
                    return redirect(url_for("files", project_key=project_key))
                error = True
                challenge_error = "비밀번호가 올바르지 않습니다."
            else:
                error = True
                challenge_error = "정답이 틀렸습니다."
        else:
            # 일반 로그인 시도
            if password == info["password"]:
                session.pop(fail_key, None)
                session[f"auth_{project_key}"] = True
                return redirect(url_for("files", project_key=project_key))
            error = True
            session[fail_key] = session.get(fail_key, 0) + 1

        # 챌린지 필요 여부
        if needs_challenge(project_key):
            ch = generate_math_challenge()
            challenge = ch["question"]
            session[f"challenge_{project_key}"] = ch["answer"]

    return render_template("auth.html", project_name=info["name"], error=error, challenge=challenge, challenge_error=challenge_error)

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
        usage=get_project_usage(project_key),
    )


@app.route("/local", defaults={"subpath": ""})
@app.route("/local/<path:subpath>")
def local_browse(subpath):
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


# ── 로컬 폴더 API ────────────────────────────
LOCAL_BACKUP = SHARED_FOLDER / ".backup"
MAX_UPLOAD_MB = 100  # 파일당 최대 업로드 크기 (MB)


@app.route("/local-upload", defaults={"subpath": ""}, methods=["POST"])
@app.route("/local-upload/<path:subpath>", methods=["POST"])
def local_upload(subpath):
    token = get_token_from_request()
    if not token or not get_email_by_token(token):
        return redirect(url_for("local_auth"))

    target = safe_path(SHARED_FOLDER, subpath)
    errors = []

    # 용량 체크
    upload_size = request.content_length or 0
    max_bytes = MAX_UPLOAD_MB * 1024 * 1024
    if upload_size > max_bytes:
        errors.append(f"파일 크기가 {MAX_UPLOAD_MB}MB를 초과합니다.")
        return redirect(url_for("local_browse", subpath=subpath, error=";;".join(errors)))

    for f in request.files.getlist("files"):
        if not f.filename:
            continue
        fname = decode_filename(f.filename)
        invalid = set('\\/:*?"<>|')
        if any(c in invalid for c in Path(fname).name):
            errors.append(f"'{fname}' 파일명에 사용할 수 없는 문자가 있습니다.")
            continue
        try:
            f.save(str(target / Path(fname).name))
        except OSError:
            errors.append(f"'{fname}' 저장 실패")
    if errors:
        return redirect(url_for("local_browse", subpath=subpath, error=";;".join(errors)))
    return redirect(url_for("local_browse", subpath=subpath))


@app.route("/local/api/mkdir", methods=["POST"])
def local_api_mkdir():
    token = get_token_from_request()
    if not token or not get_email_by_token(token):
        return jsonify({"ok": False, "msg": "인증이 필요합니다."}), 401

    data = request.get_json(force=True)
    subpath = data.get("path", "")
    folder_name = data.get("folder_name", "").strip()

    if not folder_name:
        return jsonify({"ok": False, "msg": "폴더명을 입력하세요."})

    invalid = set('\\/:*?"<>|')
    if any(c in invalid for c in folder_name):
        return jsonify({"ok": False, "msg": "폴더명에 \\ / : * ? \" < > | 를 사용할 수 없습니다."})

    target = safe_path(SHARED_FOLDER, subpath)
    new_folder = target / folder_name
    if new_folder.exists():
        return jsonify({"ok": False, "msg": "이미 존재하는 폴더입니다."})
    try:
        new_folder.mkdir(parents=False)
        _append_history("mkdir", "local", request.remote_addr,
                        f"local/{subpath}/{folder_name}" if subpath else f"local/{folder_name}")
        return jsonify({"ok": True, "msg": f"'{folder_name}' 폴더 생성됨"})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})


@app.route("/local/api/delete", methods=["POST"])
def local_api_delete():
    token = get_token_from_request()
    if not token or not get_email_by_token(token):
        return jsonify({"ok": False, "msg": "인증이 필요합니다."}), 401

    data = request.get_json(force=True)
    subpath = data.get("path", "")
    target = safe_path(SHARED_FOLDER, subpath)

    if not target.exists():
        return jsonify({"ok": False, "msg": "존재하지 않는 파일/폴더입니다."})

    try:
        LOCAL_BACKUP.mkdir(exist_ok=True)
        dest = LOCAL_BACKUP / target.name
        if dest.exists():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            if target.is_file():
                dest = LOCAL_BACKUP / f"{target.stem}_{ts}{target.suffix}"
            else:
                dest = LOCAL_BACKUP / f"{target.name}_{ts}"
        target.rename(dest)
        _append_history("delete", "local", request.remote_addr,
                        f"local/{subpath}", backup=str(dest))
        return jsonify({"ok": True, "msg": f"'{target.name}'을(를) .backup으로 이동"})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})
@app.route("/upload/<project_key>", defaults={"subpath": ""}, methods=["POST"])
@app.route("/upload/<project_key>/<path:subpath>", methods=["POST"])
def upload(project_key, subpath):
    if project_key not in PROJECTS:
        return redirect(url_for("index"))
    if not is_authenticated(project_key):
        return redirect(url_for("auth", project_key=project_key))

    base = SHARED_FOLDER / project_key
    target = safe_path(base, subpath)

    usage = get_project_usage(project_key)
    remaining = usage["max"] - usage["used"]
    total_upload = request.content_length or 0

    if total_upload > remaining:
        return redirect(url_for("files", project_key=project_key, subpath=subpath, error="over"))

    max_bytes = MAX_UPLOAD_MB * 1024 * 1024
    if total_upload > max_bytes:
        return redirect(url_for("files", project_key=project_key, subpath=subpath, error="over"))

    errors = []
    for f in request.files.getlist("files"):
        if not f.filename:
            continue
        fname = decode_filename(f.filename)
        # Windows 금지 문자 체크
        invalid = set('\\/:*?"<>|')
        if any(c in invalid for c in Path(fname).name):
            errors.append(f"'{fname}' 파일명에 사용할 수 없는 문자가 있습니다.")
            continue
        try:
            f.save(str(target / Path(fname).name))
            _append_history("upload", project_key, request.remote_addr,
                            f"{project_key}/{subpath}/{fname}" if subpath else f"{project_key}/{fname}")
        except OSError:
            errors.append(f"'{fname}' 파일을 저장할 수 없습니다. 파일명을 확인해주세요.")

    if errors:
        return redirect(url_for("files", project_key=project_key, subpath=subpath, error=";;".join(errors)))

    return redirect(url_for("files", project_key=project_key, subpath=subpath))

@app.route("/logout/<project_key>")
def logout(project_key):
    session.pop(f"auth_{project_key}", None)
    return redirect(url_for("index"))


@app.route("/change-password/<project_key>", methods=["GET", "POST"])
def change_password(project_key):
    """공구 비밀번호 변경"""
    if project_key not in PROJECTS:
        return redirect(url_for("index"))

    if request.method == "GET":
        if not is_authenticated(project_key):
            return redirect(url_for("auth", project_key=project_key))
        return render_template(
            "change_password.html",
            project_key=project_key,
            project_name=PROJECTS[project_key]["name"]
        )

    # POST: 비밀번호 변경 처리
    if not is_authenticated(project_key):
        return jsonify({"ok": False, "msg": "인증이 필요합니다."}), 401

    data = request.get_json(force=True)
    old_pw = data.get("old_pw", "")
    new_pw = data.get("new_pw", "")

    # 현재 비밀번호 확인
    if old_pw != PROJECTS[project_key]["password"]:
        return jsonify({"ok": False, "msg": "현재 비밀번호가 일치하지 않습니다."})

    # 새 비밀번호 검증
    if len(new_pw) < 4:
        return jsonify({"ok": False, "msg": "비밀번호는 4자 이상이어야 합니다."})

    # .env 키 매핑
    ENV_KEYS = {
        "sungsan1": "SUNGSAN1_PW",
        "sungsan2": "SUNGSAN2_PW",
        "gudong1":  "GUDONG1_PW",
        "gudong2":  "GUDONG2_PW",
    }
    env_key = ENV_KEYS.get(project_key)
    if not env_key:
        return jsonify({"ok": False, "msg": "잘못된 프로젝트입니다."})

    try:
        # .env 파일 업데이트
        from dotenv import set_key
        env_path = Path(__file__).parent / ".env"
        set_key(str(env_path), env_key, new_pw)

        # 메모리 업데이트
        PROJECTS[project_key]["password"] = new_pw

        print(f"[PW] {project_key} 비밀번호 변경됨")
        return jsonify({"ok": True, "msg": "비밀번호가 변경되었습니다."})
    except Exception as e:
        print(f"[PW ERROR] {e}")
        return jsonify({"ok": False, "msg": f"파일 쓰기 오류: {e}"})

@app.errorhandler(403)
def forbidden(_):
    return render_template("local_auth.html"), 403


@app.errorhandler(404)
def not_found(_):
    return redirect(url_for("index"))


@app.errorhandler(413)
def too_large(_):
    return "업로드 용량이 너무 큽니다 (최대 100MB).", 413

# ─────────────────────────────────────────────
# 로컬 폴더 이메일 인증 라우트
# ─────────────────────────────────────────────


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
        secure=True,
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
# 로컬 폴더 관리자 페이지
# ─────────────────────────────────────────────

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "daeho1001@nate.com")


def is_admin():
    """현재 요청이 관리자(ADMIN_EMAIL)인지 확인"""
    token = get_token_from_request()
    email = get_email_by_token(token)
    return email == ADMIN_EMAIL


@app.route("/local/admin")
def local_admin():
    """토큰 관리자 페이지"""
    if not is_admin():
        abort(403)

    tokendata = load_tokens()
    return render_template(
        "local_admin.html",
        tokens=tokendata.get("tokens", {}),
        allowed_emails=tokendata.get("allowed_emails", []),
        admin_email=ADMIN_EMAIL,
    )


@app.route("/local/admin/add-email", methods=["POST"])
def local_admin_add_email():
    """허용 이메일 추가"""
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403

    data = request.get_json(force=True)
    email = data.get("email", "").strip().lower()

    if not email or "@" not in email:
        return jsonify({"ok": False, "msg": "올바른 이메일을 입력해주세요."})

    tokendata = load_tokens()
    if email in [e.lower() for e in tokendata.get("allowed_emails", [])]:
        return jsonify({"ok": False, "msg": "이미 등록된 이메일입니다."})

    tokendata.setdefault("allowed_emails", []).append(email)
    save_tokens(tokendata)
    print(f"[ADMIN] 이메일 추가됨: {email}")
    return jsonify({"ok": True, "msg": f"'{email}' 추가 완료"})


@app.route("/local/admin/remove-email", methods=["POST"])
def local_admin_remove_email():
    """허용 이메일 삭제"""
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403

    data = request.get_json(force=True)
    email = data.get("email", "").strip().lower()

    if not email:
        return jsonify({"ok": False, "msg": "이메일을 입력해주세요."})

    if email == ADMIN_EMAIL:
        return jsonify({"ok": False, "msg": "관리자 이메일은 삭제할 수 없습니다."})

    tokendata = load_tokens()
    cleaned = [e for e in tokendata.get("allowed_emails", []) if e.lower() != email]
    if len(cleaned) == len(tokendata.get("allowed_emails", [])):
        return jsonify({"ok": False, "msg": "등록되지 않은 이메일입니다."})

    tokendata["allowed_emails"] = cleaned
    # 토큰도 함께 삭제
    tokendata["tokens"].pop(email, None)
    save_tokens(tokendata)
    print(f"[ADMIN] 이메일 삭제됨: {email}")
    return jsonify({"ok": True, "msg": f"'{email}' 제거 완료"})


@app.route("/local/admin/revoke-token", methods=["POST"])
def local_admin_revoke_token():
    """특정 이메일의 토큰 강제 취소"""
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403

    data = request.get_json(force=True)
    email = data.get("email", "").strip().lower()

    if not email:
        return jsonify({"ok": False, "msg": "이메일을 입력해주세요."})

    tokendata = load_tokens()
    if email not in tokendata.get("tokens", {}):
        return jsonify({"ok": False, "msg": "해당 이메일의 토큰이 없습니다."})

    tokendata["tokens"].pop(email, None)
    save_tokens(tokendata)
    print(f"[ADMIN] 토큰 취소됨: {email}")
    return jsonify({"ok": True, "msg": f"'{email}' 토큰 취소 완료"})

# ─────────────────────────────────────────────
# API 라우트 (JS fetch 전용)
# ─────────────────────────────────────────────

def _backup_to_dotbackup(base: Path, target: Path) -> Path:
    """파일/폴더를 .backup으로 이동. 충돌 시 타임스탬프 suffix. 반환: 백업된 경로"""
    backup_dir = base / ".backup"
    backup_dir.mkdir(exist_ok=True)

    dest = backup_dir / target.name
    if dest.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if target.is_file():
            dest = backup_dir / f"{target.stem}_{ts}{target.suffix}"
        else:
            dest = backup_dir / f"{target.name}_{ts}"

    target.rename(dest)
    return dest


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

    invalid = set('\\/:*?"<>|')
    if any(c in invalid for c in folder_name):
        return jsonify({"ok": False, "msg": "폴더명에 \\ / : * ? \" < > | 를 사용할 수 없습니다."})

    base = SHARED_FOLDER / project_key
    target = safe_path(base, subpath)
    new_folder = target / folder_name

    if new_folder.exists():
        return jsonify({"ok": False, "msg": "이미 존재하는 폴더입니다."})

    try:
        new_folder.mkdir(parents=False)
        _append_history("mkdir", project_key, request.remote_addr,
                        f"{project_key}/{subpath}/{folder_name}" if subpath else f"{project_key}/{folder_name}")
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
        backup_path = _backup_to_dotbackup(base, target)
        _append_history("delete", project_key, request.remote_addr,
                        subpath, backup=str(backup_path))
        return jsonify({"ok": True, "msg": f"'{target.name}'을(를) .backup으로 이동했습니다."})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})


@app.route("/api/delete-selected", methods=["POST"])
def api_delete_selected():
    data = request.get_json()
    project_key = data.get("project", "")
    paths = data.get("paths", [])

    if project_key not in PROJECTS:
        return jsonify({"ok": False, "msg": "잘못된 프로젝트입니다."})
    if not is_authenticated(project_key):
        return jsonify({"ok": False, "msg": "인증이 필요합니다."})

    base = SHARED_FOLDER / project_key
    success_count = 0
    errors = []

    for subpath in paths:
        target = safe_path(base, subpath)
        if not target.exists():
            errors.append(f"'{target.name}' 없음")
            continue
        try:
            backup_path = _backup_to_dotbackup(base, target)
            _append_history("delete", project_key, request.remote_addr,
                            subpath, backup=str(backup_path))
            success_count += 1
        except Exception as e:
            errors.append(f"'{target.name}': {e}")

    if success_count > 0:
        msg = f"{success_count}개를 .backup으로 이동했습니다."
        return jsonify({"ok": True, "msg": msg})
    else:
        return jsonify({"ok": False, "msg": ";;".join(errors)})


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


@app.route("/api/list-dirs", methods=["POST"])
def api_list_dirs():
    """지정 경로의 하위 폴더 목록 반환 (폴더 트리용)"""
    data = request.get_json()
    project_key = data.get("project", "")
    subpath = data.get("path", "")

    if project_key not in PROJECTS:
        return jsonify({"ok": False, "dirs": []})
    if not is_authenticated(project_key):
        return jsonify({"ok": False, "dirs": []})

    base = SHARED_FOLDER / project_key
    target = safe_path(base, subpath) if subpath else base

    if not target.is_dir():
        return jsonify({"ok": False, "dirs": []})

    dirs = []
    for entry in sorted(target.iterdir()):
        if entry.is_dir() and entry.name != ".backup":
            dirs.append(entry.name)

    return jsonify({"ok": True, "dirs": dirs})


@app.route("/api/move", methods=["POST"])
def api_move():
    """파일/폴더 이동"""
    data = request.get_json()
    project_key = data.get("project", "")
    paths = data.get("paths", [])
    dest = data.get("dest", "")
    overwrite = data.get("overwrite", False)

    if project_key not in PROJECTS:
        return jsonify({"ok": False, "msg": "잘못된 프로젝트입니다."})
    if not is_authenticated(project_key):
        return jsonify({"ok": False, "msg": "인증이 필요합니다."})
    if not paths or not dest:
        return jsonify({"ok": False, "msg": "선택된 파일과 대상 폴더가 필요합니다."})

    base = SHARED_FOLDER / project_key
    dest_path = safe_path(base, dest)

    if not dest_path.is_dir():
        return jsonify({"ok": False, "msg": "대상 폴더가 존재하지 않습니다."})

    # 1차: 충돌 검사
    conflicts = []
    for p in paths:
        src = safe_path(base, p)
        if not src.exists():
            return jsonify({"ok": False, "msg": f"'{src.name}'을(를) 찾을 수 없습니다."})
        target = dest_path / src.name
        if target.exists():
            conflicts.append(src.name)

    if conflicts and not overwrite:
        return jsonify({
            "ok": False, "conflict": True,
            "conflicts": conflicts,
            "msg": f"{len(conflicts)}개 파일 충돌"
        })

    # 2차: 실제 이동 (overwrite 시 기존 파일 백업)
    for p in paths:
        src = safe_path(base, p)
        target = dest_path / src.name

        if target.exists() and overwrite:
            _backup_to_dotbackup(base, target)

        try:
            shutil.move(str(src), str(target))
            _append_history("move", project_key, request.remote_addr,
                            p, extra={"dest": dest})
        except Exception as e:
            return jsonify({"ok": False, "msg": f"'{src.name}' 이동 실패: {e}"})

    return jsonify({"ok": True, "msg": f"{len(paths)}개 항목을 이동했습니다."})


@app.route("/api/copy", methods=["POST"])
def api_copy():
    """파일/폴더 복사"""
    data = request.get_json()
    project_key = data.get("project", "")
    paths = data.get("paths", [])
    dest = data.get("dest", "")

    if project_key not in PROJECTS:
        return jsonify({"ok": False, "msg": "잘못된 프로젝트입니다."})
    if not is_authenticated(project_key):
        return jsonify({"ok": False, "msg": "인증이 필요합니다."})
    if not paths or not dest:
        return jsonify({"ok": False, "msg": "선택된 파일과 대상 폴더가 필요합니다."})

    base = SHARED_FOLDER / project_key
    dest_path = safe_path(base, dest)

    if not dest_path.is_dir():
        return jsonify({"ok": False, "msg": "대상 폴더가 존재하지 않습니다."})

    renamed = []  # (원본명, 저장명)

    for idx, p in enumerate(paths):
        src = safe_path(base, p)
        if not src.exists():
            return jsonify({"ok": False, "msg": f"{idx+1}번째 항목 '{Path(p).name}'을(를) 찾을 수 없습니다."})

        # 충돌 시 suffix
        target = dest_path / src.name
        was_renamed = False
        if target.exists():
            stem = src.stem
            suffix = src.suffix
            counter = 1
            was_renamed = True
            while True:
                new_name = f"{stem}_copy{counter}{suffix}" if counter > 1 else f"{stem}_copy{suffix}"
                target = dest_path / new_name
                if not target.exists():
                    break
                counter += 1

        try:
            if src.is_file():
                shutil.copy2(str(src), str(target))
            else:
                shutil.copytree(str(src), str(target))
            _append_history("copy", project_key, request.remote_addr,
                            p, extra={"dest": dest,
                                      "renamed": target.name if was_renamed else None})
        except Exception as e:
            return jsonify({"ok": False, "msg": f"{idx+1}번째 '{src.name}' 복사 실패: {e}"})

        if was_renamed:
            renamed.append(f"{src.name} \u2192 {target.name}")

    # 메시지 구성
    if renamed:
        detail = "\n".join(f"\u2022 {r}" for r in renamed)
        msg = f"{len(paths)}\uac1c \ud56d\ubaa9 \ubcf5\uc0ac \uc644\ub8cc\n{detail}"
    else:
        msg = f"{len(paths)}개 항목을 복사했습니다."

    return jsonify({"ok": True, "msg": msg})


# ─────────────────────────────────────────────
# AI 채팅 API
# ─────────────────────────────────────────────

# 프로젝트 정보 데이터 (챗봇이 참고)
CHAT_PROJECT_INFO = {
    "sungsan1": {
        "name": "성산1공구",
        "desc": "성산천 재해복구사업 제1공구"
    },
    "sungsan2": {
        "name": "성산2공구",
        "desc": "성산천 재해복구사업 제2공구"
    },
    "gudong1": {
        "name": "구동1공구",
        "desc": "서천군 재해복구사업 구동지구 제1공구"
    },
    "gudong2": {
        "name": "구동2공구",
        "desc": "서천군 재해복구사업 구동지구 제2공구"
    }
}

CHAT_FLOOD_SECTIONS = [
    "비상연락망", "수방자재", "장비·인력",
    "수방조직", "긴급복구", "상황전파",
    "수위단계별 대응", "복구 우선순위"
]


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """AI 채팅 API — 초간단 프로젝트 도우미"""
    data = request.get_json()
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"reply": "무엇을 도와드릴까요? 😊"})

    msg = message.lower()

    # ── 인사 ──
    if any(g in msg for g in ["안녕", "하이", "헬로", "hi", "hello", "반가", "ㅎㅇ"]):
        return jsonify({
            "reply": "안녕하세요! 👋 서천군 재해복구사업 개발노트 도우미입니다.\n"
                     "궁금한 점이 있으면 물어봐 주세요!"
        })

    # ── 특정 공구 정보 (먼저 체크: 구체적 질문 우선) ──
    for key, info in CHAT_PROJECT_INFO.items():
        name_parts = [info["name"]]  # 전체 이름
        name_parts.append(info["name"][:-3] if len(info["name"]) > 3 else "")  # '성산1공구' -> '성산1'
        name_parts.append(key)  # 'sungsan1'
        if any(p and p in msg for p in name_parts):
            return jsonify({
                "reply": f"**{info['name']}** ({key})\n{info['desc']}\n\n"
                         f"파일을 보려면 메인 페이지에서 해당 카드를 클릭하세요."
            })

    # ── 프로젝트 목록 ──
    if any(w in msg for w in ["프로젝트", "목록"]):
        names = "\n".join(f"  • **{k}** — {v['name']}" for k, v in CHAT_PROJECT_INFO.items())
        return jsonify({
            "reply": f"현재 등록된 프로젝트입니다: \n{names}\n\n"
                     f"각 프로젝트를 클릭하면 파일을 열람할 수 있습니다. (비밀번호 필요)"
        })

    # ── 수방대책 ──
    if any(w in msg for w in ["수방", "홍수", "태풍", "대책", "flood"]):
        sections = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(CHAT_FLOOD_SECTIONS))
        return jsonify({
            "reply": f"🌊 **사업관리단 수방대책** — {len(CHAT_FLOOD_SECTIONS)}개 섹션\n{sections}\n\n"
                     f"메인 페이지 하단의 '사업관리단 수방대책' 링크를 클릭하세요."
        })

    # ── 도움말 ──
    if any(w in msg for w in ["도움", "뭐 할 수", "help", "명령", "가능"]):
        return jsonify({
            "reply": "💡 **할 수 있는 일**\n"
                     "  • 프로젝트 목록 보기\n"
                     "  • 각 공구 정보 확인 (성산1, 성산2, 구동1, 구동2)\n"
                     "  • 수방대책 정보\n"
                     "  • 간단한 대화\n\n"
                     "궁금한 걸 물어보세요!"
        })

    # ── 사이트 정보 ──
    if any(w in msg for w in ["사이트", "이 페이지", "여기", "개발노트"]):
        return jsonify({
            "reply": "🗂️ **서천군 재해복구사업 개발노트**\n"
                     "이 페이지는 성산천 사업관리단의 내부 자료 공유 사이트입니다.\n"
                     "각 공구별 문서(작업일보, 안전일지, 시방서 등)를 열람하고 다운로드할 수 있습니다."
        })

    # ── 작별 ──
    if any(w in msg for w in ["잘가", "바이", "by", "종료", "끝"]):
        return jsonify({"reply": "네, 필요한 게 있으면 언제든 불러주세요! 😊"})

    # ── 기본 응답 ──
    return jsonify({
        "reply": "질문을 잘 이해하지 못했어요. 😅\n"
                 "'도움말'이라고 입력하시면 제가 할 수 있는 일을 알려드릴게요!"
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)