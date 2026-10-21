# Integración continua

La integración continua se define en dos workflows de GitHub Actions, en `.github/workflows/`. Se ejecutan en `ubuntu-24.04`, versión fijada para que una migración de `ubuntu-latest` no cambie el entorno sin avisar.

| Workflow | Fichero | Qué comprueba |
|---|---|---|
| CI | [`ci.yml`](../.github/workflows/ci.yml) | Calidad del código Python: lint, formato y tests |
| Docker | [`docker.yml`](../.github/workflows/docker.yml) | Calidad de los Dockerfiles y construcción y publicación de las imágenes |

Ambos se lanzan en cada pull request hacia `main` y en cada push a `main`. `docker.yml` también se lanza al subir un tag `v*`.

## CI: lint y tests

`ci.yml` tiene dos trabajos independientes, que se ejecutan en paralelo: `lint` y `test`. Si uno falla, el otro termina igualmente y se ven los dos resultados.

### Trabajos

| Trabajo | Qué hace | Comando |
|---|---|---|
| `lint` | Comprueba el estilo y los errores comunes, y que el código está formateado | `ruff check .` y `ruff format --check .` |
| `test` | Ejecuta las pruebas de un servicio. Una instancia por servicio (`document-service`, `traceability-service` y `submission-service`) | `python -m pytest` desde `services/<servicio>` |

Ambos usan Python 3.12, la misma versión que las imágenes Docker, y instalan las dependencias desde `requirements-dev.txt`, que agrupa las de los tres servicios y las herramientas de desarrollo.

### Qué revisa `ruff`

La configuración está en [`ruff.toml`](../ruff.toml), y es la misma en local y en CI:

- **Reglas por defecto de `ruff`**: errores de sintaxis, imports sin usar, nombres sin definir y otros fallos típicos.
- **Orden de los imports** (`I`, equivalente a `isort`), con `app` declarado como paquete propio para que los imports de cada servicio se agrupen bien.
- **Formato**: líneas de hasta 100 caracteres. `ruff format --check` no modifica nada, solo falla si el código no está formateado.

### Qué hacen los tests

Cada servicio tiene sus pruebas en `tests/` y las ejecuta `pytest`. De momento solo comprueban `GET /health`, y crecerán con cada historia de usuario. Usan el cliente de pruebas de FastAPI (`TestClient`), que llama a la aplicación sin levantar un servidor.

`pytest` se lanza **por servicio**, desde su carpeta, y no una sola vez desde la raíz. Los tres servicios tienen un paquete llamado `app`, y al ejecutarlos juntos Python solo importaría uno de ellos. La carpeta de cada servicio se añade al `pythonpath` mediante su `pyproject.toml`.

### Decisiones de diseño

| Decisión | Elección | Motivo |
|---|---|---|
| Disparadores | Pull request hacia `main` y push a `main` | El pull request avisa antes de mergear. El push comprueba que `main` sigue sano tras el *squash and merge* |
| Permisos | `contents: read` | El workflow solo lee el código y no necesita escribir en el repositorio |
| Versión de Python | `3.12`, igual que los Dockerfiles | Evita que una prueba pase en CI con una versión distinta a la que se despliega |
| Dependencias | Instalación desde `requirements-dev.txt` | Un solo fichero para el lint y las pruebas. `ruff` y `pytest` no están en las imágenes de producción |
| Caché de `pip` | `cache: pip`, con la clave en `requirements-dev.txt` y en los `requirements.txt` de los servicios | Reutiliza las descargas entre ejecuciones, y se invalida al cambiar cualquier dependencia |
| Matriz de pruebas | Un trabajo por servicio, con `fail-fast: false` | Un fallo en un servicio no cancela las pruebas de los otros |
| Lint y pruebas separados | Dos trabajos en paralelo | Un error de formato no oculta un fallo de pruebas, y al revés |
| Runner | `ubuntu-24.04` fijo | `ubuntu-latest` migrará a otra versión sin aviso, y podría cambiar el entorno |

### Reproducir el CI en local

```bash
ruff check .
ruff format --check .
cd services/document-service && python -m pytest
```

Para que `ruff format --check` pase antes de subir los cambios, se puede ejecutar `ruff format .`, que sí modifica los ficheros.

### Si el CI falla

