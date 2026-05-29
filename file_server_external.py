"""
file_server_external.py  —  대외용 웹 파일 서버
포트  : 5050
공유  : E:\openshare
"""

from flask import (Flask, render_template, send_from_directory,
                   request, redirect, url_for, session, abort, jsonify)
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import secrets, os

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

SHARED_FOLDER = Path(r"E:\openshare")

# ── .env 로드 ─────────────────────────────────
load_dotenv()

# ── 시작 시 .env 누락 키 점검 ─────────────────
REQUIRED_KEYS = ["SUNGSAN1_PW", "SUNGSAN2_PW", "GUDONG1_PW", "GUDONG2_PW"]
missing = [k for k in REQUIRED_KEYS if not os.getenv(k)]
if missing:
    raise RuntimeError(f"[ERROR] .env에 다음 키가 없습니다: {', '.join(missing)}")

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)