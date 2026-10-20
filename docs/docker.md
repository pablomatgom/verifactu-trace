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
| Construcción multietapa | Etapa `builder` y etapa `runtime` | Las herramientas de compilación (`build-essential`) solo existen en la primera etapa y se descartan, por lo que nunca llegan a la imagen final |
| Dependencias | Entorno virtual en `/opt/venv` | Deja todas las librerías en una única carpeta que se copia en bloque a la etapa final con `COPY --from=builder` |
| Caché de capas | `requirements.txt` se copia y se instala antes que el código | Si solo cambia el código, la capa de dependencias se reutiliza y la construcción tarda segundos |
| Usuario | `appuser`, usuario de sistema sin shell ni directorio personal | Principio de mínimo privilegio: el proceso no se ejecuta como `root` |
| Variables de Python | `PYTHONUNBUFFERED=1` y `PYTHONDONTWRITEBYTECODE=1` | Los logs salen por `stdout` sin retraso, algo necesario para observarlos en un contenedor, y no se generan ficheros `.pyc` inútiles |
| Variables de `pip` | `PIP_NO_CACHE_DIR=1` y `PIP_DISABLE_PIP_VERSION_CHECK=1` | Evitan guardar la caché de descargas en la imagen y una consulta de red innecesaria |
| Comprobación de salud | `HEALTHCHECK` sobre `GET /health` con `urllib` | Docker marca el contenedor como sano o no sano. Se usa `urllib` porque la imagen `slim` no incluye `curl` |
| Arranque | `uvicorn` con `--host 0.0.0.0` | Si escuchara solo en `127.0.0.1`, no sería accesible desde fuera del contenedor |

## Contexto de build y `.dockerignore`

El contexto de build es la carpeta de cada servicio, por lo que su `.dockerignore` está en esa misma carpeta, ya que Docker lo busca en la raíz del contexto. Excluye cachés de Python, entornos virtuales, tests, la configuración de herramientas y los ficheros `.env`, de modo que la imagen solo contiene `app/` y no se cuelan credenciales por error.

## Verificación

```bash
docker run --rm document-service whoami     # appuser
docker run --rm document-service which gcc  # sin salida: el compilador no está en la imagen final
```
