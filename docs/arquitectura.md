# Arquitectura interna de los servicios

El sistema se divide en tres microservicios por **función de negocio** (`document-service`, `traceability-service` y `submission-service`). Dentro de cada servicio, el código se organiza en **capas**. Este documento describe esa organización interna. La estructura de carpetas de cada servicio y su acceso a datos están en [`database.md`](database.md).

## Arquitectura en capas

Cada capa tiene una única responsabilidad y solo se comunica con la inferior:

```
petición HTTP
     │
     ▼
┌─────────────┐
│     api     │   recibe y valida la petición, devuelve la respuesta
└──────┬──────┘
       ▼
┌─────────────┐
│  services   │   reglas de negocio
└──────┬──────┘
       ▼
┌─────────────┐
│ repositories│   consultas a la base de datos
└──────┬──────┘
       ▼
  PostgreSQL
```

`models` no es una capa del flujo: contiene las tablas de SQLAlchemy y lo usan los repositorios.

### Equivalencia con el patrón clásico

Es el mismo patrón que se conoce como *controller / service / repository* en frameworks como Spring Boot o NestJS:

| Patrón clásico | Carpeta | Qué contiene |
|---|---|---|
| Controller | `app/api/` | Rutas de FastAPI (`APIRouter`), esquemas de entrada y salida |
| Service | `app/services/` | Reglas de negocio: numeración, cálculo de impuestos, validaciones |
| Repository | `app/repositories/` | Consultas con SQLAlchemy |
| Entity / Model | `app/models/` | Tablas |

La carpeta se llama `api` y no `controllers` porque en FastAPI esa capa son los routers y las dependencias HTTP.

### Qué sabe y qué no sabe cada capa

| Capa | Responsabilidad | Qué no debe hacer |
|---|---|---|
| `api` | Recibir la petición, validarla y devolver la respuesta con su código HTTP | Escribir SQL ni aplicar reglas de negocio |
| `services` | Aplicar las reglas de negocio y coordinar los repositorios | Conocer HTTP (códigos de estado, cabeceras) ni escribir SQL |
| `repositories` | Leer y escribir en la base de datos | Decidir reglas de negocio ni conocer HTTP |

Con esta separación:

- Las reglas de negocio se pueden probar sin servidor ni base de datos.
- El acceso a datos queda en un único sitio. Cambiar una consulta no afecta a las rutas.
- Cada fichero es corto y tiene un motivo claro para cambiar.

## Capas frente a componentes

Hay dos formas habituales de organizar el código de un servicio:

| | Por capas (la nuestra) | Por componentes |
|---|---|---|
| Se divide por | Función técnica | Función de negocio |
| Estructura | `api/`, `services/`, `repositories/` | `orders/`, `invoices/`, `delivery_notes/` |
| Dentro de cada carpeta | Todos los ficheros de esa capa | Su propio controller, service, repository y modelo |

Se pueden combinar: dividir primero por componente y aplicar las capas dentro de cada uno.

### Por qué capas

- **Los servicios ya son los componentes.** La división por negocio se hace a nivel de microservicios. Dentro de cada servicio el alcance es pequeño, y subdividir de nuevo sería excesivo.
- **Es el patrón más extendido.** Cualquiera que llegue al repositorio sabe dónde buscar cada cosa.
- **Se prueba fácilmente.** Los tests de `services` no necesitan HTTP ni SQL.

Si `document-service` crece y acumula mucha lógica de pedidos, albaranes y facturas, se puede reorganizar por componente. El cambio consistiría en mover ficheros, no en reescribir lógica.

## Reglas

1. **Cada capa solo habla con la siguiente.** `api` llama a `services`, y `services` llama a `repositories`. Un endpoint que lee la base de datos directamente se salta la arquitectura, y deja las capas en simples carpetas con nombre.
2. **Las dependencias van hacia abajo.** Un repositorio no importa un servicio, y un servicio no importa un router.
3. **La sesión de base de datos se inyecta.** `api` la recibe con `Depends(get_session)` y la pasa hacia abajo. Así los tests pueden sustituirla (ver `client` y `session` en [`database.md`](database.md)).
4. **Las excepciones de negocio se traducen en `api`.** Un servicio lanza una excepción propia de [`exceptions.py`](../services/document-service/app/exceptions.py) (por ejemplo, `ReferenceNotFound` si un albarán referencia a un pedido inexistente) y la capa `api` la convierte en el código HTTP, como un `404`. El servicio no conoce los códigos de estado.
5. **Los servicios no importan los esquemas de la API.** `api` traduce los modelos de Pydantic a datos propios del servicio (`OrderData`, `DeliveryNoteData`, `InvoiceData` y `LineData`, que son `dataclass`). Así el servicio sigue sin conocer el formato de la petición, y se prueba con objetos simples.
6. **El servicio confirma la transacción.** El repositorio solo hace `flush`, y el servicio llama a `commit` al terminar el caso de uso, de modo que el número, el pedido y sus líneas se guardan juntos o no se guarda nada.
7. **La respuesta se construye dentro del endpoint**, mientras la sesión sigue abierta. Si se devolviera el objeto de SQLAlchemy y se serializara después, leer las líneas podría necesitar la base de datos cuando la sesión ya se cerró.

