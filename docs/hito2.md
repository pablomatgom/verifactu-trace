# Hito 2: integración continua

Este documento recoge las decisiones técnicas del Hito 2 y las razones de cada una: el gestor de tareas, la biblioteca de aserciones, el marco de pruebas y el sistema de integración continua. Después explica qué lógica de negocio se prueba y cómo se ejecuta todo.

El detalle de los workflows (trabajos, permisos, caché, pruebas de integración con Docker Compose y publicación de imágenes) está en [`ci.md`](ci.md), y al final de este documento hay una tabla con los entregables del hito y el lugar donde se cumple cada uno. Aquí se justifica **por qué** se eligió cada herramienta frente a sus alternativas, reconociendo también sus inconvenientes.

| Decisión | Elección |
|---|---|
| Gestor de tareas | GNU Make (`Makefile`) |
| Biblioteca de aserciones | El `assert` de Python, con la introspección de `pytest` |
| Estilo de pruebas | Orientado a TDD: pruebas pequeñas, una por regla de negocio |
| Marco de pruebas | `pytest` |
| Integración continua | GitHub Actions |

## Gestor de tareas: GNU Make

El enunciado pide que las pruebas se lancen **igual en local y en remoto**. Para ello los comandos viven en un único sitio, el [`Makefile`](../Makefile), y el CI los llama en lugar de repetirlos en su YAML.

```bash
make test                            # pytest de los tres servicios
make test SERVICE=document-service   # de uno solo
make lint                            # ruff check y ruff format --check
make format                          # ruff check --fix y ruff format
make up                              # el sistema completo con Docker Compose
make down                            # lo para
make clean                           # lo para y borra los datos
```

| Alternativa | Por qué no |
|---|---|
| `just` o `Task` (go-task) | Tienen una sintaxis más cómoda y funcionan igual en Windows, pero son una herramienta más que instalar, también en cada ejecución del CI, y que el lector del repositorio no conoce de antemano |
| `tox` o `nox` | Son excelentes para probar contra varias versiones de Python, que aquí no hace falta (solo 3.12, la de las imágenes), y no sirven para lanzar `docker compose` ni el lint |
| Scripts en `pyproject.toml` (`hatch`, `poethepoet`) | Atan las tareas a Python y a una herramienta de empaquetado que el proyecto no usa |
| Scripts de shell sueltos | No declaran dependencias entre tareas (`make up` crea antes el `.env` si falta) ni se pueden listar con una orden como `make help` |

**Por qué Make.** Es el estándar de hecho para este fin, el que cita el enunciado, y los runners de GitHub Actions ya lo traen instalado, de modo que no añade pasos ni dependencias al CI. Sabe declarar dependencias entre tareas, y el lenguaje de las recetas es el `sh` que ya se usa en el resto del proyecto.

**Inconvenientes que se han tenido en cuenta:**

- En Windows `make` no viene instalado (`choco install make` o `scoop install make`) y las recetas se lanzan desde Git Bash, porque son de `sh`. Está documentado en [`ci.md`](ci.md).
- Exige tabuladores y finales de línea LF. Con `core.autocrlf=true`, Git escribiría el fichero con CRLF en Windows y `make` fallaría en cada línea; por eso [`.gitattributes`](../.gitattributes) fija `eol=lf` para el `Makefile`.
- No es portable a plataformas sin `sh`. Se acepta, porque el sistema se ejecuta en contenedores Linux y el CI corre en Ubuntu.

## Biblioteca de aserciones: el `assert` de `pytest`

Las pruebas usan la sentencia `assert` de Python. `pytest` la reescribe al importar el módulo para que, cuando falla, muestre el valor de cada lado, la diferencia entre dos estructuras y la expresión evaluada, sin escribir nada especial.

```python
assert delays == [
    timedelta(seconds=5),
    timedelta(seconds=10),
    timedelta(seconds=20),
    timedelta(seconds=40),
]
```

Para las excepciones se usa `pytest.raises` con `match`, que además comprueba el mensaje (40 usos en el proyecto):

```python
with pytest.raises(IntegrityError, match="ck_document_lines_quantity_not_zero"):
    document_repository.add(session, document)
```

| Alternativa | Por qué no |
|---|---|
| `unittest` (`assertEqual`, `assertRaises`...) | Obliga a heredar de `TestCase` y a elegir entre decenas de métodos; el mensaje de fallo es peor |
| `assertpy`, `PyHamcrest`, `expects` | Aserciones encadenadas (`assert_that(x).is_equal_to(y)`) que añaden una dependencia y un estilo propio a cambio de poco: el `assert` plano ya se lee como una frase |
| `pytest-check` | Permite varias comprobaciones por prueba sin cortar en la primera, pero se prefiere que cada prueba compruebe una sola cosa |

