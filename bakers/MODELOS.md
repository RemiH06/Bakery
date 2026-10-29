# Elegir modelos según el hardware

Cómo se eligieron los modelos de [`servidor/llama-swap.yaml`](servidor/llama-swap.yaml) y cómo repetir la elección en otra máquina. Los números de aquí son de Pixilate (RTX 3060 12 GB, Ryzen 7 5700X, 48 GB de RAM, NVMe): sirven de referencia, no de promesa. En otro equipo, medir de nuevo.

## Método

1. **Inventario real del equipo:** VRAM, RAM, núcleos, disco y si la máquina se comparte (juegos, otros servicios). En Bakery lo da la skill `hardware` de SkillShot; Claude cruza ese inventario con las fuentes de abajo y propone candidatos. El método es lo que se reusa; los números salen de medir.
2. **Cuentas a mano** para descartar lo que no cabe (abajo).
3. **Medir** los candidatos con `llama-bench` y los bancos de [`banco/`](banco/), en el uso real (texto largo, imágenes, con la otra carga encendida).
4. **A/B en la tarea:** el mismo Baker con dos modelos sobre el mismo material, y leer las salidas. La velocidad sola no decide.

## Fuentes

- **unsloth:** guías por modelo (cómo correrlo en llama.cpp, parámetros recomendados, cuánta memoria pide) y sus repos de Hugging Face con GGUF en cuantizaciones dinámicas (`UD-Q4_K_XL` y similares), que suelen perder menos calidad que las uniformes del mismo tamaño.
- **Fichas de modelo en Hugging Face:** licencia (Apache 2.0 o MIT para no tener sorpresas), contexto de entrenamiento, si es MoE y cuántos parámetros activa, y si trae proyector de visión (`mmproj`).
- **PrismML:** formatos de los Bonsai ternarios y de 1 bit (https://docs.prismml.com/download/formats). Los ternarios (`PQ2_0`) piden el fork `PrismML-Eng/llama.cpp`; los de 1 bit (`Q1_0`) ya corren en llama.cpp oficial.
- **Metadatos del GGUF:** la fuente final para las cuentas de caché. `llama-server` los imprime al cargar (`n_layer`, `n_head_kv`, `n_embd_head_k` y, en los híbridos, cada cuántas capas hay atención completa).
- **Leaderboards (benchlm.ai y parecidos):** solo para armar la lista corta, y solo si se cotejan con una prueba propia. No reemplazan al A/B.

## Cuentas

**Peso del modelo:** parámetros × bits por peso / 8.

| Modelo | Parámetros | Bits aprox. | Cuenta | Archivo real |
|---|---|---|---|---|
| Ternary Bonsai 2 27B `PQ2_0` | 27 B | ~2.1 | 27 × 2.1 / 8 ≈ 7.1 GB | 7.2 GB |
| Qwen3.6 35B-A3B `UD-Q4_K_XL` | 35 B | ~4.5 a 5 | 35 × 4.75 / 8 ≈ 21 GB | ~22 GB |

**Caché KV por token:** capas de atención × cabezas KV × dimensión por cabeza × 2 (K y V) × bytes por valor (2 en f16, ~1 en q8_0). En los modelos híbridos (atención completa cada 4 capas, el resto SSM) solo cuentan las capas de atención.

| Modelo | Capas de atención | Cabezas KV × dim | Por token (f16) | A 32k | A 262k |
|---|---|---|---|---|---|
| Qwen3.6 35B-A3B | 10 | 2 × 256 | 10 × 2 × 256 × 2 × 2 = 20 KB | ~0.6 GB | ~5 GB (2.6 en q8_0) |
| Bonsai 27B | 16 | 4 × 256 | 64 KB | ~2 GB | 64k: ~4 GB |

VRAM total ≈ pesos en GPU + caché KV + buffers de cómputo (crecen con `-ub`) + lo que ya use el escritorio (~1 GB en Windows). Dejar al menos 1 GB libre.

**MoE que no cabe en VRAM:** con `-ncmoe N`, los expertos de N capas se quedan en RAM y la GPU guarda lo demás. Qwen 35B-A3B con `-ncmoe 99` (todos los expertos en RAM) usa 3.9 GB de VRAM y genera a ~19 tok/s; con `-ncmoe 24`, 11.2 GB y ~26 tok/s. Funciona bien porque solo activa ~3 B parámetros por token. El techo lo pone la RAM: los expertos se mapean del GGUF y llegan a ~20 GB conforme se usan. Un modelo denso del mismo tamaño no sirve así: cada token lee todos los pesos de RAM.

## Medir

- **`llama-bench`** (viene con llama.cpp): lectura (`pp`) y generación (`tg`) a varias profundidades, sin el ruido del servidor. Ejemplo: `llama-bench -m models/<modelo>.gguf -ngl 99 -ncmoe 99 -p 2048 -n 128 -ub 512,2048,4096`.
- **[`banco/carga.py`](banco/carga.py):** N conversaciones a la vez contra el Baker `chat`; latencia p50/p95 y tok/s.
- **[`banco/banco_vision.py`](banco/banco_vision.py) + [`banco/variantes.sh`](banco/variantes.sh):** la llamada de `reel` contra un llama-server suelto, comparando flags y número o tamaño de fotogramas.
- **[`banco/chat_juego.py`](banco/chat_juego.py) + [`banco/muestreo.sh`](banco/muestreo.sh):** un chat largo mientras corre otra carga (un juego), muestreando VRAM, GPU, CPU y las decisiones del vigilante.

Los resultados van a `~/.bakers/banco/`, fuera del repo.

## Lecciones que dependen del hardware

Medidas en Pixilate. Comprobarlas antes de copiarlas a otra máquina:

- **`-ub` grande con texto y expertos en RAM:** leer el prompt era el cuello (120 tok/s con el `-ub 512` por defecto). Con 2048 sube a ~390 por 0.25 GB más de VRAM; con 4096, a ~580 (+0.9 GB).
- **`--no-op-offload` con imágenes y expertos en RAM:** cada imagen se decodifica en su propio lote, y llama.cpp copiaba los expertos de RAM a GPU en cada lote. Calcularlos en CPU bajó 8 fotogramas de ~63 s a ~34 s. Con texto no conviene: en lotes grandes la copia sí paga.
- **Caché KV en q8_0** para que un modelo quepa entero en VRAM con más contexto (Bonsai abliterado a 64k: 9.9 GB en vez de 11.8).
- **Prioridad baja si la máquina se comparte:** con los expertos en CPU, generar saturaba la CPU y un juego bajaba de 120 a 40 FPS. Con prioridad baja (`BelowNormal` en Windows, `Nice=10` en systemd) no cuesta nada cuando no hay otra carga.
- **MTP y decodificación especulativa:** con los expertos en RAM, el borrador de Qwen bajó de 17.6 a 8.7 tok/s (aceptaba 31 %). Apagado. Con el modelo entero en VRAM podría ser otra historia.
- **Las tablas de VRAM y RAM de [`servidor/vigilante.py`](servidor/vigilante.py)** son de esta tarjeta y este contexto: en otro equipo se miden de nuevo con `nvidia-smi` con cada modelo cargado y quieto.
