# Correo de no-reply en remlam.dev

Bakery no manda correo directo: una IP residencial está en las listas de bloqueo y el puerto 25 de salida suele venir cerrado. Lo envía **AhaSend** (AhaSend B.V., Ámsterdam; servidores propios en Hetzner, Alemania y Finlandia; los datos de los mensajes se quedan en la UE). Plan gratis: 1,000 correos al mes, 3 dominios, sin tarjeta. Los no-reply solo envían; lo único que recibe es la raíz, por Cloudflare Email Routing (sección 1).

Se eligió sobre Scaleway TEM (una nube completa para mandar unos cuantos correos) y Lettermint (1 dominio en el plan gratis). Las dos tienen adaptador en Swoosh por si hay que cambiar.

## Direcciones

| Proyecto | Remitente | Llave | Estado |
|---|---|---|---|
| Mapo | `Mapo <no-reply@mail.mapo.remlam.dev>` | `messages:send:mail.mapo.remlam.dev` | Listo en código (`docs/despliegue.md` de Mapo, "Correo") |
| Tabularium | `Tabularium <no-reply@mail.tabularium.remlam.dev>` | `messages:send:mail.tabularium.remlam.dev` | Dominio reservado; hoy no manda nada (cuentas con llaves de acceso, invitaciones por `mailto:`) |

Por qué un subdominio por proyecto:
- **Reputación aparte.** Si un envío de Tabularium (por ejemplo, las noticias) cae en spam, los enlaces de acceso de Mapo no se ven afectados.
- **Llaves aparte.** La llave de cada proyecto solo envía desde su dominio; si se filtra, no administra la cuenta ni envía como el otro.
- **No choca con el túnel.** `mapo.remlam.dev` es un CNAME, y un nombre con CNAME no admite otros registros, como el TXT del SPF. `mail.mapo.remlam.dev` es otro nombre.
- **La raíz queda libre** para un buzón personal en el futuro.

## 1. La raíz (Cloudflare, DNS de remlam.dev)

La raíz no envía correo, pero recibe: Cloudflare Email Routing reenvía las direcciones creadas a mano (la cuenta de AhaSend está a nombre de una de ellas) a un buzón personal. Catch-all apagado. Registros:

| Tipo | Nombre | Contenido |
|---|---|---|
| MX | `@` | `route1`, `route2` y `route3.mx.cloudflare.net` (los pone Email Routing) |
| TXT | `@` | `v=spf1 include:_spf.mx.cloudflare.net ~all` (el de Email Routing; solo puede haber un SPF por nombre) |
| TXT | `cf2024-1._domainkey` | DKIM de Email Routing (lo pone Cloudflare) |
| TXT | `_dmarc` | `v=DMARC1; p=reject; sp=reject` |

El DMARC con `p=reject` hace que nadie pueda enviar como `algo@remlam.dev`; los reenvíos conservan el remitente original y no lo tocan. `sp=reject` también cubre cualquier subdominio sin su propio `_dmarc`. Los subdominios de correo sí tienen el suyo (paso 3) y ese manda sobre este. Para pasar a Proton, se cambian los MX y el SPF; la dirección se queda igual.

## 2. AhaSend: cuenta y dominios

1. Crear la cuenta en ahasend.com (plan Free).
2. **Domains > Add domain:** `mail.mapo.remlam.dev`, tipo transaccional (AhaSend propone el prefijo `mail.`). Apagar el seguimiento de aperturas y clics: reescribe cada enlace por `track.ahasend.com`, y en Mapo son enlaces de acceso. Repetir con `mail.tabularium.remlam.dev`. Cada dominio muestra sus registros con los valores exactos.
3. Pedir a soporte que verifique la cuenta antes de encender el envío. Mientras no está verificada, un modelo de lenguaje (en Scaleway, Francia) puede revisar el contenido de los mensajes, y en Mapo esos mensajes llevan enlaces de acceso vigentes. Los límites de envío también empiezan bajos.

## 3. Registros de cada subdominio (Cloudflare)

Para `mail.mapo` y después lo mismo para `mail.tabularium`. Los nombres son relativos a `remlam.dev`, como los pide el panel de Cloudflare. **Todos los CNAME en "Solo DNS" (nube gris)**: con proxy, Cloudflare oculta el destino que AhaSend necesita revisar. Los valores que dicen "del panel" se copian exactos del dominio en AhaSend.

| Tipo | Nombre | Contenido |
|---|---|---|
| TXT | `mail.mapo` | `v=spf1 include:spf.ahasend.com ~all` |
| CNAME | `ahasend._domainkey.mail.mapo` | del panel (DKIM) |
| CNAME | `ahasend2._domainkey.mail.mapo` | del panel (DKIM de rotación) |
| CNAME | `psrp.mail.mapo` | `rp.ahasend.com` (rebotes) |
| MX | `mail.mapo` | `mx.ahasend.com`, prioridad 10 |
| TXT | `_dmarc.mail.mapo` | `v=DMARC1; p=none` al principio; `v=DMARC1; p=reject` cuando el paso 5 salga bien |

El CNAME `t.mail.mapo` (a `track.ahasend.com`) **no** se agrega: es el del seguimiento de clics. Después, **Check DNS** en AhaSend: tarda de 5 a 30 minutos, hasta 48 horas como máximo.

## 4. Llave de envío (una por proyecto)

**Credentials > Add > API Key v2**, en modo Production, con el alcance `messages:send:mail.mapo.remlam.dev`. Empieza con `aha-sk-` y solo se muestra una vez. Va en el `.env` del servidor como `MAPO_AHASEND_API_KEY`, nunca en el repo. El ID de la cuenta (`MAPO_AHASEND_ACCOUNT_ID`) sale en la configuración de la cuenta. Estas llaves no sirven para SMTP: si una app necesita SMTP, va con una credencial SMTP limitada a su dominio (`send.ahasend.com`, puerto 587 con STARTTLS).

## 5. Comprobar

1. Mandarse un correo desde la app (en Mapo, pedir un enlace de acceso).
2. En el cliente, abrir el original del mensaje: `SPF: PASS`, `DKIM: PASS` con `d=mail.mapo.remlam.dev`, `DMARC: PASS`.
3. Si pasa, subir el `_dmarc` del subdominio a `p=reject`.
4. Desde la terminal: `nslookup -type=TXT mail.mapo.remlam.dev 1.1.1.1`.

## Pendiente antes de que Tabularium envíe noticias

- Las noticias son correo de marketing para AhaSend: tienen que salir de un dominio de tipo *Marketing* (otro subdominio, por ejemplo `noticias.tabularium.remlam.dev`), solo a quien se suscribió de forma explícita, con baja de un clic (`List-Unsubscribe` y `List-Unsubscribe-Post`). Si las quejas pasan de 0.3 % o los rebotes de 1 %, suspenden la cuenta.
- El envío sale de `frambuesa-yi`: comprobar que el servicio que mande tenga salida a `api.ahasend.com` (los servicios están aislados).
- Python: la API con `urllib` o `smtplib` de la librería estándar, sin dependencias nuevas.