**Por qué.** No añade dependencias, se lee como Python normal y el diagnóstico de los fallos es muy bueno. El análisis de SonarCloud refuerza dos hábitos que se aplican en todo el proyecto: no mezclar varias condiciones en una misma aserción (`assert a and b` se divide en dos) y dejar dentro de `pytest.raises` **una sola** llamada que pueda lanzar la excepción, para que la prueba no pase por una causa distinta de la que se quiere comprobar.

**Inconvenientes:** `assert` depende de la reescritura de `pytest` (con otro ejecutor no daría los mismos mensajes) y una aserción compleja puede ser difícil de leer. Para eso se divide en variables intermedias.

### Estilo: TDD frente a BDD

Se elige un estilo **orientado a TDD**: pruebas unitarias y de integración pequeñas, una por regla de negocio, con la estructura *preparar, actuar, comprobar* y un nombre que describe el comportamiento y no la función probada:

```python
def test_a_rollback_gives_the_number_back(session): ...
def test_a_deleted_event_is_detected_even_if_the_next_one_is_rechained(): ...
def test_the_wait_never_exceeds_the_maximum(attempts): ...
```

| Estilo | Qué aporta | Por qué no aquí |
|---|---|---|
| BDD con `behave` o `pytest-bdd` | Escenarios escritos en lenguaje natural (*Gherkin*) que puede leer alguien sin conocimientos técnicos | Añade una capa de ficheros `.feature` y de pegamento por cada prueba. Aquí quien escribe y lee las pruebas es el desarrollador, y el producto es una API, no una aplicación con un cliente de negocio que valide los escenarios |

Hay un matiz importante: los **criterios de aceptación** de las historias de usuario sí están escritos como *Dado, cuando, entonces* (es lo que pide la plantilla de issue), y cada uno se implementa como una o varias pruebas. El enfoque de BDD se aprovecha en la especificación, y las pruebas se escriben con el estilo directo de TDD.

Las pruebas se escriben junto con la funcionalidad, no siempre antes. Lo que sí se hace es comprobar que detectan lo que dicen detectar: quitando a propósito una regla del código (el límite de cantidad, un bloqueo de fila, el desempate de un orden...) y verificando que alguna prueba falla. Más de una vez ese ejercicio mostró una regla que ninguna prueba cubría.

## Marco de pruebas: `pytest`

`pytest` encuentra los ficheros `test_*.py`, ejecuta las funciones `test_*` e informa de los resultados. Se usa la versión 8 (`pytest>=8.0,<9` en [`requirements-dev.txt`](../requirements-dev.txt)).

| Alternativa | Por qué no |
|---|---|
| `unittest` | Viene con Python, pero exige clases, `setUp` y `tearDown` y no tiene parametrización ni fixtures encadenables |
| `nose2` | Es un proyecto con poca actividad frente a `pytest` |
| `Robot Framework` | Pensado para pruebas de aceptación con palabras clave, más pesado de lo que se necesita |

**Qué aporta en este proyecto**, con ejemplos reales:

- **Fixtures encadenables y con alcance.** `alembic_cfg`, `engine`, `session` y `client` se construyen unos a partir de otros ([`conftest.py`](../services/document-service/tests/conftest.py)). La sesión de cada prueba corre dentro de una transacción que se deshace al terminar, así que las pruebas no se influyen entre sí aunque compartan base de datos.
- **Parametrización** (`@pytest.mark.parametrize`, 60 usos): la misma regla con muchos casos, como cada campo de una rectificativa que puede ser inválido, sin repetir la prueba.
- **`monkeypatch`** (71 usos): sustituye una dependencia en una prueba y la restaura después, por ejemplo para forzar una carrera entre dos peticiones simultáneas.
- **Omitir o fallar según el entorno.** Las fixtures de base de datos y de Redis omiten las pruebas en local si falta la URL, pero las hacen **fallar** en el CI (donde existe la variable `CI`). Así un CI mal configurado no parece un CI en verde sin pruebas.
- **El cliente de pruebas de FastAPI** (`TestClient`) llama a la aplicación sin levantar un servidor.

**Inconvenientes:** las fixtures funcionan por nombre y pueden resultar mágicas para quien no conoce `pytest`. Y dos ficheros con el mismo nombre en carpetas distintas (por ejemplo `tests/api/test_x.py` y `tests/unit/test_x.py`) chocan al importarse, porque las carpetas de pruebas no son paquetes; la solución adoptada es usar nombres únicos.

