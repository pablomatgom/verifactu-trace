# Empaquetado con Docker

Cada microservicio se empaqueta en su propia imagen mediante un `Dockerfile` ubicado en su carpeta (`services/<servicio>/Dockerfile`). Los tres siguen la misma estructura y solo cambia el puerto.

| Servicio | Puerto |
|---|---|
| `document-service` | 8001 |
| `traceability-service` | 8002 |
| `submission-service` | 8003 |

## Construir y ejecutar un servicio

```bash
docker build -t document-service services/document-service
docker run --rm -p 8001:8001 document-service
```

El servicio responde en `http://localhost:8001/health`.

## Decisiones de diseño

| Decisión | Elección | Motivo |
|---|---|---|
| Imagen base | `python:3.12-slim` | Basada en Debian y con solo lo imprescindible. La imagen completa de Python incluye compiladores y herramientas de sistema que no se necesitan en ejecución y la hacen más pesada |
| Alternativas descartadas | `alpine` y `distroless` | `alpine` usa musl en lugar de glibc, y no todos los paquetes de Python publican binarios para él, por lo que habría que compilarlos. `distroless` no incluye shell, lo que dificulta depurar, y el ahorro de tamaño a esta escala es pequeño |
| Construcción multietapa | Etapa `builder` y etapa `runtime` | La etapa `builder` instala las dependencias y la etapa `runtime` solo recibe el entorno virtual resultante y el código. `pip` y sus herramientas de instalación no llegan a la imagen final |
| Instalación de dependencias | `pip install --only-binary :all:` | Solo se instalan paquetes precompilados (*wheels*). Si una dependencia no tiene *wheel*, el build falla en lugar de ejecutar el script de instalación de un paquete fuente, lo que reduce el riesgo de cadena de suministro. Por eso la imagen de build no necesita compilador |
| Dependencias | Entorno virtual en `/opt/venv` | Deja todas las librerías en una única carpeta que se copia en bloque a la etapa final con `COPY --from=builder` |
| Caché de capas | `requirements.txt` se copia y se instala antes que el código | Si solo cambia el código, la capa de dependencias se reutiliza y la construcción tarda segundos |
| Usuario | `appuser`, usuario de sistema sin shell ni directorio personal, con UID y GID fijos `10001` | Principio de mínimo privilegio: el proceso no se ejecuta como `root`. `USER` usa el UID numérico porque un orquestador no puede comprobar que un nombre no es `root`, y Hadolint lo exige (`DL3066`) |
| Variables de Python | `PYTHONUNBUFFERED=1` y `PYTHONDONTWRITEBYTECODE=1` | Los logs salen por `stdout` sin retraso, algo necesario para observarlos en un contenedor, y no se generan ficheros `.pyc` inútiles |
| Variables de `pip` | `PIP_NO_CACHE_DIR=1` y `PIP_DISABLE_PIP_VERSION_CHECK=1` | Evitan guardar la caché de descargas en la imagen y una consulta de red innecesaria |
| Comprobación de salud | `HEALTHCHECK` sobre `GET /health` con `urllib`, en formato JSON | Docker marca el contenedor como sano o no sano. Se usa `urllib` porque la imagen `slim` no incluye `curl`. El formato JSON evita lanzar un shell intermedio (`DL3025`) |
| Arranque | `uvicorn` con `--host 0.0.0.0` | Si escuchara solo en `127.0.0.1`, no sería accesible desde fuera del contenedor |

## Contexto de build y `.dockerignore`

El contexto de build es la carpeta de cada servicio, por lo que su `.dockerignore` está en esa misma carpeta, ya que Docker lo busca en la raíz del contexto. Excluye cachés de Python, entornos virtuales, tests, la configuración de herramientas y los ficheros `.env`, de modo que la imagen solo contiene `app/` y no se cuelan credenciales por error.

## Limitaciones conocidas

Los `requirements.txt` fijan rangos de versiones (por ejemplo `fastapi>=0.115,<1`) y no versiones exactas con *hashes*, por lo que dos construcciones en fechas distintas pueden instalar versiones diferentes. Bloquear las dependencias con un *lockfile* con *hashes* (`pip-compile --generate-hashes` e instalación con `--require-hashes`) se aborda en el hito de seguridad.

## Verificación

```bash
docker run --rm document-service whoami     # appuser
docker run --rm document-service which gcc  # sin salida: el compilador no está en la imagen final
```
