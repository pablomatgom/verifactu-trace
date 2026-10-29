# Capa de datos y migraciones

Los servicios guardan sus datos en PostgreSQL, en un esquema propio cada uno (`documents`, `traceability` y `submissions`). Este documento describe el patrón que aplica `document-service`, que será el mismo en los otros dos servicios cuando necesiten base de datos.

## Estructura del servicio

```
services/document-service/
├── alembic.ini              # configuración de Alembic
├── migrations/
│   ├── env.py               # conexión, esquema y bloqueo de las migraciones
│   ├── script.py.mako       # plantilla de las migraciones nuevas
│   └── versions/            # una migración por cambio del esquema
├── app/
│   ├── api/                 # capa HTTP: rutas, esquemas de entrada y salida y formato de errores
│   ├── services/            # capa de negocio: reglas, numeración, importes
│   ├── repositories/        # capa de datos: consultas contra el esquema
│   ├── models/              # modelos de SQLAlchemy
│   ├── config.py            # variables de entorno
│   ├── db.py                # motor, sesión y base declarativa
│   └── main.py
└── tests/
```

| Capa | Responsabilidad | Qué no sabe |
|---|---|---|
| `api` | Recibir y validar la petición, y devolver la respuesta | SQL |
| `services` | Reglas de negocio | HTTP y SQL |
| `repositories` | Consultas a la base de datos | HTTP y reglas de negocio |

Cada capa solo habla con la siguiente. Así las reglas se pueden probar sin servidor ni base de datos, y el acceso a datos queda en un único sitio. El patrón, su equivalencia con *controller / service / repository* y la comparación con una organización por componentes están en [`arquitectura.md`](arquitectura.md).

### Ficheros `__init__.py`

Los paquetes de `app/` llevan `__init__.py` aunque Python 3 también importaría carpetas sin él (*namespace packages*). Con un paquete normal los imports son más fiables, y los tres servicios tienen un paquete `app` que no debe mezclarse.

- `app/models/__init__.py` **tiene una función real**: es donde se importan los modelos para que se registren en `Base.metadata`. `env.py` hace `import app.models`, y sin esos imports `--autogenerate` generaría migraciones vacías.
- `migrations/` y `migrations/versions/` **no llevan** `__init__.py`: Alembic carga cada migración por su ruta, no como paquete.
- `tests/` tampoco lo lleva, porque `pytest` se ejecuta por servicio con el `pythonpath` definido en su `pyproject.toml`.

## Configuración

| Variable | Uso | Valor por defecto |
|---|---|---|
| `DATABASE_URL` | URL de conexión a PostgreSQL | Obligatoria |
| `DATABASE_SCHEMA` | Esquema que pertenece al servicio | `documents` |

Compose pasa `DATABASE_URL` con el formato `postgresql://...`. SQLAlchemy lo asociaría al controlador `psycopg2`, que no está instalado, por lo que `config.py` lo convierte a `postgresql+psycopg://` para usar psycopg 3. Así el `compose.yaml` y el `.env` no cambian.

## Modelo de datos

Pedidos, albaranes y facturas comparten una sola tabla, porque el contrato de la API los trata como un único recurso (`/documents`). Cada documento apunta al anterior de la cadena mediante `parent_id`. Hoy solo se crean pedidos (CU-1).

```mermaid
erDiagram
    documents ||--o{ document_lines : "líneas (se borran con él)"
    documents |o--o{ documents : "parent_id: documento anterior"

    documents {
        uuid id PK
        varchar type "ORDER"
        varchar number UK "P-2026-000001"
        varchar status "ISSUED"
        date issue_date
        varchar customer_tax_id
        numeric total_net
        numeric total_vat
        numeric total
        uuid parent_id FK "vacío en un pedido"
        timestamptz created_at
    }
    document_lines {
        uuid id PK
        uuid document_id FK
        int position "desde 1"
        varchar description
        numeric quantity "3 decimales"
        numeric unit_price
        numeric vat_rate "0 a 100"
    }
    document_counters {
        varchar series PK "P"
        int year PK
        int last_number "último emitido"
    }
```