### Errores de validación

Los datos que no cumplen el esquema de Pydantic (sin líneas, cantidad negativa, campos que faltan) los rechaza FastAPI antes de llegar al servicio, con un `422`. [`api/errors.py`](../services/document-service/app/api/errors.py) convierte la respuesta al cuerpo común del contrato de la API, `{"error": {"code": "VALIDATION_ERROR", "message": "..."}}`, con un mensaje que indica el campo: `lines.0.quantity: Input should be greater than 0`. Cuando el fallo es del cuerpo entero (JSON mal formado o ausente), el campo es `body`. Una petición rechazada no consume número de la serie.

Los esquemas de entrada heredan de `RequestModel` ([`schemas/common.py`](../services/document-service/app/api/schemas/common.py)), que **prohíbe los campos desconocidos**. Si un cliente envía un campo que calcula el servidor, como `total`, recibe un `422` en lugar de creer que su valor se usó.

### Errores de negocio

Una petición con el formato correcto que rompe una regla (un pedido que no existe, una entrega mayor que lo pedido) la detecta el servicio, que lanza una subclase de `DomainError`. Cada subclase tiene su `code`, y [`api/errors.py`](../services/document-service/app/api/errors.py) las convierte con el mismo cuerpo común:

| Excepción | Código | Respuesta |
|---|---|---|
| `ReferenceNotFound` | `REFERENCE_NOT_FOUND` | `404` |
| `DocumentNotFound` | `DOCUMENT_NOT_FOUND` | `404` |
| `InvalidOrderLine` | `INVALID_ORDER_LINE` | `422` |
| `InvalidInvoiceLine` | `INVALID_INVOICE_LINE` | `422` |
| `NothingToCorrect` | `NOTHING_TO_CORRECT` | `422` |
| `InvalidDateRange` | `INVALID_DATE_RANGE` | `422` |
| `QuantityExceeded` | `QUANTITY_EXCEEDED` | `422` |
| `DeliveryNoteAlreadyInvoiced` | `DELIVERY_NOTE_ALREADY_INVOICED` | `422` |
| `ReferenceCancelled` | `REFERENCE_CANCELLED` | `422` |
| `DocumentNotCancellable` | `DOCUMENT_NOT_CANCELLABLE` | `409` |

Un solo manejador (`domain_error_handler`) sirve para todas: responde `404` para las que heredan de `NotFound` (`ReferenceNotFound`, cuando la petición se refiere a un documento que no existe, y `DocumentNotFound`, cuando se consulta uno) `409` para las que heredan de `Conflict` (la petición choca con el estado del documento, como anular uno que ya tiene factura) y `422` para el resto. Una excepción nueva solo necesita su `code` y heredar de `DomainError` (o de `NotFound` o `Conflict`, si debe responder `404` o `409`). Como el servicio lanza la excepción antes de guardar nada, la petición rechazada no consume número de la serie.

`traceability-service` y `submission-service` usan una variante más sencilla: cada subclase de `DomainError` lleva también su `status_code` (por ejemplo `EventsNotFound` es `404` y `SubmissionAlreadyExists` es `409`), y su manejador responde con el de la excepción, sin ninguna clase base intermedia como `NotFound`.

### Eventos

Cuando una factura se emite, el servicio lo anuncia al resto del sistema con el evento `invoice.issued`, publicado en un *stream* de Redis. Se organiza como el acceso a la base de datos:

- [`app/events.py`](../services/document-service/app/events.py) es la pieza que habla con Redis, igual que `db.py` con PostgreSQL. Define `EventPublisher` (lo que el servicio necesita: publicar un evento en un *stream*) y `RedisEventPublisher` (su implementación con `XADD`).
- El endpoint recibe el publicador con `Depends(get_publisher)` y se lo pasa al servicio, como la sesión de base de datos. El servicio no importa `redis`: depende de `EventPublisher`. Si Redis falla, `RedisEventPublisher` lanza `EventPublishError`, una excepción propia, y el servicio no ve las de Redis.
- Los tests sustituyen `get_publisher` por uno falso que apunta los eventos en una lista, así que ningún test necesita Redis salvo los pocos que lo prueban a propósito (ver [`database.md`](database.md)).