## Integración continua: GitHub Actions

Los workflows se definen en [`.github/workflows/`](../.github/workflows/) y se activan en cada pull request hacia `main` y en cada push a `main`. El resultado se ve en el propio pull request, antes de fusionarlo.

| Alternativa | Por qué no |
|---|---|
| Jenkins | Es gratuito, pero hay que alojar y mantener un servidor (actualizaciones, agentes, seguridad), y el proyecto debe poder ejecutarse sin infraestructura propia |
| Travis CI | Ya no ofrece el servicio gratuito ilimitado para código abierto de otros tiempos |
| CircleCI | Ofrece un plan gratuito, pero con límites de créditos, y es un servicio más que conectar al repositorio |
| GitLab CI | Exigiría trabajar en GitLab o duplicar el repositorio |

**Por qué.**

- Es **gratuito** para repositorios públicos, como pide el enunciado.
- Está **integrado** en el repositorio: los workflows son ficheros YAML versionados, el resultado aparece en la propia pull request y no hay un servicio externo que conectar ni una cuenta más que gestionar.
- Permite **contenedores de servicio** (PostgreSQL y Redis desechables en cada trabajo), **matrices** (un trabajo por microservicio) y levantar el sistema completo con Docker Compose.
- El `GITHUB_TOKEN` del propio workflow publica las imágenes en GitHub Container Registry, sin guardar credenciales en el repositorio.
- Convive con otros sistemas: SonarCloud analiza el código en cada pull request.

**Inconvenientes:** los workflows están atados a GitHub (cambiar de plataforma obligaría a reescribirlos), el uso en repositorios privados tiene una cuota de minutos, y las acciones de terceros son una dependencia externa. Se mitiga fijando la versión de las acciones (`actions/checkout@v7`) y la del runner (`ubuntu-24.04`), y limitando los permisos del workflow a `contents: read`.

### Qué ejecuta

| Trabajo | Comando |
|---|---|
| `lint` | `make lint` |
| `test` (uno por servicio, en paralelo) | `make test SERVICE=<servicio>`, con una PostgreSQL y una Redis desechables |
| `integration` | `make up`, y comprobaciones de la salud, los esquemas y las migraciones |
| `hadolint`, `build` (workflow `Docker`) | Análisis de los Dockerfiles, construcción y publicación de las imágenes |

## Qué lógica de negocio se prueba

El proyecto tiene **498 pruebas** (220 de `document-service`, 141 de `traceability-service` y 137 de `submission-service`), en 56 ficheros. Se reparten en cuatro niveles:

| Nivel | Qué comprueba | Ejemplos |
|---|---|---|
| Unitarias | Funciones puras, sin base de datos ni red | El cálculo del hash ([`test_hashing.py`](../services/traceability-service/tests/unit/test_hashing.py)), la espera creciente de los reintentos ([`test_retry.py`](../services/submission-service/tests/unit/test_retry.py)), el formato de la numeración, los importes con su redondeo, la comparación de líneas de una cadena |
| De servicio y de API con PostgreSQL real | Las reglas de negocio sobre la base de datos de verdad, no sobre un simulacro | La numeración correlativa **y sin huecos**: un *rollback* devuelve el número ([`test_counter.py`](../services/document-service/tests/repositories/test_counter.py)); las cantidades entregadas, que no pueden superar las pedidas; los estados de un envío |
| De concurrencia | Peticiones simultáneas con transacciones que se confirman de verdad | Dos albaranes, dos facturas o dos rectificativas a la vez no pueden pasarse de lo que quedaba; un envío bloqueado por una réplica lo salta la otra |
| De integración con Redis y de sistema | Que las piezas funcionan juntas | El evento `invoice.issued` llega de verdad al *stream* y se consume una sola vez; `docker compose up` deja los cinco contenedores sanos |

Reglas de negocio con pruebas propias, entre otras:

- **Cadena de hashes** (CU-9 y CU-10): que el hash cambie si cambia cualquier parte del evento o el hash anterior; que se detecte un evento alterado, sustituido o borrado, incluso si quien lo borró recalculó los hashes siguientes; y, a propósito, que **no** se detecte el borrado de los últimos eventos, dejando constancia de ese límite.
- **Numeración fiscal** (CU-1 a CU-3): series, año, contador sin huecos y número que no se reutiliza.
- **Cadena documental** (CU-2, CU-3, CU-6 y CU-8): un albarán se puede entregar en partes sin superar el pedido, una factura por albarán (también a nivel de base de datos), la anulación solo de lo que no se ha facturado y las rectificativas sin devolver más de lo facturado.
- **Reintentos** (CU-13 a CU-16): espera que se duplica, intentos agotados, envío dado por perdido, y el reenvío manual con sus intentos reiniciados.
- **Idempotencia de los eventos:** si el *stream* entrega dos veces la misma entrada, no se registra dos veces.

