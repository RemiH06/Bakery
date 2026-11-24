# n8n en Bakery

Instancia para aprender a armar automatizaciones con nodos. No es la base de los procesos de Bakery: esos son timers de systemd y tareas de `job.ps1` con su latido (`remote/README.md`, "Procesos y latidos"). n8n sirve para practicar y para flujos que peguen APIs de terceros con OAuth.

Licencia: Sustainable Use License (fair-code, no OSI). Gratis para uso propio; no se puede ofrecer como servicio a otros.

## Dónde y cómo

En el Debian del WSL de Pixilate, solo en el tailnet (`127.0.0.1:5678` y `tailscale serve --https=5678`).

```bash
mkdir -p ~/srv/n8n && cp <clon>/n8n/compose.yml ~/srv/n8n/ && cd ~/srv/n8n
umask 077; printf 'N8N_HOST=%s\nN8N_ENCRYPTION_KEY=%s\n' "<host del tailnet>" "$(openssl rand -hex 32)" > .env
docker compose up -d
```

En Windows: `tailscale serve --bg --https=5678 http://127.0.0.1:5678`. La primera visita crea la cuenta de dueño: contraseña larga y, en *Settings > Personal*, autenticación de dos pasos.

## Seguridad

| Qué | Amenaza que evita | Cómo se verifica |
|---|---|---|
| Versión fija, revisada contra los avisos de seguridad | Las RCE de 2026 (CVE-2026-21858, de CVSS 10, entre otras) | `docker compose images` muestra la versión |
| Solo `127.0.0.1` y tailnet; ningún webhook público | Bots que escanean internet y los webhooks sin autenticación de esas fallas | `ss -ltn \| grep 5678` en el WSL da solo `127.0.0.1` |
| Sin los nodos de comandos y archivos; sin variables de entorno en nodos | Que quien entre al editor (o una credencial robada) corra comandos en el contenedor | El nodo "Execute Command" no aparece en el editor |
| `cap_drop: ALL`, `no-new-privileges`, sin montar nada del host | Que una falla en n8n escale al WSL | `docker inspect n8n-n8n-1` |
| `N8N_ENCRYPTION_KEY` en `.env` 600, fuera del repo | Leer las credenciales guardadas desde una copia del volumen | `stat -c %a .env` da `600` |

Reglas de uso: nada de credenciales de NetZero ni de datos de terceros, y el MCP de instancia apagado (*Settings*) mientras no se use.

## Respaldo y apagado

- Los flujos se exportan como JSON desde el editor. El volumen `n8n_n8n_data` entra a la lista de lo que no se reconstruye en la mudanza a Debian (1.16), junto con el `.env` (sin la llave, las credenciales no se descifran).
- Apagar: `tailscale serve --https=5678 off` en Windows y `docker compose -f ~/srv/n8n/compose.yml down` en el WSL.
- Subir de versión: leer los avisos, cambiar el número en `compose.yml`, `docker compose pull && docker compose up -d`.