**Se publica después del `commit`**, no antes: si se publicara antes y la transacción fallara, otros servicios recibirían una factura que no existe. Y si Redis no responde, **la factura se emite igual**: el error se registra en el log (`Event invoice.issued of invoice F-... was not published`) y la respuesta es `201`. Un fallo de quien reacciona a las facturas no debe impedir emitirlas. Redis se conecta con un tiempo máximo de 2 segundos para que no deje la petición esperando.

### Consumo de eventos

`traceability-service` es quien lee el *stream* `invoice.issued`. Lo hace [`app/consumer.py`](../services/traceability-service/app/consumer.py), un hilo en segundo plano que arranca con la aplicación (el `lifespan` de FastAPI en `main.py`) y se detiene con ella. Para cada entrada llama a `event_service.record_event`, la misma función que usa el endpoint, así que el consumidor está al mismo nivel que `api`: traduce una entrada de Redis a la llamada al servicio.

Lee con un **grupo de consumidores**, que recuerda qué entradas se entregaron y cuáles se confirmaron (`XACK`):

- Cada entrada la procesa una sola réplica del grupo, y otro servicio con su propio grupo recibe también todas.
- Se confirma **después del `commit`**. Si el servicio cae entre las dos cosas, la entrada se entrega otra vez, y `source_message_id` hace que registrarla de nuevo no haga nada (el procesamiento es idempotente).
- Si falla algo transitorio (la base de datos no responde), la entrada no se confirma, queda pendiente y se reintenta tras una espera de 2 segundos.
- Cada réplica lee primero sus entradas pendientes, después reclama (`XAUTOCLAIM`) las que otro consumidor lleva 30 segundos sin confirmar (un contenedor que se sustituyó deja sus entradas pendientes con su nombre) y por último pide las nuevas.
- Una entrada que no se puede interpretar nunca (le faltan campos) se confirma y se registra como error, para que no bloquee las siguientes.
- El grupo se crea desde el principio del *stream* (`id="0"`), de modo que las facturas emitidas antes de que el servicio arrancara por primera vez también se registran.

Los tests del consumidor (`tests/test_consumer.py`) usan un Redis real, con un *stream* y un grupo propios en cada test.

### Envío y reintentos

`submission-service` lee el mismo *stream* con su propio grupo de consumidores, y su [`app/consumer.py`](../services/submission-service/app/consumer.py) funciona como el de trazabilidad, con una diferencia: solo **registra** el envío (`PENDING`). Enviarlo es trabajo de otro proceso en segundo plano, [`app/sender.py`](../services/submission-service/app/sender.py). Los dos arrancan con la aplicación (el `lifespan` de `main.py`) y se detienen con ella.

Se separan porque tienen ritmos distintos: leer el *stream* es esperar entradas, y enviar es llamar a un sistema externo que puede tardar o fallar. Así una AEAT lenta no retrasa el registro de las facturas, y el registro no depende de que la AEAT responda.

**La base de datos es la cola de los reintentos.** Cada envío guarda su estado y cuándo se puede intentar de nuevo (`next_attempt_at`). El proceso de envío busca cada segundo los que tocan, y no hay temporizadores en memoria. Por eso un reinicio no pierde ningún reintento, y cualquier réplica puede hacerlo (`SKIP LOCKED` evita que dos envíen el mismo).

El intento se hace en tres pasos, cada uno en su transacción:

1. **Reclamar**: se marcan `SENT`, se cuenta el intento y se confirma.
2. **Enviar a la AEAT**, sin ninguna transacción abierta: la conexión a la base de datos no se queda ocupada mientras la AEAT tarda en responder.
3. **Guardar el resultado**: `ACCEPTED`, `REJECTED`, `RETRYING` (con la fecha del siguiente intento) o `FAILED`.

Si el servicio cae entre el paso 1 y el 3, el envío se queda en `SENT`. Pasado un minuto sin respuesta se da por perdido y se vuelve a reclamar, así que un envío no se queda atascado. El coste es que, en ese caso, la factura puede llegar dos veces a la AEAT; una AEAT real tendría que tratar el envío de forma idempotente.

La AEAT es una interfaz (`AeatClient`) y `SimulatedAeat` es su implementación actual. Dependiendo de la interfaz, el resto del servicio no cambiaría con un cliente de la AEAT real, y los tests usan una AEAT guionizada que responde lo que se le diga. Los tiempos se pasan como parámetro (`now`), así que los tests de las esperas crecientes no tienen que esperar.