La cadena de documentos se forma con `parent_id`: el albarán (CU-2) apuntará a su pedido y la factura (CU-3) a su albarán. `document_counters` queda suelta porque no tiene clave foránea: `documents.number` se construye con su valor, pero la base de datos no lo comprueba. El diagrama muestra las columnas clave, y las tablas de abajo las detallan todas.

### Tablas

**`documents`**: un documento de la cadena.

| Columna | Tipo | Notas |
|---|---|---|
| `id` | `UUID` | Clave primaria, la asigna el servidor |
| `type` | `VARCHAR(20)` | `ORDER` por ahora. Indexada |
| `series` | `VARCHAR(10)` | `P` para los pedidos |
| `number` | `VARCHAR(40)` | **Único**, como `P-2026-000001` |
| `status` | `VARCHAR(20)` | `ISSUED` por ahora |
| `issue_date` | `DATE` | La pone el servidor con la fecha de hoy |
| `customer_name` | `VARCHAR(200)` | Nombre del cliente |
| `customer_tax_id` | `VARCHAR(20)` | NIF/CIF del cliente. Indexada |
| `total_net`, `total_vat`, `total` | `NUMERIC(12,2)` | Los calcula el servidor |
| `parent_id` | `UUID` | Clave foránea a `documents.id`: el documento anterior de la cadena. Vacío en un pedido |
| `created_at` | `TIMESTAMPTZ` | Valor por defecto `now()` en la base de datos |

**`document_lines`**: las líneas de un documento. Se borran con él (`ON DELETE CASCADE`).

| Columna | Tipo | Notas |
|---|---|---|
| `id` | `UUID` | Clave primaria |
| `document_id` | `UUID` | Clave foránea a `documents.id`. Indexada |
| `position` | `INTEGER` | Orden de la línea, desde 1 |
| `description` | `VARCHAR(300)` | |
| `quantity` | `NUMERIC(12,3)` | Mayor que cero, hasta 3 decimales |
| `unit_price` | `NUMERIC(12,2)` | No negativo |
| `vat_rate` | `NUMERIC(5,2)` | Entre 0 y 100 |

**`document_counters`**: el último número emitido de cada serie y año. La clave primaria es (`series`, `year`), y `last_number` guarda el contador.

### Decisiones de diseño

| Tema | Decisión | Por qué |
|---|---|---|
| Tipos y estados | `DocumentType` y `DocumentStatus` son `StrEnum` de Python (`models/document.py`) y se guardan como texto, no como `ENUM` nativo | Añadir un valor a un `ENUM` de PostgreSQL exige una migración con `ALTER TYPE`. Con texto basta un miembro nuevo en la enumeración |
| Series | `P` para los pedidos, definida en `services/numbering.py` junto al formato del número | Un solo sitio para saber cómo se numera cada tipo |
| Importes | `NUMERIC` en la base de datos y `Decimal` en Python, nunca `float`. En el JSON viajan como números | Evita errores de redondeo binario |
| Cálculo | Lo hace el servidor y la petición no puede enviarlo. Cada línea se redondea a céntimos (mitad hacia arriba) y el IVA se redondea **por línea** | Los totales cuadran con las líneas, como en una factura |
| Restricciones | La base de datos repite las reglas de la API (cantidad > 0, precio ≥ 0, IVA entre 0 y 100) | Última defensa si algo salta la validación de la API |
| Fechas | `created_at` es `timestamptz` e `issue_date` es una fecha sin hora | Una hora sin zona horaria sería ambigua |

### Numeración correlativa

El número sale de `document_counters` con una sola sentencia:

```sql
INSERT INTO document_counters (series, year, last_number) VALUES (:series, :year, 1)
ON CONFLICT (series, year) DO UPDATE SET last_number = document_counters.last_number + 1
RETURNING last_number
```

1. Actualizar la fila **la bloquea hasta el final de la transacción**, así que dos peticiones simultáneas reciben números distintos.
2. El número y el documento se guardan en la **misma transacción**. Si la creación del documento falla, el *rollback* devuelve el número y no quedan huecos.

