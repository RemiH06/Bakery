# Correo de no-reply en remlam.dev

Bakery no manda correo directo: una IP residencial está en las listas de bloqueo y el puerto 25 de salida suele venir cerrado. Lo envía **Scaleway Transactional Email (TEM)**: francés, sujeto al RGPD, 300 correos al mes gratis por organización y 0.25 € por cada mil adicionales. Recibir correo no está configurado: estas direcciones solo envían.

## Direcciones

| Proyecto | Remitente | Proyecto de Scaleway | Estado |
|---|---|---|---|
| Mapo | `Mapo <no-reply@correo.mapo.remlam.dev>` | `mapo` | Listo en código (`docs/despliegue.md` de Mapo, "Correo") |
| Tabularium | `Tabularium <no-reply@correo.tabularium.remlam.dev>` | `tabularium` | Dominio reservado; hoy no manda nada (cuentas con llaves de acceso, invitaciones por `mailto:`) |

Por qué un subdominio por proyecto:
- **Reputación aparte.** Si un envío de Tabularium (por ejemplo, las noticias) cae en spam, los enlaces de acceso de Mapo no se ven afectados.
- **Llaves aparte.** Cada proyecto de Scaleway tiene su propia llave; si se filtra la de uno, no puede enviar como el otro.
- **No choca con el túnel.** `mapo.remlam.dev` es un CNAME, y un nombre con CNAME no admite otros registros, como el TXT del SPF. `correo.mapo.remlam.dev` es otro nombre.
- **La raíz queda libre** para un buzón personal en el futuro.

## 1. Proteger la raíz (Cloudflare, DNS de remlam.dev)

La raíz no envía correo. Estos dos registros hacen que nadie pueda enviar correo haciéndose pasar por `algo@remlam.dev`:

| Tipo | Nombre | Contenido |
|---|---|---|
| TXT | `@` | `v=spf1 -all` |
| TXT | `_dmarc` | `v=DMARC1; p=reject; sp=reject` |

`sp=reject` también cubre cualquier subdominio que no tenga su propio `_dmarc`. Los subdominios de correo sí tienen el suyo (paso 3) y ese manda sobre este. Si algún día la raíz recibe o envía correo (Proton, Email Routing), hay que cambiar estos dos registros primero.

## 2. Scaleway (una vez por proyecto)

1. Crear la cuenta, validar la tarjeta y la identidad. Sin la validación, los límites de envío son más bajos.
2. En **Organización > Proyectos**, crear `mapo` y `tabularium`.
3. Dentro de cada proyecto: **Transactional Email > Select a plan > Essential > Add a domain external to Scaleway**, con `correo.mapo.remlam.dev` (o `correo.tabularium.remlam.dev`). La consola muestra el nombre y el valor del DKIM de ese dominio.
4. **IAM > Applications:** crear `mapo-correo` (o `tabularium-correo`). **IAM > Policies:** una política con el permiso `TransactionalEmailEmailFullAccess`, con alcance **solo** en el proyecto de esa app y la aplicación como principal. Con ese permiso la llave envía correos, pero no puede tocar dominios ni otros proyectos. **API keys** de esa aplicación: guardar la llave secreta (solo se muestra una vez) en el `.env` del servidor, nunca en el repo.
5. El ID del proyecto sale en **Transactional Email > Domain overview**. Para SMTP, el usuario es ese ID y la contraseña es la llave secreta (`smtp.tem.scaleway.com`, puerto 587 con STARTTLS o 465 con TLS). Mapo no usa SMTP: va por la API, con el adaptador de Swoosh.

TEM solo existe en la región `fr-par`. No admite un `include` de SPF anidado dentro de otro.

## 3. Registros de cada subdominio (Cloudflare)

Para `correo.mapo` y después lo mismo para `correo.tabularium`. Son nombres relativos a `remlam.dev`, como los pide el panel de Cloudflare, y ninguno va con proxy (nube gris).

| Tipo | Nombre | Contenido |
|---|---|---|
| TXT | `correo.mapo` | `v=spf1 include:_spf.tem.scaleway.com -all` |
| TXT | `<selector>._domainkey.correo.mapo` | El valor de DKIM que da la consola de Scaleway |
| MX | `correo.mapo` | `blackhole.tem.scaleway.com`, prioridad 10 |
| TXT | `_dmarc.correo.mapo` | `v=DMARC1; p=none` al principio; `v=DMARC1; p=reject` cuando el paso 4 salga bien |

El MX es el "agujero negro" de Scaleway: hay proveedores que rechazan correo de un dominio sin MX, y lo que alguien responda a un no-reply se pierde sin rebotar. Es lo esperado. Para que te escriban, el cuerpo del correo debe decir a dónde (en Mapo, el contacto de `/privacidad`).

Después, **Check domain** en la consola de Scaleway; el dominio pasa a verificado cuando los registros se propagan.

## 4. Comprobar

1. Mandarse un correo desde la app (en Mapo, pedir un enlace de acceso).
2. En el cliente, abrir el original del mensaje: `SPF: PASS`, `DKIM: PASS` con `d=correo.mapo.remlam.dev`, `DMARC: PASS`.
3. Si pasa, subir el `_dmarc` del subdominio a `p=reject`.
4. Desde la terminal, confirmar los registros: `nslookup -type=TXT correo.mapo.remlam.dev 1.1.1.1`.

## Pendiente antes de que Tabularium envíe noticias

- Las noticias son envíos masivos a quien los pidió, no correos transaccionales. Hay que revisar que la política antispam de Scaleway los permita en TEM, y agregar `List-Unsubscribe` y la baja con un clic.
- El envío sale de `frambuesa-yi`: comprobar que el servicio que mande tenga salida a `api.scaleway.com` o a `smtp.tem.scaleway.com` (los servicios están aislados).
- Python: `smtplib` de la librería estándar o la API con `urllib`, sin dependencias nuevas.
