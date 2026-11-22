# Correo de no-reply en remlam.dev

Bakery no manda correo directo: una IP residencial está en las listas de bloqueo y el puerto 25 de salida suele venir cerrado. Lo envía **AhaSend** (AhaSend B.V., Ámsterdam; servidores propios en Hetzner, Alemania y Finlandia; los datos de los mensajes se quedan en la UE). Plan gratis: 1,000 correos al mes, 3 dominios, sin tarjeta. Recibir correo no está configurado: estas direcciones solo envían.

Se eligió sobre Scaleway TEM (una nube completa para mandar unos cuantos correos) y Lettermint (1 dominio en el plan gratis). Las dos tienen adaptador en Swoosh por si hay que cambiar.

## Direcciones

| Proyecto | Remitente | Llave | Estado |
|---|---|---|---|
| Mapo | `Mapo <no-reply@correo.mapo.remlam.dev>` | `messages:send:correo.mapo.remlam.dev` | Listo en código (`docs/despliegue.md` de Mapo, "Correo") |
| Tabularium | `Tabularium <no-reply@correo.tabularium.remlam.dev>` | `messages:send:correo.tabularium.remlam.dev` | Dominio reservado; hoy no manda nada (cuentas con llaves de acceso, invitaciones por `mailto:`) |

Por qué un subdominio por proyecto:
- **Reputación aparte.** Si un envío de Tabularium (por ejemplo, las noticias) cae en spam, los enlaces de acceso de Mapo no se ven afectados.
- **Llaves aparte.** La llave de cada proyecto solo envía desde su dominio; si se filtra, no administra la cuenta ni envía como el otro.
- **No choca con el túnel.** `mapo.remlam.dev` es un CNAME, y un nombre con CNAME no admite otros registros, como el TXT del SPF. `correo.mapo.remlam.dev` es otro nombre.
- **La raíz queda libre** para un buzón personal en el futuro.

## 1. Proteger la raíz (Cloudflare, DNS de remlam.dev)

La raíz no envía correo. Estos dos registros hacen que nadie pueda enviar correo haciéndose pasar por `algo@remlam.dev`:

| Tipo | Nombre | Contenido |
|---|---|---|
| TXT | `@` | `v=spf1 -all` |
| TXT | `_dmarc` | `v=DMARC1; p=reject; sp=reject` |

`sp=reject` también cubre cualquier subdominio sin su propio `_dmarc`. Los subdominios de correo sí tienen el suyo (paso 3) y ese manda sobre este. Si algún día la raíz recibe o envía correo (Proton, Email Routing), hay que cambiar estos dos registros primero.

## 2. AhaSend: cuenta y dominios

1. Crear la cuenta en ahasend.com (plan Free).
2. **Domains > Add domain:** `correo.mapo.remlam.dev`, tipo transaccional. Repetir con `correo.tabularium.remlam.dev`. Cada dominio muestra sus registros con los valores exactos.
3. Pedir a soporte que verifique la cuenta antes de encender el envío. Mientras no está verificada, un modelo de lenguaje (en Scaleway, Francia) puede revisar el contenido de los mensajes, y en Mapo esos mensajes llevan enlaces de acceso vigentes. Los límites de envío también empiezan bajos.

## 3. Registros de cada subdominio (Cloudflare)

Para `correo.mapo` y después lo mismo para `correo.tabularium`. Los nombres son relativos a `remlam.dev`, como los pide el panel de Cloudflare. **Todos los CNAME en "Solo DNS" (nube gris)**: con proxy, Cloudflare oculta el destino que AhaSend necesita revisar. Los valores que dicen "del panel" se copian exactos del dominio en AhaSend.

| Tipo | Nombre | Contenido |
|---|---|---|
| TXT | `correo.mapo` | `v=spf1 include:spf.ahasend.com -all` |
| CNAME | `managed._domainkey.correo.mapo` | del panel (DKIM) |
| CNAME | `managed2._domainkey.correo.mapo` | del panel (DKIM de rotación) |
| CNAME | el de rebotes (*return-path*) que muestra el panel | del panel |
| MX | `correo.mapo`, si el panel lo propone | del panel, prioridad 10 |
| TXT | `_dmarc.correo.mapo` | `v=DMARC1; p=none` al principio; `v=DMARC1; p=reject` cuando el paso 5 salga bien |

Después, **Check DNS** en AhaSend: tarda de 5 a 30 minutos, hasta 48 horas como máximo.

## 4. Llave de envío (una por proyecto)

**Credentials > Add > API Key v2**, en modo Production, con el alcance `messages:send:correo.mapo.remlam.dev`. Empieza con `aha-sk-` y solo se muestra una vez. Va en el `.env` del servidor como `MAPO_AHASEND_API_KEY`, nunca en el repo. El ID de la cuenta (`MAPO_AHASEND_ACCOUNT_ID`) sale en la configuración de la cuenta. Estas llaves no sirven para SMTP: si una app necesita SMTP, va con una credencial SMTP limitada a su dominio (`send.ahasend.com`, puerto 587 con STARTTLS).

## 5. Comprobar

1. Mandarse un correo desde la app (en Mapo, pedir un enlace de acceso).
2. En el cliente, abrir el original del mensaje: `SPF: PASS`, `DKIM: PASS` con `d=correo.mapo.remlam.dev`, `DMARC: PASS`.
3. Si pasa, subir el `_dmarc` del subdominio a `p=reject`.
4. Desde la terminal: `nslookup -type=TXT correo.mapo.remlam.dev 1.1.1.1`.

## Pendiente antes de que Tabularium envíe noticias

- Las noticias son correo de marketing para AhaSend: tienen que salir de un dominio de tipo *Marketing* (otro subdominio, por ejemplo `noticias.tabularium.remlam.dev`), solo a quien se suscribió de forma explícita, con baja de un clic (`List-Unsubscribe` y `List-Unsubscribe-Post`). Si las quejas pasan de 0.3 % o los rebotes de 1 %, suspenden la cuenta.
- El envío sale de `frambuesa-yi`: comprobar que el servicio que mande tenga salida a `api.ahasend.com` (los servicios están aislados).
- Python: la API con `urllib` o `smtplib` de la librería estándar, sin dependencias nuevas.
