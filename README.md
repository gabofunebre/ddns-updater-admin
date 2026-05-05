# ddns-updater-admin

Panel de administración para `ddns-updater` (imagen de tercero `qmcgaw/ddns-updater`) con una web Flask propia para gestionar registros DNS de Cloudflare en `config.json`.

## Qué incluye este repo

- **`ddns-updater`**: servicio principal DDNS (tercero, imagen Docker pública).
- **`ddns-admin`**: servicio web propio (Flask + Waitress) para:
  - listar registros,
  - agregar,
  - editar,
  - eliminar,
  - reiniciar el contenedor `ddns-updater` (opcional),
  - abrir/proxyear la UI nativa de estado del updater.

## Arquitectura

`docker-compose.yml` levanta dos contenedores en una red externa `DDNS_tunn_net`:

1. `ddns-updater`
   - Imagen: `qmcgaw/ddns-updater:latest`
   - Monta `./` en `/updater/data`
   - Lee/escribe `config.json` ahí.

2. `ddns-admin`
   - Build local en `./admin`
   - Monta `./` en `/config`
   - Usa `CONFIG_PATH=/config/config.json`
   - Expone endpoints web de administración.

> Nota: ambos comparten el mismo archivo de configuración a través del volumen del host.

## Reglas de negocio (deducidas del código)

El panel trabaja sobre `settings` dentro de `config.json`:

```json
{
  "settings": [
    {
      "provider": "cloudflare",
      "domain": "ddns.ejemplo.com",
      "zone_identifier": "...",
      "token": "...",
      "ip_version": "ipv4",
      "proxied": false,
      "ttl": 1
    }
  ]
}
```

### Reglas actuales

- `provider` se fija siempre en `cloudflare`.
- Campos requeridos desde formulario:
  - `domain`
  - `zone_identifier`
  - `token`
- Defaults:
  - `ip_version=ipv4`
  - `proxied=false`
  - `ttl=1` (`1 = Auto`)
- Guardado atómico:
  - escribe `config.json.tmp`
  - `fsync`
  - `os.replace` sobre `config.json`
- Permisos del archivo final:
  - `chmod 600`
  - `chown` configurable por `CONFIG_OWNER_UID/GID`.

## Endpoints del admin

- `GET /` lista registros
- `GET|POST /add`
- `GET|POST /edit/<idx>`
- `POST /delete/<idx>`
- `POST /restart` reinicia el updater (si `ENABLE_DOCKER_RESTART=true`)
- `GET /status` proxy a `http://ddns-updater:8000/`
- `GET /static/<path>` proxy de estáticos de la UI nativa
- `GET /favicon.ico` proxy favicon del updater

## Variables de entorno relevantes

### `ddns-admin`

- `CONFIG_PATH` (default `/config/config.json`)
- `DDNS_CONTAINER_NAME` (default `ddns-updater`)
- `ENABLE_DOCKER_RESTART` (`true|false`)
- `CONFIG_OWNER_UID` (default `1000`)
- `CONFIG_OWNER_GID` (default `1000`)

### `ddns-updater`

- `PERIOD`
- `LOG_LEVEL`
- `PUBLICIP_HTTP_PROVIDERS`
- `TZ`

## Cómo levantar

```bash
docker compose up -d --build
```

## Troubleshooting rápido

1. **La URL del admin carga “...” o vacía**
   - Revisar que `admin/app.py` tenga templates HTML reales (no placeholders).

2. **`/status` da error / no responde**
   - Verificar que `ddns-updater` esté corriendo y accesible por nombre DNS interno en la red (`ddns-updater:8000`).

3. **No persiste config o permisos incorrectos**
   - Verificar volumen `./:/config` y `CONFIG_OWNER_UID/GID`.

4. **No reinicia el updater desde botón**
   - Verificar `ENABLE_DOCKER_RESTART=true`
   - Verificar montaje `/var/run/docker.sock`
   - Verificar que el contenedor tenga `docker-cli` (el Dockerfile ya lo instala).

## Seguridad

- El panel maneja tokens de Cloudflare en claro en formulario y `config.json`.
- Recomendado proteger acceso con Cloudflare Access / autenticación de red privada.
- Evitar exponer este admin públicamente sin control de acceso.
