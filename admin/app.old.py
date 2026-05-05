import os, json, stat, subprocess
from flask import Flask, request, redirect, render_template_string, flash, url_for

# ---------- Templates ----------
TPL_INDEX = """
<!doctype html><html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
<title>DDNS Config</title>
</head><body class="p-4">
<div class="container" style="max-width:1100px">
  <h3 class="mb-3">Cloudflare DDNS – Registros</h3>
  {% with m=get_flashed_messages() %}{% if m %}<div class="alert alert-info">{{ m[0] }}</div>{% endif %}{% endwith %}

  <div class="d-flex gap-2 mb-3">
    <a class="btn btn-primary" href="{{ url_for('add') }}">Agregar registro</a>
    {% if can_restart %}
      <form method="post" action="{{ url_for('restart') }}" class="d-inline">
        <button class="btn btn-outline-danger" onclick="return confirm('Reiniciar ddns-updater ahora?')">Reiniciar updater</button>
      </form>
    {% endif %}
    <a class="btn btn-secondary" href="{{ url_for('status') }}" target="_blank">Ver estado (UI updater)</a>
  </div>

  <div class="table-responsive">
  <table class="table table-sm align-middle">
    <thead><tr>
      <th>#</th><th>Dominio (FQDN)</th><th>Zone ID</th><th>IPv</th><th>Proxied</th><th>TTL</th><th>Acciones</th>
    </tr></thead>
    <tbody>
    {% for s in settings %}
      <tr>
        <td>{{ loop.index0 }}</td>
        <td class="fw-semibold">{{ s.get('domain','') }}</td>
        <td><code style="font-size:0.8rem">{{ (s.get('zone_identifier','')[:8]+'…') if s.get('zone_identifier') else '' }}</code></td>
        <td>{{ s.get('ip_version','ipv4') }}</td>
        <td>{{ 'ON' if s.get('proxied') else 'OFF' }}</td>
        <td>{{ s.get('ttl',1) }}</td>
        <td class="d-flex gap-2">
          <a class="btn btn-sm btn-outline-primary" href="{{ url_for('edit', idx=loop.index0) }}">Editar</a>
          <form method="post" action="{{ url_for('delete', idx=loop.index0) }}" onsubmit="return confirm('Eliminar registro {{ s.get('domain','') }}?')">
            <button class="btn btn-sm btn-outline-danger">Eliminar</button>
          </form>
        </td>
      </tr>
    {% else %}
      <tr><td colspan="7" class="text-muted">Sin registros. Hacé clic en “Agregar registro”.</td></tr>
    {% endfor %}
    </tbody>
  </table>
  </div>

  <p class="text-muted small mt-4">El archivo se guarda en: <code>{{ config_path }}</code>. Protegé este sitio con Cloudflare Access.</p>
</div></body></html>
"""

TPL_FORM = """
<!doctype html><html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
<title>{{ 'Editar' if editing else 'Agregar' }} registro</title>
</head><body class="p-4">
<div class="container" style="max-width:900px">
  <h4 class="mb-3">{{ 'Editar' if editing else 'Agregar' }} registro</h4>
  <form method="post">
    <div class="row g-3">
      <div class="col-md-8">
        <label class="form-label">Dominio (FQDN)</label>
        <input name="domain" class="form-control" required value="{{ s.get('domain','') or 'ddns.gabo.ar' }}">
        <div class="form-text">Ej: ddns.gabo.ar</div>
      </div>
      <div class="col-md-4">
        <label class="form-label">IP version</label>
        <select name="ip_version" class="form-select">
          <option value="ipv4" {% if s.get('ip_version','ipv4')=='ipv4' %}selected{% endif %}>ipv4</option>
          <option value="ipv6" {% if s.get('ip_version')=='ipv6' %}selected{% endif %}>ipv6</option>
        </select>
      </div>
      <div class="col-md-12">
        <label class="form-label">Zone ID</label>
        <input name="zone_identifier" class="form-control" required value="{{ s.get('zone_identifier','') }}">
      </div>
      <div class="col-md-12">
        <label class="form-label">API Token (DNS Edit)</label>
        <input name="token" class="form-control" required value="{{ s.get('token','') }}">
      </div>
      <div class="col-md-4">
        <label class="form-label">Proxied</label>
        <select name="proxied" class="form-select">
          <option value="false" {% if not s.get('proxied') %}selected{% endif %}>OFF (DNS only)</option>
          <option value="true"  {% if s.get('proxied') %}selected{% endif %}>ON</option>
        </select>
      </div>
      <div class="col-md-4">
        <label class="form-label">TTL</label>
        <input name="ttl" type="number" min="1" class="form-control" value="{{ s.get('ttl',1) }}">
        <div class="form-text">1 = Auto</div>
      </div>
    </div>
    <div class="mt-4 d-flex gap-2">
      <button class="btn btn-primary" type="submit">Guardar</button>
      <a class="btn btn-secondary" href="{{ url_for('index') }}">Volver</a>
    </div>
  </form>
</div></body></html>
"""

# ---------- App ----------
def create_app():
    # static_folder=None para que no choque con /static proxy
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
        import urllib.request
        base = "http://ddns-updater:8000"
        req = urllib.request.Request(base + path, headers={"User-Agent": "ddns-admin-proxy"})
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read()
            ct = r.headers.get("Content-Type", "application/octet-stream")
            return body, r.getcode(), {"Content-Type": ct}

    @app.route("/status")
    def status():
        return _proxy_to_updater("/")

    @app.route("/static/<path:path>")
    def static_proxy(path):
        return _proxy_to_updater("/static/" + path)

    @app.route("/favicon.ico")
    def favicon_proxy():
        return _proxy_to_updater("/favicon.ico")

    return app