## Entregables del hito y dónde se cumplen

El enunciado del Hito 2 pide tres entregables. Esta tabla dice dónde está cada requisito y en qué documento se explica.

### Dockerfiles de producción (uno por microservicio)

| Requisito | Dónde se cumple |
|---|---|
| Construcción multietapa | Etapas `builder` y `runtime` en `services/<servicio>/Dockerfile`. La primera instala las dependencias y la segunda solo recibe el entorno virtual y el código ([`docker.md`](docker.md)) |
| Imagen base minimalista, fundamentada | `python:3.12-slim`, con las alternativas descartadas (`alpine`, `distroless`) y el porqué en la tabla de decisiones de [`docker.md`](docker.md) |
| Mínimo privilegio | `appuser`, un usuario de sistema sin shell, con UID y GID `10001`, y `USER 10001:10001` en la imagen final |
| Optimización de la caché de capas | `requirements.txt` se copia e instala antes que el código, y `.dockerignore` limita el contexto de construcción |
| Exposición de puertos | `EXPOSE 8001`, `8002` y `8003`, y un `HEALTHCHECK` sobre `GET /health` |

### Orquestación local (`compose.yaml`)

| Requisito | Dónde se cumple |
|---|---|
| Al menos 3 contenedores | Cinco: los tres servicios, PostgreSQL y Redis ([`compose.md`](compose.md)) |
| Redes virtuales aisladas | `edge` para los servicios y `data` (`internal: true`) para PostgreSQL y Redis |
| Volúmenes persistentes | `postgres-data` y `redis-data` (con `--appendonly yes`) |
| Variables de entorno desde un archivo de ejemplo | `.env.example`, sin credenciales reales; `.env` está en `.gitignore` y Compose falla con un mensaje claro si falta una variable |
| Un único comando | `docker compose up --build`, o `make up` |

### Integración continua

| Requisito | Dónde se cumple |
|---|---|
| Eventos `push` y `pull_request` a la rama principal | `ci.yml` y `docker.yml` se activan en los dos casos ([`ci.md`](ci.md)) |
| Linters de código | `ruff check` y `ruff format --check`, con `make lint` (trabajo `lint` de `ci.yml`) |
| Linter de Dockerfiles | `hadolint` (trabajo `hadolint` de `docker.yml`) |
| Pruebas unitarias | `pytest` de cada servicio (trabajo `test` de `ci.yml`, uno por servicio) |
| Pruebas de integración | Con PostgreSQL y Redis reales en el trabajo `test`, y con el sistema completo en el trabajo `integration` (`docker compose up --wait`) |
| Construcción y publicación en GHCR | Trabajo `build` de `docker.yml`: construye la imagen de cada servicio y, fuera de los pull requests, la publica en `ghcr.io/pablomatgom/verifactu-trace/<servicio>` |
| Etiquetas con la versión o el hash del commit | `sha-<commit>` y `latest` en cada push a `main`, y la versión semántica (`1.0.0`) al subir un tag `v*` |

El enunciado agrupa todo esto en un único `ci.yml`. Aquí se reparte en dos workflows: `ci.yml` valida el código (lint, pruebas e integración) y `docker.yml` valida y publica las imágenes. Los dos se lanzan con los mismos eventos y cada uno se ve como un conjunto de trabajos independiente en la pull request. Separarlos hace que un fallo de estilo en el código no oculte uno en un Dockerfile, y al revés, y mantiene cada fichero corto y centrado en una responsabilidad, con la construcción de las imágenes usando su propia caché de capas.

### Evidencias

La salida real de los comandos y las capturas de GitHub y SonarCloud que demuestran lo anterior están en [`evidencias/`](evidencias/README.md).

## Cómo ejecutar las pruebas

```bash
make test                              # los tres servicios
make test SERVICE=submission-service   # uno
make test PYTEST_ARGS="-x -k invoice"  # con argumentos para pytest
make lint
```

Las pruebas necesitan una PostgreSQL y una Redis, que se indican con `DATABASE_URL` y `REDIS_URL`; sin ellas, `make test` avisa y se omiten en local las pruebas que las necesitan (en el CI fallan). En [`database.md`](database.md) está cómo levantarlas. Cada servicio se prueba por separado, desde su carpeta, porque los tres tienen un paquete llamado `app`.