### Errores en la documentación de la API

FastAPI documenta por defecto el `422` con su propio formato (`{"detail": [...]}`), que no es el que devuelve este servicio. Cada endpoint declara sus errores en `responses` con `error_response("descripción")`, para cualquier código ([`schemas/common.py`](../services/document-service/app/api/schemas/common.py)): `responses={422: error_response("...")}`. Así `/docs` y `/openapi.json` describen cada error con el cuerpo común, con un ejemplo. Un test (`tests/api/test_openapi.py`) comprueba que se documenta el nuestro y no el de FastAPI. Los endpoints nuevos deben declararlos también.

## Limitaciones conocidas

- Los tres servicios tienen ya las capas con la estructura creada: `document-service` (CU-1 a CU-8), `traceability-service` (CU-9 a CU-12) y `submission-service` (CU-13 a CU-16).
- Los mensajes de los errores están en inglés y no se traducen.
- **La cadena documental (CU-11) es la única consulta que depende de otro servicio.** `traceability-service` no guarda los documentos, solo sus eventos, así que la reconstruye pidiendo a `document-service` la factura, su albarán y su pedido por HTTP, siguiendo `parent_id`. Si `document-service` cae, esa consulta responde `503` (con 3 segundos de espera como máximo), mientras que el registro, la verificación y el histórico de eventos siguen funcionando. Se descartó guardar copias de los documentos en este servicio por la duplicación y porque podrían quedar desactualizadas. La consulta sale como máximo en tres peticiones, una por documento.
- **La cadena de hashes detecta la manipulación, pero no la impide ni la detecta en el último evento.** Cualquiera con acceso a la base de datos puede hacer un `UPDATE` o un `DELETE`; la verificación (CU-10) lo descubre después, salvo si se borran los últimos eventos o se reescribe el último con su hash recalculado, porque ningún evento posterior responde por ellos. La solución habitual es guardar el último hash de cada cadena fuera de esta base de datos (un servicio externo de sellado, o un registro que solo admita añadir). No está hecho en este hito. Tampoco hay nada que impida modificar los eventos desde la base de datos, como un *trigger* o un usuario sin permisos de `UPDATE` y `DELETE`.
- **La paginación de los listados (documentos y envíos) usa `OFFSET`.** Es sencilla y deja saltar a cualquier página, pero la base de datos tiene que recorrer y descartar las filas anteriores, así que las páginas muy lejanas son más lentas. Además, si se crean documentos o envíos mientras un cliente recorre las páginas, los más nuevos desplazan a los demás. Una paginación por cursor (pedir "los anteriores a este número") evitaría ambas cosas, a costa de no poder saltar a una página concreta. Con el volumen de esta práctica no compensa.
- **El evento `invoice.issued` se puede perder.** Se guarda la factura y después se publica el evento: son dos operaciones en sistemas distintos y no pueden ser atómicas. Si el proceso cae o Redis falla entre las dos, la factura existe y los demás servicios no se enteran. La solución habitual es un *outbox transaccional*: guardar el evento en una tabla dentro de la misma transacción que la factura y que otro proceso lo publique. No está hecho en este hito. Mientras tanto, el fallo se registra en el log y se puede detectar.
- Hay un solo *stream* sin recorte (`XTRIM`): las entradas se quedan aunque ya estén confirmadas. La política de retención queda pendiente, y habrá que decidirla sabiendo que lo leen dos grupos (trazabilidad y envío), para no recortar entradas que un grupo todavía no ha confirmado.
- Una entrada ilegible se descarta, no se guarda en una cola de entradas fallidas (*dead letter*). Queda registrada en el log.
- Los dos consumidores (`traceability-service` y `submission-service`) tienen el mismo código de lectura del *stream*, repetido en cada servicio. Es una decisión consciente: cada servicio es independiente y no comparten librerías. Si hubiera más consumidores, compensaría extraerlo.
- El envío a la AEAT es simulado. Un envío que se pierde a mitad (el servicio cae mientras envía) se repite pasado un minuto, así que la AEAT real recibiría la factura dos veces y tendría que tratarlo de forma idempotente.
- Con varias réplicas, el orden entre eventos de un mismo documento es el del bloqueo de su cadena, que normalmente coincide con el del *stream*, pero no está garantizado si dos réplicas leen entradas consecutivas del mismo documento a la vez.
- La regla de que cada capa solo habla con la siguiente la garantiza la revisión de código, no una herramienta. Se podría automatizar con una herramienta como `import-linter`.
