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
| `InvalidOrderLine` | `INVALID_ORDER_LINE` | `422` |
| `QuantityExceeded` | `QUANTITY_EXCEEDED` | `422` |
| `DeliveryNoteAlreadyInvoiced` | `DELIVERY_NOTE_ALREADY_INVOICED` | `422` |

Un solo manejador (`domain_error_handler`) sirve para todas: responde `404` para `ReferenceNotFound` y `422` para el resto. Una excepción nueva solo necesita su `code` y heredar de `DomainError`. Como el servicio lanza la excepción antes de guardar nada, la petición rechazada no consume número de la serie.

### Eventos

Cuando una factura se emite, el servicio lo anuncia al resto del sistema con el evento `invoice.issued`, publicado en un *stream* de Redis. Se organiza como el acceso a la base de datos:

- [`app/events.py`](../services/document-service/app/events.py) es la pieza que habla con Redis, igual que `db.py` con PostgreSQL. Define `EventPublisher` (lo que el servicio necesita: publicar un evento en un *stream*) y `RedisEventPublisher` (su implementación con `XADD`).
- El endpoint recibe el publicador con `Depends(get_publisher)` y se lo pasa al servicio, como la sesión de base de datos. El servicio no importa `redis`: depende de `EventPublisher`. Si Redis falla, `RedisEventPublisher` lanza `EventPublishError`, una excepción propia, y el servicio no ve las de Redis.
- Los tests sustituyen `get_publisher` por uno falso que apunta los eventos en una lista, así que ningún test necesita Redis salvo los pocos que lo prueban a propósito (ver [`database.md`](database.md)).

**Se publica después del `commit`**, no antes: si se publicara antes y la transacción fallara, otros servicios recibirían una factura que no existe. Y si Redis no responde, **la factura se emite igual**: el error se registra en el log (`Event invoice.issued of invoice F-... was not published`) y la respuesta es `201`. Un fallo de quien reacciona a las facturas no debe impedir emitirlas. Redis se conecta con un tiempo máximo de 2 segundos para que no deje la petición esperando.

### Errores en la documentación de la API

FastAPI documenta por defecto el `422` con su propio formato (`{"detail": [...]}`), que no es el que devuelve este servicio. Cada endpoint declara sus errores en `responses` con `error_response("descripción")`, para cualquier código ([`schemas/common.py`](../services/document-service/app/api/schemas/common.py)): `responses={422: error_response("...")}`. Así `/docs` y `/openapi.json` describen cada error con el cuerpo común, con un ejemplo. Un test (`tests/api/test_openapi.py`) comprueba que se documenta el nuestro y no el de FastAPI. Los endpoints nuevos deben declararlos también.

## Limitaciones conocidas

- Solo `document-service` tiene las capas con la estructura creada, y de momento solo para los pedidos, los albaranes y las facturas (CU-1 a CU-3). `traceability-service` y `submission-service` la aplicarán cuando tengan lógica.
- Los mensajes de los errores están en inglés y no se traducen.
- **El evento `invoice.issued` se puede perder.** Se guarda la factura y después se publica el evento: son dos operaciones en sistemas distintos y no pueden ser atómicas. Si el proceso cae o Redis falla entre las dos, la factura existe y los demás servicios no se enteran. La solución habitual es un *outbox transaccional*: guardar el evento en una tabla dentro de la misma transacción que la factura y que otro proceso lo publique. No está hecho en este hito. Mientras tanto, el fallo se registra en el log y se puede detectar.
- Hay un solo *stream* sin recorte (`XTRIM`): crece mientras nadie lo consuma. Los consumidores y la política de retención llegan con `traceability-service` y `submission-service`.
- La regla de que cada capa solo habla con la siguiente la garantiza la revisión de código, no una herramienta. Se podría automatizar con una herramienta como `import-linter`.