| Fallo | Causa habitual | Solución |
|---|---|---|
| `ruff check` con `I001` | Imports desordenados | `ruff check --fix .` |
| `ruff format --check` | Código sin formatear | `ruff format .` |
| `pytest` falla en un solo servicio | El cambio afecta a ese servicio | Entrar en `services/<servicio>` y ejecutar `python -m pytest` |
| Falla la instalación de dependencias | Un rango de versiones en `requirements.txt` ya no se puede resolver | Revisar el rango del paquete que indica el error |

## Docker: lint, construcción y publicación

### Trabajos

| Trabajo | Qué hace | Cuándo |
|---|---|---|
| `hadolint` | Analiza el `Dockerfile` de cada servicio | Pull request y push |
| `build` | Construye la imagen de cada servicio. Depende de `hadolint` | Pull request y push |
| Publicación | Último paso de `build`: sube la imagen a GHCR | Solo en push a `main` y en tags `v*` |

En un pull request la imagen se construye pero **no se publica**. Así se detecta un Dockerfile roto antes de mergear, sin dejar imágenes de ramas sin revisar en el registro.

### Imágenes publicadas

Las imágenes se publican en GitHub Container Registry, una por servicio:

```
ghcr.io/pablomatgom/verifactu-trace/document-service
ghcr.io/pablomatgom/verifactu-trace/traceability-service
ghcr.io/pablomatgom/verifactu-trace/submission-service
```

| Etiqueta | Cuándo se crea | Para qué sirve |
|---|---|---|
| `sha-<commit>` | En cada push a `main` | Identifica exactamente qué código contiene la imagen y permite volver a una versión anterior |
| `latest` | En cada push a `main` | Apunta a la última versión de la rama principal |
| `1.0.0` | Al subir el tag `v1.0.0` | Versión estable, tal y como se etiqueta una release |

Para publicar una versión estable basta con crear un tag:

```bash
git tag v1.0.0
git push origin v1.0.0
```

`latest` es cómoda pero cambia con el tiempo, así que un despliegue reproducible debe fijar `sha-<commit>` o una versión.

### Decisiones de diseño

| Decisión | Elección | Motivo |
|---|---|---|
| Workflow separado | `docker.yml` aparte de `ci.yml` | `ci.yml` solo necesita leer el código. El permiso de escribir paquetes se concede únicamente a `docker.yml` |
| Permisos | `contents: read` global y `packages: write` solo en el trabajo `build` | Mínimo privilegio: un fallo en otro trabajo no puede publicar imágenes |
| Autenticación | `GITHUB_TOKEN` | Es un token temporal de cada ejecución. No hay contraseñas ni tokens personales guardados como secreto |
| Linter | Hadolint | Revisa el Dockerfile contra buenas prácticas antes de gastar tiempo en construir |
| Matriz | Un trabajo por servicio, con `fail-fast: false` | Si falla un servicio se sigue viendo el resultado de los otros dos |
| Caché de capas | `type=gha` con un ámbito por servicio | Reutiliza capas entre ejecuciones y evita que los servicios se pisen la caché |
| Etiquetas | Generadas con `docker/metadata-action` | Calcula las etiquetas a partir del commit o del tag, y pone en minúsculas el nombre de la imagen, como exige GHCR |
| Acciones de terceros | Fijadas a un SHA de commit completo, con la versión en un comentario | Un tag como `@v4` puede reescribirse si el repositorio de la acción se ve comprometido. Un SHA no |

### Primera publicación

GHCR crea cada paquete como **privado** la primera vez que se publica. Si las imágenes deben poder descargarse sin autenticación, hay que cambiar su visibilidad en *Package settings* de cada paquete.

## Limitaciones conocidas

- Las imágenes no se escanean en busca de vulnerabilidades. Se aborda en el hito de seguridad junto con el *lockfile* con hashes descrito en [`docker.md`](docker.md).
- Los SHA de las acciones se actualizan a mano. Dependabot podría proponer las actualizaciones automáticamente.
- Los tests no miden cobertura. Se puede añadir cuando haya lógica de negocio que cubrir.
- Los workflows no definen `timeout-minutes` ni `concurrency`. Un trabajo colgado consume minutos hasta el límite de GitHub, y varios push seguidos a la misma rama lanzan ejecuciones que no se cancelan entre sí.
- Los tests de integración contra PostgreSQL y Redis todavía no se ejecutan en CI. Se añadirán con las historias que usen la base de datos.