El coste es que las peticiones de una misma serie y año se ponen en cola mientras dura la transacción. Para registrar pedidos es asumible.

El esquema (`documents`) está escrito en las migraciones, porque Alembic lo fija al autogenerarlas.

## Migraciones con Alembic

Las migraciones son ficheros versionados en `migrations/versions/`. Cada uno describe un cambio del esquema, y Alembic aplica en orden solo los que faltan. La versión actual se guarda en la tabla `alembic_version`, **dentro del esquema del servicio**, para que cada servicio tenga su propio historial.

### Cuándo se ejecutan

El contenedor ejecuta las migraciones al arrancar, antes de levantar el servidor:

```
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app ..."]
```

- Si una migración falla, el contenedor termina con error y **no atiende tráfico** con un esquema desactualizado. `docker compose ps` y los logs muestran el motivo.
- `exec` sustituye el shell por `uvicorn`, de modo que el servidor recibe las señales de parada y el contenedor se detiene limpiamente.
- Si no hay nada que aplicar, `alembic upgrade head` termina al instante y el arranque no se retrasa.

### Qué hace `env.py`

1. **Toma un bloqueo de PostgreSQL** (`pg_advisory_lock`). Si varias réplicas arrancan a la vez, la primera migra y las demás esperan. Cuando entran, ya no tienen nada que aplicar. Sin el bloqueo, dos réplicas intentarían crear las mismas tablas al mismo tiempo.
2. **Crea el esquema** del servicio si no existe (`CREATE SCHEMA IF NOT EXISTS`). Así el servicio no depende del script `db/init`, que solo se ejecuta con el volumen vacío y no existe en una base de datos gestionada en la nube.
3. **Aplica las migraciones** pendientes, guardando la versión en `<esquema>.alembic_version`.
4. **Libera el bloqueo.**

Alembic solo mira el esquema del servicio al autogenerar migraciones, y no el resto de la base de datos.

### Comandos

Se ejecutan desde `services/document-service`, con `DATABASE_URL` definida:

```bash
alembic revision --autogenerate -m "create orders table"   # genera una migración a partir de los modelos
alembic upgrade head                                       # aplica las migraciones pendientes
alembic downgrade -1                                       # deshace la última
alembic current                                            # versión aplicada
```

Una migración autogenerada **hay que revisarla** antes de commitearla: Alembic no detecta algunos cambios, como el renombrado de una columna, que interpreta como borrar una y crear otra.

Los modelos nuevos deben importarse en `app/models/__init__.py`, o Alembic no los verá.

### Las migraciones en Git

Los ficheros de `migrations/versions/` **se suben al repositorio**, igual que el resto del código. La base de datos solo guarda qué versión tiene aplicada, y los ficheros contienen cómo llegar hasta ella: sin ellos no se puede crear una base de datos nueva ni actualizar una existente. Además, la imagen Docker los copia y el arranque del contenedor los ejecuta.

- **Una migración ya mergeada no se edita.** Si tiene un error, se añade otra migración que lo corrija. Quien ya la aplicó no volvería a ejecutarla, y su base de datos quedaría distinta a la de los demás.
- **Van en la misma PR que el modelo y el código que los usa**, para que cada versión del código tenga el esquema que espera.
- **Si dos ramas crean una migración a la vez**, ambas apuntan a la misma revisión anterior y Alembic informa de dos *heads*. Se resuelve con `alembic merge` o rebasando una de las ramas.
- **Los hooks de `ruff`** de `alembic.ini` formatean cada migración nueva al generarla, para que pase el lint del CI. Solo funcionan donde `ruff` está instalado (el entorno de desarrollo), no en la imagen.

## Tests con PostgreSQL

Los tests usan una PostgreSQL real y no SQLite: la numeración correlativa de las facturas se apoya en bloqueos de fila (`SELECT ... FOR UPDATE`), que SQLite no soporta, y los servicios usan esquemas de PostgreSQL.

