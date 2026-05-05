import os, json, stat, subprocess
from flask import Flask, request, redirect, render_template_string, flash, url_for

# ---------- Templates ----------
TPL_INDEX = """..."""  # (idéntico a tu versión, no lo recorto por brevedad)
TPL_FORM = """..."""   # (idéntico a tu versión, no lo recorto por brevedad)

# ---------- App ----------
def create_app():
    app = Flask(__name__, static_folder=None)
    app.secret_key = os.urandom(16)

    CONFIG_PATH = os.environ.get("CONFIG_PATH","/config/config.json")
    DDNS_NAME = os.environ.get("DDNS_CONTAINER_NAME","ddns-updater")
    CAN_RESTART = os.environ.get("ENABLE_DOCKER_RESTART","false").lower()=="true"
    OWNER_UID = int(os.environ.get("CONFIG_OWNER_UID","1000"))
    OWNER_GID = int(os.environ.get("CONFIG_OWNER_GID","1000"))

    # ----- helpers de config -----
    def load_settings():
        try:
            with open(CONFIG_PATH,"r") as f:
                data = json.load(f)
            return data.get("settings",[])
        except FileNotFoundError:
            return []
        except Exception:
            return []

    def save_settings(settings):
        data = {"settings": settings}
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp,"w") as f:
            json.dump(data,f,indent=2)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, CONFIG_PATH)
        try:
            os.chown(CONFIG_PATH, OWNER_UID, OWNER_GID)
        except Exception:
            pass
        os.chmod(CONFIG_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 600

    def record_from_form(form):
        return {
            "provider":"cloudflare",
            "domain": form["domain"].strip(),
            "zone_identifier": form["zone_identifier"].strip(),
            "token": form["token"].strip(),
            "ip_version": form.get("ip_version","ipv4"),
            "proxied": form.get("proxied","false")=="true",
            "ttl": int(form.get("ttl","1") or "1"),
        }

    # ----- rutas principales -----
    @app.route("/")
    def index():
        return render_template_string(
            TPL_INDEX,
            settings=load_settings(),
            can_restart=CAN_RESTART,
            config_path=CONFIG_PATH
        )

    @app.route("/add", methods=["GET","POST"])
    def add():
        if request.method=="POST":
            settings = load_settings()
            settings.append(record_from_form(request.form))
            save_settings(settings)
            flash("Registro agregado.")
            return redirect(url_for("index"))
        return render_template_string(TPL_FORM, s={}, editing=False)

    @app.route("/edit/<int:idx>", methods=["GET","POST"])
    def edit(idx:int):
        settings = load_settings()
        if idx<0 or idx>=len(settings):
            flash("Índice inválido."); return redirect(url_for("index"))
        if request.method=="POST":
            settings[idx] = record_from_form(request.form)
            save_settings(settings)
            flash("Registro actualizado.")
            return redirect(url_for("index"))
        return render_template_string(TPL_FORM, s=settings[idx], editing=True)

    @app.route("/delete/<int:idx>", methods=["POST"])
    def delete(idx:int):
        settings = load_settings()
        if 0<=idx<len(settings):
            dom = settings[idx].get("domain","")
            settings.pop(idx)
            save_settings(settings)
            flash(f"Registro eliminado: {dom}")
        return redirect(url_for("index"))

    @app.route("/restart", methods=["POST"])
    def restart():
        if not CAN_RESTART:
            flash("Reinicio deshabilitado."); return redirect(url_for("index"))
        try:
            subprocess.check_call(["/usr/bin/docker","restart", DDNS_NAME])
            flash("Updater reiniciado.")
        except Exception as e:
            flash(f"No pude reiniciar: {e}")
        return redirect(url_for("index"))

    # ----- proxy a la UI nativa del updater (+ estáticos) -----
    def _proxy_to_updater(path="/"):
        import urllib.request, urllib.error
        base = "http://ddns-updater:8000"
        req = urllib.request.Request(base + path, headers={"User-Agent": "ddns-admin-proxy"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                body = r.read()
                ct = r.headers.get("Content-Type", "application/octet-stream")
                return body, r.getcode(), {"Content-Type": ct}
        except urllib.error.HTTPError as e:
            body = e.read() or b""
            ct = e.headers.get("Content-Type", "text/plain") if getattr(e, "headers", None) else "text/plain"
            return body, e.code, {"Content-Type": ct}
        except urllib.error.URLError:
            return b"ddns-updater no disponible", 502, {"Content-Type": "text/plain"}

    @app.route("/status")
    def status():
        return _proxy_to_updater("/")

    @app.route("/static/<path:path>")
    def static_proxy(path):
        return _proxy_to_updater("/static/" + path)

    @app.route("/favicon.ico")
    def favicon_proxy():
        body, status, headers = _proxy_to_updater("/favicon.ico")
        if status == 404:
            return b"", 204, {"Content-Type": "text/plain"}
        return body, status, headers

    return app
