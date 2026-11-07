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
│   ├── exceptions.py        # errores de negocio que lanzan los servicios
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

Pedidos, albaranes y facturas comparten una sola tabla, porque el contrato de la API los trata como un único recurso (`/documents`). Cada documento apunta al anterior de la cadena mediante `parent_id`. Hoy se crean pedidos (CU-1), albaranes (CU-2) y facturas (CU-3), y se consultan por su identificador (CU-4) o en un listado con filtros (CU-5).

```mermaid
erDiagram
    documents ||--o{ document_lines : "líneas (se borran con él)"
    document_lines |o--o{ document_lines : "source_line_id: línea de origen"
    documents |o--o{ documents : "parent_id: documento anterior"

    documents {
        uuid id PK
        varchar type "ORDER, DELIVERY_NOTE, INVOICE"
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
        uuid source_line_id FK "línea de origen"
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

La cadena de documentos se forma con `parent_id`: el albarán (CU-2) apunta a su pedido y la factura (CU-3) apunta a su albarán. Lo mismo ocurre con las líneas: cada línea de un albarán apunta con `source_line_id` a la línea del pedido que entrega, y la de una factura a la línea del albarán que factura. Con eso se suma cuánto se ha entregado de cada línea del pedido. `document_counters` queda suelta porque no tiene clave foránea: `documents.number` se construye con su valor, pero la base de datos no lo comprueba. El diagrama muestra las columnas clave, y las tablas de abajo las detallan todas.

### Tablas

**`documents`**: un documento de la cadena.

| Columna | Tipo | Notas |
|---|---|---|
| `id` | `UUID` | Clave primaria, la asigna el servidor |
| `type` | `VARCHAR(20)` | `ORDER`, `DELIVERY_NOTE` o `INVOICE`. Indexada |
| `series` | `VARCHAR(10)` | `P` para los pedidos, `A` para los albaranes y `F` para las facturas. Indexada |
| `number` | `VARCHAR(40)` | **Único**, como `P-2026-000001`, `A-2026-000001` o `F-2026-000001` |
| `status` | `VARCHAR(20)` | `ISSUED` por ahora. Indexada |
| `issue_date` | `DATE` | La pone el servidor con la fecha de hoy. Indexada, junto con `number` |
| `customer_name` | `VARCHAR(200)` | Nombre del cliente |
| `customer_tax_id` | `VARCHAR(20)` | NIF/CIF del cliente. Indexada |
| `total_net`, `total_vat`, `total` | `NUMERIC(12,2)` | Los calcula el servidor |
| `parent_id` | `UUID` | Clave foránea a `documents.id`: el documento anterior de la cadena (el pedido, en un albarán, y el albarán, en una factura). Vacío en un pedido. En las facturas es **único**, porque un albarán se factura una vez |
| `created_at` | `TIMESTAMPTZ` | Valor por defecto `now()` en la base de datos |

**`document_lines`**: las líneas de un documento. Se borran con él (`ON DELETE CASCADE`).

| Columna | Tipo | Notas |
|---|---|---|
| `id` | `UUID` | Clave primaria |
| `document_id` | `UUID` | Clave foránea a `documents.id`. Indexada |
| `source_line_id` | `UUID` | Clave foránea a `document_lines.id`: la línea del documento anterior que esta línea entrega o factura. Vacía en un pedido. Indexada |
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
| Series | `P` para los pedidos, `A` para los albaranes y `F` para las facturas, definidas en `services/numbering.py` junto al formato del número | Un solo sitio para saber cómo se numera cada tipo |
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

### Cantidades entregadas

Un pedido puede entregarse en varios albaranes, y la suma de lo entregado de cada línea no puede superar lo pedido. No se guarda ningún total: se calcula al registrar el albarán, sumando las líneas de los albaranes anteriores que apuntan a esa línea del pedido con `source_line_id`.

1. El servicio **bloquea la fila del pedido** (`SELECT ... FOR UPDATE`) antes de comprobar las cantidades.
2. Si dos albaranes del mismo pedido llegan a la vez, el segundo espera a que el primero termine, y entonces ve lo que este entregó.
3. Sin el bloqueo, los dos pasarían la comprobación y, entre los dos, entregarían más de lo pedido.

Un test (`tests/services/test_delivery_note_concurrency.py`) fuerza ese solapamiento y falla si se quita el bloqueo. Los albaranes de pedidos distintos no se bloquean entre sí.

### Una factura por albarán

Un albarán se factura una sola vez, y esa regla se protege con dos defensas:

1. **El servicio** bloquea la fila del albarán (`SELECT ... FOR UPDATE`) y comprueba que no tenga ya una factura. Si la tiene, responde `422 DELIVERY_NOTE_ALREADY_INVOICED`. Es la que da un error claro al cliente.
2. **La base de datos** tiene un índice único parcial sobre `parent_id` que solo afecta a las facturas (`WHERE type = 'INVOICE'`), creado por la migración `0004`. Es la última defensa: aunque dos peticiones se saltaran la comprobación, la segunda factura se rechazaría. Es parcial porque varios albaranes sí pueden tener el mismo pedido como padre.

La numeración de las facturas es correlativa y sin huecos por la misma razón que la de los pedidos: el contador de la serie `F` se actualiza dentro de la transacción de la factura, y si esta falla, el *rollback* devuelve el número. Una petición rechazada no consume número.

### El listado de documentos

`GET /api/v1/documents` (CU-5) filtra por `type`, `series`, `status`, `issue_date` y cliente, y las migraciones `0005` y `0006` indexan las columnas que no lo tenían (`type` y `customer_tax_id` ya lo tenían). `status` solo tiene hoy el valor `ISSUED`, así que su índice no acelera nada todavía: se crea ya para que lo aproveche cuando haya más estados (la anulación de CU-6 añadirá uno).

- **El orden y las fechas** los sirve un solo índice compuesto sobre `(issue_date, number)`. Un índice *btree* se recorre igual hacia delante que hacia atrás, así que sirve para `ORDER BY issue_date DESC, number DESC`: la base de datos lee las filas ya en orden, sin ordenarlas, y el filtro por `from` y `to` cae sobre su primera columna. Sustituye al índice solo de `issue_date` que creó la `0005`, que quedaba cubierto por este. Se midió con 300.000 documentos: la última página tardaba 270 ms con el índice de la fecha sola (ordenaba por número los empates de cada día) y 52 ms con el compuesto, y la primera pasó de 0,32 ms a 0,09 ms. La última página sigue siendo la más lenta porque el `OFFSET` obliga a recorrer y descartar las filas anteriores (ver las limitaciones de [`docs/arquitectura.md`](arquitectura.md)).

- **El cliente** se filtra con un solo parámetro: el texto es el NIF/CIF exacto (que usa el índice) o parte del nombre, sin distinguir mayúsculas (`ILIKE '%texto%'`). Esa búsqueda por nombre no puede usar un índice normal, así que recorre la tabla. Con pocos documentos no importa; con muchos, el remedio sería un índice `pg_trgm`. El texto del cliente se escapa, para que un `%` o un `_` escritos por el cliente busquen ese carácter y no actúen como comodines de `LIKE`.
- **El orden** es fecha de emisión descendente y número descendente. El número es único, así que desempata siempre igual: sin él, dos documentos del mismo día podrían cambiar de página entre dos peticiones.
- **La página** se calcula con `LIMIT` y `OFFSET`, y `total` con un `COUNT(*)` de los mismos filtros. Son dos consultas por petición, sin depender del tamaño de la página, y no se cargan las líneas del listado. Un test cuenta las consultas y falla si crecen.

El esquema (`documents`) está escrito en las migraciones, porque Alembic lo fija al autogenerarlas.

## Modelo de datos de `traceability-service`

`traceability-service` aplica el mismo patrón en su esquema `traceability`, con una sola tabla, `trace_events`, que guarda los eventos de todos los documentos:

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | `uuid` | Clave primaria, asignada por el servidor |
| `document_id` | `uuid` | Documento al que se refiere el evento. No es clave foránea: el documento vive en el esquema de otro servicio, y los servicios solo comparten identificadores |
| `sequence` | `integer` | Posición en la cadena del documento, desde 1 |
| `event_type` | `varchar(100)` | Tipo de evento, como `INVOICE_ISSUED` |
| `occurred_at` | `timestamptz` | Cuándo ocurrió, según quien lo envía |
| `payload` | `jsonb` | Datos del evento. Forman parte del hash |
| `previous_hash` | `varchar(64)` | `hash` del evento anterior (64 ceros en el primero) |
| `hash` | `varchar(64)` | SHA-256 hexadecimal del contenido canónico y `previous_hash` |
| `source_message_id` | `varchar(64)` | Identificador de la entrada de Redis de la que viene, o vacío si viene del endpoint |
| `created_at` | `timestamptz` | Cuándo se registró |

Restricciones:

- `UNIQUE (document_id, sequence)`: la cadena de un documento no tiene huecos ni posiciones repetidas. Su índice sirve también para las consultas por documento, como el histórico de un documento (CU-12), que lee sus eventos por este índice y los pide ordenados por `sequence` de forma explícita.
- `UNIQUE (source_message_id)`: una entrada del *stream* entregada dos veces no se registra dos veces.
- `sequence >= 1` y longitud 64 para los dos hashes.

**Cómo se encadena.** Un evento nuevo necesita el último del documento y, para el primero, no hay fila que bloquear con `SELECT ... FOR UPDATE`. Por eso se toma un *advisory lock* de PostgreSQL (`pg_advisory_xact_lock(hashtext('trace:<documento>'))`) hasta el final de la transacción: "leer el último" y "guardar el siguiente" son un solo paso para los eventos del mismo documento, y los de documentos distintos no se esperan. La restricción única es la última defensa. El test `tests/services/test_event_concurrency.py` lanza seis eventos a la vez y comprueba que la cadena no se bifurca; sin el bloqueo falla.

Las migraciones son `0001` (vacía) y `0002` (crea `trace_events`).

## Modelo de datos de `submission-service`

`submission-service` aplica el mismo patrón en su esquema `submissions`, con una tabla, `submissions`, con **un envío por factura**:

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | `uuid` | Clave primaria, asignada por el servidor |
| `invoice_id` | `uuid` | Factura que se envía. Único, y no es clave foránea: la factura vive en el esquema de otro servicio |
| `invoice_number` | `varchar(40)` | Número de la factura, si se conoce (viene en el evento, pero no en el disparo manual) |
| `status` | `varchar(20)` | `PENDING`, `SENT`, `ACCEPTED`, `REJECTED`, `RETRYING` o `FAILED`. Es texto, no un `ENUM` de PostgreSQL, por la misma razón que en `document-service` |
| `attempts` | `integer` | Intentos hechos |
| `next_attempt_at` | `timestamptz` | Cuándo se puede intentar de nuevo. Vacío cuando el envío es definitivo |
| `last_error` | `varchar(100)` | Por qué falló o se rechazó el último intento, como `AEAT_UNAVAILABLE` |
| `aeat_reference` | `varchar(100)` | Referencia que dio la AEAT al aceptarlo |
| `created_at`, `updated_at` | `timestamptz` | Cuándo se creó y cuándo cambió por última vez |

Restricciones e índices:

- `UNIQUE (invoice_id)`: una factura se envía una vez, aunque su evento llegue dos veces o alguien lo pida también a mano. Es lo que hace idempotente el consumo del evento: el servicio inserta con `ON CONFLICT DO NOTHING`, y si la factura ya tenía envío, no hace nada.
- `attempts >= 0`.
- Índice `(status, next_attempt_at)`, para que el proceso de envío encuentre rápido los que tocan.

**Cómo se reparten los envíos entre réplicas.** El proceso de envío elige los envíos que toca intentar con `SELECT ... FOR UPDATE SKIP LOCKED`: si otra réplica ya ha bloqueado una fila, se la salta en vez de esperar. Después los marca `SENT` y confirma **antes** de llamar a la AEAT, así que otra réplica no los ve como pendientes. El test `tests/services/test_claim_concurrency.py` comprueba que una fila bloqueada por un proceso se la salta el otro; sin `SKIP LOCKED` falla.

Las migraciones son `0001` (vacía) y `0002` (crea `submissions`).

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
| `tests/` (raíz) | Configuración, migraciones, `/health` y el publicador de eventos | Según el test |
| `tests/unit/` | Reglas de negocio puras: formato del número y cálculo de importes | No |
| `tests/repositories/` | Consultas y restricciones: el contador de numeración y el índice de una factura por albarán | Sí |
| `tests/services/` | Reglas que dependen de transacciones reales, como la concurrencia de los albaranes y de las facturas, o el evento en Redis. Los de concurrencia hacen `commit` de verdad y borran sus datos al terminar | Sí (y Redis en uno) |
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

- Los tres servicios usan la base de datos con el mismo patrón.
- La primera migración (`0001`) está vacía: marca el punto de partida del historial. Las tablas llegan con las historias de usuario: `0002` crea las de los documentos (CU-1) y `0003` añade `source_line_id` a las líneas (CU-2) y `0004` el índice de una factura por albarán (CU-3) y `0005` y `0006` los índices del listado (CU-5).
- Un número solo se devuelve con un *rollback*. Si se anula un documento ya guardado, su número no se reutiliza, que es lo esperado en una numeración fiscal. Lo trata CU-6.
- Las migraciones se aplican en cada arranque y no hay una marcha atrás automática. Una migración que falla a la mitad deja el contenedor reiniciándose hasta que se corrige.
- `GET /health` falla cuando la base de datos no responde. Separar la comprobación de que el proceso está vivo de la de que está listo para atender se aborda en el hito de observabilidad.
