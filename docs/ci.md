# Integración continua

Por qué se eligieron `make`, `pytest` y GitHub Actions frente a sus alternativas está en [`hito2.md`](hito2.md). Este documento describe cómo están configurados.

La integración continua se define en dos workflows de GitHub Actions, en `.github/workflows/`. Se ejecutan en `ubuntu-24.04`, versión fijada para que una migración de `ubuntu-latest` no cambie el entorno sin avisar.

| Workflow | Fichero | Qué comprueba |
|---|---|---|
| CI | [`ci.yml`](../.github/workflows/ci.yml) | Calidad del código Python: lint, formato y tests |
| Docker | [`docker.yml`](../.github/workflows/docker.yml) | Calidad de los Dockerfiles y construcción y publicación de las imágenes |

Ambos se lanzan en cada pull request hacia `main` y en cada push a `main`. `docker.yml` también se lanza al subir un tag `v*`.

## CI: lint y tests

`ci.yml` tiene tres trabajos independientes, que se ejecutan en paralelo: `lint`, `test` e `integration`. Si uno falla, los otros terminan igualmente y se ven todos los resultados.

### Trabajos

| Trabajo | Qué hace | Comando |
|---|---|---|
| `lint` | Comprueba el estilo y los errores comunes, y que el código está formateado | `make lint` (`ruff check .` y `ruff format --check .`) |
| `test` | Ejecuta las pruebas de un servicio, con una PostgreSQL y una Redis desechables como servicios del trabajo. Una instancia por servicio (`document-service`, `traceability-service` y `submission-service`) | `make test SERVICE=<servicio>` (`python -m pytest` desde `services/<servicio>` |
| `integration` | Levanta el sistema completo con Docker Compose y comprueba que los cinco contenedores funcionan juntos | `make up` (`docker compose up --build --wait`) |

Ambos usan Python 3.12, la misma versión que las imágenes Docker, y instalan las dependencias desde `requirements-dev.txt`, que agrupa las de los tres servicios y las herramientas de desarrollo.

### Qué revisa `ruff`

La configuración está en [`ruff.toml`](../ruff.toml), y es la misma en local y en CI:

- **Reglas por defecto de `ruff`**: errores de sintaxis, imports sin usar, nombres sin definir y otros fallos típicos.
- **Orden de los imports** (`I`, equivalente a `isort`), con `app` declarado como paquete propio para que los imports de cada servicio se agrupen bien.
- **Formato**: líneas de hasta 100 caracteres. `ruff format --check` no modifica nada, solo falla si el código no está formateado.

### Base de datos y Redis en los tests

El trabajo `test` define `DATABASE_URL` y levanta un contenedor `postgres:17-alpine` como servicio, con el healthcheck de `pg_isready`, de modo que los pasos solo empiezan cuando la base de datos responde. Las credenciales (`test-only`) son de una base de datos que desaparece al terminar el trabajo, y no hay secretos. Si `DATABASE_URL` falta en el CI, los tests fallan en lugar de omitirse.

Con `REDIS_URL` y un contenedor `redis:7-alpine` (healthcheck `redis-cli ping`) pasa lo mismo: sirve para los tests que comprueban que el evento `invoice.issued` llega de verdad al *stream*, y si `REDIS_URL` falta en el CI, esos tests fallan en lugar de omitirse. Los demás tests no necesitan Redis, porque el publicador se sustituye por uno falso. El detalle está en [`database.md`](database.md).

### Qué hacen los tests

Cada servicio tiene sus pruebas en `tests/` y las ejecuta `pytest`. Cubren las migraciones, los endpoints de todos los casos de uso y las reglas de negocio de cada servicio:

- **`document-service`**: la numeración correlativa sin huecos, el cálculo de importes, los pedidos, albaranes, facturas y rectificativas con sus límites de cantidad, la consulta y el listado, la anulación, las discrepancias entre documentos y la publicación del evento `invoice.issued`. Las peticiones simultáneas a un mismo albarán, factura o pedido se prueban con transacciones que se confirman de verdad.
- **`traceability-service`**: el cálculo y el encadenado de los hashes (con su concurrencia), la verificación de la cadena con eventos alterados, sustituidos o borrados, el histórico, la cadena documental (con un cliente HTTP probado contra un servidor local) y el consumidor del *stream* contra un Redis real.
- **`submission-service`**: los estados y los reintentos de un envío (esperas crecientes, intentos agotados, envíos perdidos y reintento manual), la AEAT simulada, las consultas y el listado paginado, el consumidor del *stream* contra un Redis real, el proceso de envío y el flujo completo de un evento hasta su aceptación.

Usan el cliente de pruebas de FastAPI (`TestClient`), que llama a la aplicación sin levantar un servidor. Los niveles de pruebas y los ejemplos de cada regla están en [`hito2.md`](hito2.md), y la parte de bases de datos en [`database.md`](database.md).

`pytest` se lanza **por servicio**, desde su carpeta, y no una sola vez desde la raíz. Los tres servicios tienen un paquete llamado `app`, y al ejecutarlos juntos Python solo importaría uno de ellos. La carpeta de cada servicio se añade al `pythonpath` mediante su `pyproject.toml`.

### Prueba de integración con Docker Compose

Las pruebas unitarias comprueban cada servicio por separado. El trabajo `integration` comprueba lo que ellas no pueden: que las piezas funcionan **juntas**. Es el mismo procedimiento que se sigue en local, automatizado:

1. Crea `.env` a partir de `.env.example`.
2. Ejecuta `make up`, que lanza `docker compose up --build --wait --wait-timeout 180`. Construye las tres imágenes y espera a que todos los contenedores estén sanos. Si alguno no lo consigue en tres minutos, el trabajo falla.
3. Llama a `GET /health` de cada servicio en los puertos `8001`, `8002` y `8003`, con reintentos.
4. Consulta PostgreSQL y comprueba que existen los tres esquemas (`documents`, `traceability` y `submissions`), lo que verifica que el script de inicialización se ejecutó.
5. Comprueba que los tres servicios aplicaron sus migraciones al arrancar (consulta su tabla `alembic_version`).
6. Si algo falla, muestra los logs de todos los contenedores.
7. Siempre, al terminar, apaga el sistema y elimina los volúmenes (`docker compose down -v`).

Con ello se valida además el propio `compose.yaml`: las redes, el orden de arranque y las comprobaciones de salud. Las pruebas de la API contra PostgreSQL y Redis las hace el trabajo `test`; este comprueba solo que las piezas arrancan y se conectan entre sí.

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

El CI llama a los mismos objetivos del [`Makefile`](../Makefile) que se usan en local, así que se reproduce con:

```bash
make lint
make test SERVICE=document-service   # o sin SERVICE, para los tres servicios
```

`make test` necesita `DATABASE_URL` y `REDIS_URL` apuntando a una PostgreSQL y una Redis (ver [`database.md`](database.md)). Si faltan, avisa y omite los tests que las necesitan, mientras que en el CI esos tests fallan. Para que `make lint` pase antes de subir los cambios, `make format` formatea el código y ordena los imports, que es lo único que modifica ficheros.

### El gestor de tareas

Los comandos viven en el [`Makefile`](../Makefile), y el CI los llama en lugar de repetirlos en el YAML. Así, lo que pasa en local es lo que pasa en el CI.

| Objetivo | Qué hace |
|---|---|
| `make help` | Lista los objetivos |
| `make test` | `pytest` de los tres servicios, uno detrás de otro, desde la carpeta de cada uno. Un servicio que falla no detiene a los demás, y el objetivo falla al final. `SERVICE=<nombre>` limita a uno y `PYTEST_ARGS` pasa argumentos a `pytest` |
| `make lint` | `ruff check .` y `ruff format --check .` |
| `make format` | `ruff check --fix .` y `ruff format .` |
| `make up` | Crea `.env` si falta y ejecuta `docker compose up --build --wait --wait-timeout 180` |
| `make down` | `docker compose down`: para el sistema y conserva los datos |
| `make clean` | `docker compose down -v`: para el sistema y borra los volúmenes |

`make` viene con Linux y macOS. En Windows se instala con `choco install make` o `scoop install make`, y las órdenes se lanzan desde Git Bash, porque las recetas son de `sh`. El `Makefile` se guarda siempre con finales de línea LF (`.gitattributes`): con CRLF, que es lo que Git escribiría en Windows, `make` falla al leer cada línea.

### Si el CI falla

| Fallo | Causa habitual | Solución |
|---|---|---|
| `ruff check` con `I001` | Imports desordenados | `make format` |
| `ruff format --check` | Código sin formatear | `make format` |
| `pytest` falla en un solo servicio | El cambio afecta a ese servicio | `make test SERVICE=<servicio>` |
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
| `0.2.0` | Al subir el tag `v0.2.0` | Versión estable, tal y como se etiqueta una release. Esta es la del Hito 2 |

Para publicar una versión estable basta con crear un tag anotado sobre `main` y subirlo:

```bash
git tag -a v0.2.0 -m "Hito 2"
git push origin v0.2.0
```

El tag lanza `docker.yml`, que publica `0.2.0` y `sha-<commit>` para cada servicio. `latest` no cambia, porque solo se actualiza desde la rama por defecto.

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
- Los tests no miden cobertura. Se podría añadir un informe (por ejemplo con `pytest-cov`) ahora que los tres servicios tienen lógica de negocio que cubrir.
- Los workflows no definen `timeout-minutes` ni `concurrency`. Un trabajo colgado consume minutos hasta el límite de GitHub, y varios push seguidos a la misma rama lanzan ejecuciones que no se cancelan entre sí.
- La prueba de integración solo comprueba que el sistema arranca, que los esquemas existen y que los tres servicios han aplicado sus migraciones. Las pruebas de Redis las hace el trabajo `test`, no este.
- El trabajo `integration` reconstruye las imágenes en cada ejecución, sin la caché de capas que sí usa `docker.yml`.
- El trabajo `integration` tiene `timeout-minutes: 10`. Los demás trabajos del repositorio todavía no definen límite de tiempo.