### En local

Hace falta una PostgreSQL desechable. La de Compose no sirve, porque está en una red interna y no publica puertos:

```bash
docker run -d --name pg-test -e POSTGRES_USER=verifactu -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=verifactu -p 55432:5432 postgres:17-alpine

export DATABASE_URL=postgresql://verifactu:test@127.0.0.1:55432/verifactu   # PowerShell: $env:DATABASE_URL = "..."
cd services/document-service
python -m pytest

docker rm -f pg-test                                                        # al terminar
```

Sin `DATABASE_URL`, los tests que necesitan la base de datos se **omiten** con un aviso, y el resto se ejecuta.

### En el CI

El trabajo `test` levanta un contenedor de PostgreSQL como servicio y define `DATABASE_URL`. Si la variable falta en el CI (donde `CI=true`), los tests **fallan** en lugar de omitirse, para que una configuración rota no pase como un CI en verde.

### Fixtures

| Fixture | Alcance | Qué hace |
|---|---|---|
| `engine` | Sesión de tests | Aplica `alembic upgrade head` una vez y devuelve el motor. Así las migraciones se prueban de verdad |
| `session` | Cada test | Abre una transacción y la deshace al terminar, de modo que los tests no se influyen entre sí |
| `client` | Cada test | Cliente de FastAPI cuya sesión es la anterior |

Los tests de las migraciones comprueban que el esquema y la tabla de versiones se crean, y que ejecutar `upgrade` dos veces es seguro, que es lo que hace cada réplica al arrancar.

### Organización de `tests/`

| Carpeta | Qué prueba | ¿PostgreSQL? |
|---|---|---|
| `tests/` (raíz) | Configuración, migraciones y `/health` | Según el test |
| `tests/unit/` | Reglas de negocio puras: formato del número y cálculo de importes | No |
| `tests/repositories/` | Consultas: el contador de numeración | Sí |
| `tests/api/` | Los endpoints de principio a fin, con `client` | Sí |

Los nombres de fichero deben ser únicos en todo `tests/`, porque las carpetas no llevan `__init__.py`.

## Decisiones de diseño

| Decisión | Elección | Motivo |
|---|---|---|
| ORM | SQLAlchemy 2, síncrono | Más simple de probar, y la carga del proyecto no exige asincronía |
| Controlador | psycopg 3 con `psycopg[binary]` | Tiene *wheels* para la instalación con `--only-binary` |
| Migraciones | Alembic | Un esquema versionado permite desplegar nuevas versiones sobre una base de datos con datos, algo que `create_all()` no hace |
| Dónde se ejecutan | Al arrancar el contenedor | Un único comando y sin contenedores extra. El bloqueo evita la carrera entre réplicas |
| Esquema | Uno por servicio, con su tabla `alembic_version` | Cada servicio es dueño de su historial |
| Creación del esquema | En `env.py` | El servicio no depende de un script externo |
| Aislamiento de tests | Transacción con *rollback* | Más rápido que recrear las tablas en cada test |
| Salud | `GET /health` ejecuta `SELECT 1` | Devuelve `503` si la base de datos no responde, y el `HEALTHCHECK` marca el contenedor como no sano |

## Limitaciones conocidas

- Solo `document-service` usa la base de datos por ahora. `traceability-service` y `submission-service` aplicarán el mismo patrón con sus historias.
- La primera migración (`0001`) está vacía: marca el punto de partida del historial. Las tablas llegan con las historias de usuario: `0002` crea las de los documentos (CU-1).
- Un número solo se devuelve con un *rollback*. Si se anula un documento ya guardado, su número no se reutiliza, que es lo esperado en una numeración fiscal. Lo trata CU-6.
- Las migraciones se aplican en cada arranque y no hay una marcha atrás automática. Una migración que falla a la mitad deja el contenedor reiniciándose hasta que se corrige.
- `GET /health` falla cuando la base de datos no responde. Separar la comprobación de que el proceso está vivo de la de que está listo para atender se aborda en el hito de observabilidad.
