# Especificación de la API REST

Detalle de los 16 endpoints de `verifactu-trace`: qué hace cada uno, el cuerpo de la petición, las respuestas y sus errores. El [`README.md`](../README.md#especificación-de-la-api-rest) tiene el resumen, las convenciones comunes (prefijo, formato, paginación, códigos de estado y errores) y los estados y reglas. Cada servicio publica además su documentación OpenAPI en `/docs`.

Los endpoints están agrupados por servicio, y cada uno lleva el caso de uso (CU) que implementa.

## document-service

### `POST /api/v1/orders` (CU-1)

Registra un pedido. El servidor asigna el `id` (UUID), el número de la serie `P` (`P-<año>-<correlativo de seis cifras>`), la fecha y los importes, y **no se aceptan en la petición**: un campo desconocido se rechaza con `422` en lugar de ignorarse. `vat_rate` es opcional y vale `21` por defecto.

```json
{
  "customer": { "name": "Acme S.L.", "tax_id": "B12345678" },
  "lines": [
    { "description": "Widget", "quantity": 2, "unit_price": 10.5, "vat_rate": 21 }
  ]
}
```

Respuesta `201`:

```json
{
  "id": "62c13d37-67f6-42d1-918e-641e43072aa4",
  "type": "ORDER",
  "number": "P-2026-000001",
  "status": "ISSUED",
  "issue_date": "2026-10-28",
  "customer": { "name": "Acme S.L.", "tax_id": "B12345678" },
  "lines": [
    { "position": 1, "description": "Widget", "quantity": 2.0, "unit_price": 10.5, "vat_rate": 21.0 }
  ],
  "total_net": 21.0,
  "total_vat": 4.41,
  "total": 25.41
}
```

Se responde `422` si el pedido no tiene líneas, si una cantidad no es mayor que cero, si un precio es negativo o tiene más de dos decimales, si el IVA no está entre 0 y 100, si falta un campo obligatorio, si se envía un campo desconocido (como `total`) o si el cuerpo no es un JSON válido. El mensaje indica el campo, o `body` cuando el fallo es del cuerpo entero:

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "lines.0.quantity: Input should be greater than 0" } }
```

### `POST /api/v1/delivery-notes` (CU-2)

Registra un albarán que referencia a un pedido. Cada línea indica cuánto se entrega de una línea del pedido (`order_line` es su posición, empezando en 1) y no hace falta entregarlas todas. El cliente, las descripciones, los precios y el IVA son los del pedido, y el servidor asigna el `id`, el número de la serie `A` (`A-<año>-<correlativo de seis cifras>`), la fecha y los importes: ninguno se acepta en la petición.

Un pedido puede entregarse en varios albaranes, pero **las cantidades de todos ellos sumadas no pueden superar las pedidas**. Un pedido de 10 unidades admite albaranes de 4 y de 6, pero no de 4 y de 7.

```json
{
  "order_id": "62c13d37-67f6-42d1-918e-641e43072aa4",
  "lines": [
    { "order_line": 1, "quantity": 2 }
  ]
}
```

Respuesta `201`:

```json
{
  "id": "0b6c3d8e-5f0a-4c53-8d5e-9a1d6f2d7c11",
  "type": "DELIVERY_NOTE",
  "number": "A-2026-000001",
  "status": "ISSUED",
  "issue_date": "2026-11-03",
  "order_id": "62c13d37-67f6-42d1-918e-641e43072aa4",
  "customer": { "name": "Acme S.L.", "tax_id": "B12345678" },
  "lines": [
    { "position": 1, "order_line": 1, "description": "Widget", "quantity": 2.0, "unit_price": 10.5, "vat_rate": 21.0 }
  ],
  "total_net": 21.0,
  "total_vat": 4.41,
  "total": 25.41
}
```

Los errores usan el cuerpo común `{"error": {"code": "...", "message": "..."}}`:

| Respuesta | Código | Cuándo |
|---|---|---|
| `404` | `REFERENCE_NOT_FOUND` | El pedido no existe, o el identificador es de un documento que no es un pedido |
| `422` | `INVALID_ORDER_LINE` | `order_line` no es una línea del pedido |
| `422` | `QUANTITY_EXCEEDED` | Lo entregado, sumando los albaranes anteriores, supera lo pedido. Los albaranes anulados no cuentan |
| `422` | `REFERENCE_CANCELLED` | El pedido está anulado (CU-6) |
| `422` | `VALIDATION_ERROR` | Cuerpo mal formado: cantidad no mayor que cero, sin líneas, una línea del pedido repetida, falta un campo o hay uno desconocido |

```json
{ "error": { "code": "QUANTITY_EXCEEDED", "message": "line 1: 7 requested but only 6 pending (ordered 10, already delivered 4)" } }
```

Dos albaranes simultáneos del mismo pedido no pueden superar entre los dos lo pedido: el servidor bloquea el pedido mientras comprueba las cantidades y guarda el albarán.

### `POST /api/v1/invoices` (CU-3)

Emite la factura de un albarán. Solo se envía el albarán: la factura **factura lo que el albarán entregó**, con el cliente y los precios del pedido. El servidor asigna el `id`, el número de la serie `F` (`F-<año>-<correlativo de seis cifras>`, sin huecos), la fecha y los importes: ninguno se acepta en la petición, y un campo desconocido se rechaza con `422`.

Un albarán solo se puede facturar una vez.

```json
{ "delivery_note_id": "0b6c3d8e-5f0a-4c53-8d5e-9a1d6f2d7c11" }
```

Respuesta `201`:

```json
{
  "id": "5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52",
  "type": "INVOICE",
  "number": "F-2026-000001",
  "status": "ISSUED",
  "issue_date": "2026-11-03",
  "delivery_note_id": "0b6c3d8e-5f0a-4c53-8d5e-9a1d6f2d7c11",
  "order_id": "62c13d37-67f6-42d1-918e-641e43072aa4",
  "customer": { "name": "Acme S.L.", "tax_id": "B12345678" },
  "lines": [
    { "position": 1, "delivery_note_line": 1, "description": "Widget", "quantity": 2.0, "unit_price": 10.5, "vat_rate": 21.0 }
  ],
  "total_net": 21.0,
  "total_vat": 4.41,
  "total": 25.41
}
```

`total_net` es la base imponible, `total_vat` la cuota de IVA y `total` la suma de ambas. La cadena queda enlazada: la factura apunta a su albarán (`delivery_note_id`) y cada línea a la línea del albarán que factura (`delivery_note_line`).

| Respuesta | Código | Cuándo |
|---|---|---|
| `404` | `REFERENCE_NOT_FOUND` | El albarán no existe, o el identificador es de un documento que no es un albarán |
| `422` | `DELIVERY_NOTE_ALREADY_INVOICED` | El albarán ya tiene factura |
| `422` | `REFERENCE_CANCELLED` | El albarán está anulado (CU-6) |
| `422` | `VALIDATION_ERROR` | Cuerpo mal formado: falta `delivery_note_id`, no es un UUID o hay un campo desconocido |

Dos peticiones simultáneas para el mismo albarán no pueden emitir dos facturas: el servidor bloquea el albarán mientras comprueba y guarda, y la base de datos lo impide además con un índice único.

**Evento `invoice.issued`.** Cuando la factura queda guardada, el servicio publica el evento en el *stream* de Redis `invoice.issued`, del que leerán `traceability-service` y `submission-service`. Cada entrada lleva estos campos, todos texto:

| Campo | Contenido |
|---|---|
| `invoice_id` | Identificador de la factura |
| `number` | Número de la factura, como `F-2026-000001` |
| `delivery_note_id` | Identificador del albarán facturado |
| `order_id` | Identificador del pedido de origen |
| `total` | Total de la factura, como `25.41`. Negativo en una rectificativa (CU-8) |
| `issued_at` | Fecha y hora de emisión, en ISO 8601 con zona horaria |

Una factura rectificativa (CU-8) publica el mismo evento: `invoice_id` y `number` son los suyos, y `delivery_note_id` y `order_id` los de la factura que rectifica. El evento se publica **después de guardar** la factura. Si Redis no responde, la factura se emite igual (`201`) y el fallo queda en el log, porque un servicio que reacciona a las facturas no debe impedir emitirlas. Eso significa que el evento se puede perder; ver las limitaciones en [`docs/arquitectura.md`](arquitectura.md).

### `POST /api/v1/invoices/{id}/corrections` (CU-8)

Emite una factura **rectificativa**: corrige una factura ya emitida sin modificarla. `{id}` es el de la factura que se rectifica.

```json
{
  "reason": "Se devolvieron dos unidades dañadas",
  "lines": [ { "invoice_line": 1, "quantity": 2 } ]
}
```

`reason` es el motivo (obligatorio, hasta 300 caracteres). `lines` dice cuánto se devuelve de cada línea de la factura (`invoice_line` es su posición, desde 1) y es **opcional**: si se omite, se devuelve todo lo que aún no se había rectificado. Una línea se puede dejar fuera, pero no repetir. Las cantidades se envían en positivo, hasta con 3 decimales.

Responde `201` con la rectificativa, con su propio número de la **serie `R`** (`R-2026-000001`) y la referencia a la factura original en `corrects_invoice_id`:

```json
{
  "id": "c411a3b4-3768-432b-9724-c8300f73bf60",
  "type": "CORRECTIVE_INVOICE",
  "number": "R-2026-000001",
  "status": "ISSUED",
  "issue_date": "2026-11-08",
  "corrects_invoice_id": "5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52",
  "reason": "Se devolvieron dos unidades dañadas",
  "customer": { "name": "Acme S.L.", "tax_id": "B12345678" },
  "lines": [
    { "position": 1, "invoice_line": 1, "description": "Widget", "quantity": -2.0, "unit_price": 10.5, "vat_rate": 21.0 }
  ],
  "total_net": -21.0,
  "total_vat": -4.41,
  "total": -25.41
}
```

- **Cantidades y totales negativos.** La rectificativa devuelve unidades, así que sus líneas tienen cantidad negativa, al precio y con el IVA de la factura original, y sus importes salen negativos con el mismo redondeo que cualquier factura. Con `lines` omitido, anula exactamente los importes de la factura original, con el signo cambiado.
- **La factura original no se toca.** La rectificativa es un documento aparte (`type` `CORRECTIVE_INVOICE`) cuyo `parent_id` es la factura. Se lee con `GET /api/v1/documents/{id}` como cualquier otro, y aparece en el listado con `type=CORRECTIVE_INVOICE` o `series=R`.
- **Varias rectificativas.** Una factura puede tener varias, pero entre todas no pueden devolver más de lo facturado en cada línea: se lleva la cuenta de lo ya rectificado. Dos peticiones a la vez no pueden pasarse del total, porque el servidor bloquea la factura mientras comprueba y guarda.
- **Es una factura más.** Al guardarla se publica el evento `invoice.issued`, igual que para cualquier factura, así que se encadena en `traceability-service` y se envía a la AEAT desde `submission-service`. Sus campos `delivery_note_id` y `order_id` son los de la factura original, y `total` es negativo. No se puede anular.
- **Qué corrige y qué no.** Solo corrige **cantidades** (devoluciones o abonos). No cambia precios ni IVA: para eso habría que devolver la línea y facturarla de nuevo, algo que esta API no permite porque un albarán solo se factura una vez. Es una limitación conocida.

| Respuesta | Código | Cuándo |
|---|---|---|
| `404` | `REFERENCE_NOT_FOUND` | La factura no existe, o el identificador es de un documento que no es una factura (un pedido, un albarán o una rectificativa) |
| `422` | `INVALID_INVOICE_LINE` | `invoice_line` no es una línea de la factura |
| `422` | `QUANTITY_EXCEEDED` | Lo devuelto, sumando las rectificativas anteriores, supera lo facturado |
| `422` | `NOTHING_TO_CORRECT` | `lines` se omitió y la factura ya está rectificada por completo |
| `422` | `VALIDATION_ERROR` | Falta `reason` o está vacío o es demasiado largo, `lines` está vacío o repite una línea, una cantidad no es mayor que cero o tiene más de 3 decimales, o hay un campo desconocido |

### `GET /api/v1/documents/{id}` (CU-4)

Consulta un pedido, un albarán o una factura por su identificador. Los tres tipos se devuelven con **la misma forma**, y `type` indica de cuál se trata (`ORDER`, `DELIVERY_NOTE`, `INVOICE` o `CORRECTIVE_INVOICE`). La consulta no modifica nada.

Respuesta `200` (un albarán):

```json
{
  "id": "0b6c3d8e-5f0a-4c53-8d5e-9a1d6f2d7c11",
  "type": "DELIVERY_NOTE",
  "number": "A-2026-000001",
  "status": "ISSUED",
  "issue_date": "2026-11-02",
  "parent_id": "62c13d37-67f6-42d1-918e-641e43072aa4",
  "customer": { "name": "Acme S.L.", "tax_id": "B12345678" },
  "lines": [
    { "position": 1, "source_line": 1, "description": "Widget", "quantity": 2.0, "unit_price": 10.5, "vat_rate": 21.0 }
  ],
  "total_net": 21.0,
  "total_vat": 4.41,
  "total": 25.41
}
```

La cadena documental se recorre con dos campos. `parent_id` es el documento anterior de la cadena: el pedido de un albarán y el albarán de una factura (en un pedido vale `null`). `source_line` es la posición de la línea del documento anterior de la que viene cada línea: la del pedido que entrega una línea de albarán, la del albarán que factura una línea de factura (en un pedido vale `null`). Con ellos un cliente puede ir de una factura a su pedido consultando cada `parent_id`.

| Respuesta | Código | Cuándo |
|---|---|---|
| `404` | `DOCUMENT_NOT_FOUND` | No existe ningún documento con ese identificador |
| `422` | `VALIDATION_ERROR` | El identificador no es un UUID |

Las respuestas de creación (`POST /orders`, `/delivery-notes` y `/invoices`) conservan su forma, con campos propios de cada tipo (`order_id`, `delivery_note_id`...). Esta consulta usa la forma común para los tres.

### `GET /api/v1/documents` (CU-5)

Lista pedidos, albaranes y facturas. Todos los parámetros son opcionales y **los filtros se suman**: un documento tiene que cumplirlos todos.

| Parámetro | Filtra por |
|---|---|
| `type` | Tipo: `ORDER`, `DELIVERY_NOTE`, `INVOICE` o `CORRECTIVE_INVOICE` |
| `customer` | Cliente: el texto es su NIF/CIF exacto, o parte de su nombre (sin distinguir mayúsculas) |
| `series` | Serie: `P`, `A`, `F` o `R` |
| `status` | Estado: `ISSUED` o `CANCELLED` |
| `from`, `to` | Fecha de emisión, desde `from` hasta `to`, **ambas incluidas** |
| `page` | Número de página, desde 1 (por defecto `1`) |
| `size` | Documentos por página, de 1 a 100 (por defecto `20`) |

```
GET /api/v1/documents?type=INVOICE&customer=acme&from=2026-11-01&page=1&size=2
```

Respuesta `200`, con los documentos más recientes primero. Cada elemento lleva la cabecera y los importes del documento, sin las líneas (para ver una factura entera se usa `GET /api/v1/documents/{id}`):

```json
{
  "items": [
    {
      "id": "5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52",
      "type": "INVOICE",
      "number": "F-2026-000002",
      "status": "ISSUED",
      "issue_date": "2026-11-05",
      "parent_id": "0b6c3d8e-5f0a-4c53-8d5e-9a1d6f2d7c11",
      "customer": { "name": "Acme S.L.", "tax_id": "B12345678" },
      "total_net": 21.0,
      "total_vat": 4.41,
      "total": 25.41
    }
  ],
  "page": 1,
  "size": 2,
  "total": 134
}
```

`total` es el número de documentos que cumplen los filtros en **todas** las páginas, no solo en esta: con él un cliente sabe cuántas páginas hay (`ceil(total / size)`). Una página más allá de la última devuelve `items` vacío y conserva el `total`. Si ningún documento cumple los filtros, la respuesta es `200` con `items` vacío y `total` a `0`, no un `404`.

Los documentos se ordenan por fecha de emisión descendente y, dentro del mismo día, por número descendente. El orden es siempre el mismo, así que un documento no aparece en dos páginas ni se salta mientras el cliente las recorre.

| Respuesta | Código | Cuándo |
|---|---|---|
| `422` | `VALIDATION_ERROR` | Un parámetro no es válido: `type` o `status` desconocidos, una fecha mal formada, `page` menor que 1 o `size` fuera de 1 a 100 |
| `422` | `INVALID_DATE_RANGE` | `from` es posterior a `to` |

### `POST /api/v1/documents/{id}/cancel` (CU-6)

Anula un pedido o un albarán, para corregir un error. No lleva cuerpo. El documento **no se borra**: se conserva con `status` `CANCELLED`, con su número, y la respuesta es el documento entero, igual que `GET /api/v1/documents/{id}`.

Un documento anulado no se puede volver a usar: no se pueden hacer albaranes de un pedido anulado ni facturas de un albarán anulado (`422` `REFERENCE_CANCELLED`). Anular un albarán **libera las cantidades** que entregaba, que se pueden volver a entregar. Y el número de un documento anulado no se reutiliza, como corresponde a una numeración fiscal.

Qué se puede anular:

| Documento | Se puede anular si… |
|---|---|
| Pedido | No tiene albaranes, o todos están anulados. Si tuviera alguno vivo, quedaría sin pedido: se anulan antes |
| Albarán | No tiene factura |
| Factura | **Nunca**: una factura emitida no se anula, solo se rectifica (CU-8). Una rectificativa tampoco |

Un documento que ya está anulado tampoco se puede anular otra vez.

| Respuesta | Código | Cuándo |
|---|---|---|
| `200` | — | El documento queda `CANCELLED` |
| `404` | `DOCUMENT_NOT_FOUND` | No existe un documento con ese id |
| `409` | `DOCUMENT_NOT_CANCELLABLE` | Es una factura, ya está anulado, es un albarán con factura o es un pedido con albaranes sin anular. El mensaje dice el motivo |
| `422` | `VALIDATION_ERROR` | El id no es un UUID |

```json
{ "error": { "code": "DOCUMENT_NOT_CANCELLABLE", "message": "order P-2026-000007 has delivery notes that are not cancelled (A-2026-000006): cancel them first" } }
```

Una anulación y una petición que se apoya en el mismo documento (un albarán de ese pedido, una factura de ese albarán) a la vez no se pisan: la anulación bloquea el documento, y la otra petición espera y ve su resultado. O la anulación va primero y la otra se rechaza con `REFERENCE_CANCELLED`, o va después y se rechaza la anulación.

La anulación **no publica ningún evento**: `traceability-service` solo registra las facturas, y estas no se pueden anular.

### `GET /api/v1/documents/{id}/discrepancies` (CU-7)

Compara, línea a línea, los documentos de la cadena de `{id}` para detectar diferencias antes de que lleguen a la contabilidad. La consulta no modifica nada.

La cadena es la del documento por el que se pregunta, desde su pedido hasta él mismo: con el id de una **factura** se comparan el pedido, el albarán y la factura; con el de un albarán, el pedido y el albarán; y con el de un pedido no hay nada con lo que compararlo.

```json
{
  "document_id": "5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52",
  "compared": [
    { "type": "ORDER", "id": "3f1c0b7a-...", "number": "P-2026-000008" },
    { "type": "DELIVERY_NOTE", "id": "9a7b2d1e-...", "number": "A-2026-000008" },
    { "type": "INVOICE", "id": "5d2e8a6c-...", "number": "F-2026-000006" }
  ],
  "discrepancies": [
    {
      "field": "quantity",
      "description": "Widget",
      "source": { "document_type": "ORDER", "number": "P-2026-000008", "line": 1, "value": 10.0 },
      "target": { "document_type": "DELIVERY_NOTE", "number": "A-2026-000008", "line": 1, "value": 4.0 }
    }
  ]
}
```

Cada documento se compara con el **siguiente** de la cadena (pedido con albarán, albarán con factura). Cada línea se busca en el documento siguiente a través de `source_line`, que es como una línea dice de cuál viene, y han de coincidir tres campos: `quantity`, `unit_price` y `vat_rate`. Cada diferencia dice cuál es el campo, qué línea es y el valor en cada lado (`source` es el documento anterior, `target` el posterior). Una línea del documento anterior que el siguiente no tiene cuenta como cantidad `0`, con `line` a `null` en `target`. Las líneas del documento posterior que no vienen de ninguna del anterior no se comparan. Una factura rectificativa (CU-8) tampoco se compara con la factura que rectifica, porque difiere de ella a propósito. Una cadena coherente devuelve `discrepancies` vacío.

**Una entrega parcial es una diferencia.** Si el pedido era de 10 y el albarán entrega 4, aparece como diferencia de `quantity`. No tiene por qué ser un error (el resto se puede entregar en otro albarán), pero sí es una diferencia entre los documentos, y cada albarán se compara con el pedido por separado. Una cadena creada con esta API solo puede tener diferencias de ese tipo, porque el albarán copia el precio y el IVA del pedido y la factura copia lo que entregó el albarán. El resto de diferencias aparecen si algo modifica un documento después (un fallo o una escritura directa en la base de datos), que es lo que esta consulta detecta.

| Respuesta | Código | Cuándo |
|---|---|---|
| `404` | `DOCUMENT_NOT_FOUND` | No existe un documento con ese id |
| `422` | `VALIDATION_ERROR` | El id no es un UUID |

## traceability-service

### `POST /api/v1/traceability/events` (CU-9)

Registra un evento al final de la cadena de su documento. Es un endpoint **interno**: los eventos llegan normalmente desde el *stream* `invoice.issued` (ver más abajo), y este endpoint permite registrar otros a mano.

```json
{
  "document_id": "5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52",
  "event_type": "INVOICE_ISSUED",
  "occurred_at": "2026-10-14T09:30:00Z",
  "payload": { "number": "F-2026-000001", "total": "380.82" }
}
```

Solo `document_id` y `event_type` son obligatorios. `occurred_at` (con zona horaria) vale por defecto la hora del servidor y `payload` es `{}`. El servidor asigna el resto:

```json
{
  "id": "c04a8625-30b9-424d-8301-8d6185bcda4d",
  "document_id": "5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52",
  "sequence": 1,
  "event_type": "INVOICE_ISSUED",
  "occurred_at": "2026-10-14T09:30:00Z",
  "payload": { "number": "F-2026-000001", "total": "380.82" },
  "previous_hash": "0000000000000000000000000000000000000000000000000000000000000000",
  "hash": "0741fde33e4ee2990368a1ba86008a3ac66769e9e978b077905a9605369a4225"
}
```

| Código | `error.code` | Cuándo |
|---|---|---|
| `422` | `VALIDATION_ERROR` | Falta `document_id` o `event_type`, no es un UUID, `occurred_at` no tiene zona horaria, o hay un campo desconocido (por ejemplo `hash` o `sequence`, que calcula el servidor) |

**Cadena de hashes.** Cada documento tiene su propia cadena:

- `sequence` cuenta desde 1 para cada documento.
- `previous_hash` es el `hash` del evento anterior del mismo documento. El primero usa un hash inicial de 64 ceros.
- `hash` es el SHA-256 del contenido canónico del evento seguido de `previous_hash`. El contenido canónico es un JSON con las claves ordenadas y sin espacios (`document_id`, `event_type`, `occurred_at` en UTC, `payload` y `sequence`), de modo que se puede recalcular más tarde para verificar la cadena (CU-10).
- Dos eventos del mismo documento que llegan a la vez se encadenan uno detrás de otro, en el orden en que obtienen el bloqueo de la cadena. Nunca se bifurca.

**Consumo del evento `invoice.issued`.** Al arrancar, `traceability-service` lee el *stream* `invoice.issued` con un grupo de consumidores (`traceability-service`) y registra cada factura como un evento `INVOICE_ISSUED` en la cadena de la factura. El `payload` lleva `number`, `delivery_note_id`, `order_id`, `total` e `issued_at`, y `occurred_at` es `issued_at`.

- Confirma (`XACK`) cada entrada **después de guardar** el evento. Si el servicio cae o la base de datos no responde, la entrada queda pendiente y se entrega de nuevo, así que no se pierde por este lado.
- Si una entrada se entrega dos veces, el evento no se duplica: guarda el identificador de la entrada (`source_message_id`) y lo reconoce.
- Si el servicio estuvo parado, registra al volver las facturas emitidas mientras tanto, porque el grupo empieza en el principio del *stream*.
- Una entrada mal formada (sin campos o con valores ilegibles) se descarta con un error en el log para no bloquear las siguientes.

### `GET /api/v1/traceability/documents/{id}/verification` (CU-10)

Verifica que nadie ha manipulado los eventos de un documento. Recalcula la cadena de hashes **en orden, desde el primer evento**, y la compara con lo que hay guardado. La consulta no modifica nada.

Respuesta `200` con la cadena intacta:

```json
{
  "document_id": "5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52",
  "valid": true,
  "events_checked": 3,
  "first_invalid_sequence": null
}
```

Con un evento alterado, `valid` es `false` e indica dónde se rompe la cadena:

```json
{
  "document_id": "5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52",
  "valid": false,
  "events_checked": 3,
  "first_invalid_sequence": 2
}
```

Un evento falla si no cumple alguna de estas tres comprobaciones:

1. **Su `sequence` es la que sigue al evento anterior** (el primero, 1). Detecta un evento borrado de la mitad aunque se hayan recalculado los hashes de los siguientes.
2. **Su `previous_hash` es el `hash` guardado del evento anterior** (el primero, 64 ceros). Detecta un evento sustituido: el siguiente seguía encadenado al original.
3. **Su `hash` coincide con el SHA-256 recalculado** del contenido del evento y su `previous_hash`. Detecta que se cambiaron sus datos (`event_type`, `occurred_at` o `payload`) o el propio `hash`.

`first_invalid_sequence` es la `sequence` del **primer** evento que falla. Los siguientes no se señalan, porque dejan de ser fiables en cuanto se rompe un eslabón. Cada evento se compara con el hash *guardado* de su vecino, no con uno recalculado, así que un evento alterado se señala en su propia posición y no en la siguiente. Si se borra un evento de la mitad, se señala el que venía detrás. `events_checked` es el número de eventos de la cadena del documento.

| Respuesta | Código | Cuándo |
|---|---|---|
| `404` | `EVENTS_NOT_FOUND` | El documento no tiene ningún evento |
| `422` | `VALIDATION_ERROR` | El identificador no es un UUID |

**Qué no detecta.** La cadena detecta manipulaciones, no las impide: la base de datos acepta un `UPDATE`, y la verificación lo descubre después. Tampoco puede detectar que se **borren los últimos eventos**, ni que se **reescriba el último** recalculando su hash, porque ningún evento posterior responde por ellos. Para eso haría falta guardar el último hash fuera de esta base de datos (en un servicio externo, o publicado). Está en las limitaciones de [`docs/arquitectura.md`](arquitectura.md).

### `GET /api/v1/traceability/documents/{id}/chain` (CU-11)

Devuelve los documentos que respaldan una factura, en el orden en que se hicieron: el pedido, el albarán y la factura. `{id}` es el de la **factura**.

```json
{
  "invoice_id": "5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52",
  "chain": [
    { "type": "ORDER", "id": "3f1c0b7a-...", "number": "P-2026-000001", "issue_date": "2026-10-10" },
    { "type": "DELIVERY_NOTE", "id": "9a7b2d1e-...", "number": "A-2026-000001", "issue_date": "2026-10-12" },
    { "type": "INVOICE", "id": "5d2e8a6c-...", "number": "F-2026-000001", "issue_date": "2026-10-14" }
  ]
}
```

Este servicio no guarda los documentos, solo sus eventos. Por eso reconstruye la cadena **a partir de las referencias** que guarda `document-service`: pide la factura, sigue su `parent_id` hasta el albarán, y el de este hasta el pedido (ver `GET /api/v1/documents/{id}`). La dirección de `document-service` se pasa en la variable `DOCUMENT_SERVICE_URL`, que `compose.yaml` ya define. A diferencia de CU-9, CU-10 y CU-12, esta consulta **depende de que `document-service` esté en marcha**.

| Respuesta | Código | Cuándo |
|---|---|---|
| `404` | `INVOICE_NOT_FOUND` | No existe una factura con ese id. También si el id es el de un pedido o un albarán |
| `422` | `VALIDATION_ERROR` | El identificador no es un UUID |
| `502` | `INCONSISTENT_CHAIN` | `document-service` devuelve documentos que no forman la cadena factura → albarán → pedido. No debería ocurrir mientras se respeten las referencias |
| `503` | `DOCUMENT_SERVICE_UNAVAILABLE` | `document-service` no responde (3 segundos de espera como máximo) o devuelve un error |

### `GET /api/v1/traceability/documents/{id}/events` (CU-12)

Devuelve el histórico de eventos de un documento, para auditar qué le ha ocurrido y cuándo. Los eventos vienen **ordenados por `sequence`**, es decir, en el orden en que se registraron, que es el de su cadena de hashes. La consulta no modifica nada.

Respuesta `200`:

```json
{
  "document_id": "5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52",
  "events": [
    {
      "id": "c04a8625-30b9-424d-8301-8d6185bcda4d",
      "document_id": "5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52",
      "sequence": 1,
      "event_type": "INVOICE_ISSUED",
      "occurred_at": "2026-10-14T09:30:00Z",
      "payload": { "number": "F-2026-000001", "total": "380.82" },
      "previous_hash": "0000000000000000000000000000000000000000000000000000000000000000",
      "hash": "0741fde33e4ee2990368a1ba86008a3ac66769e9e978b077905a9605369a4225"
    }
  ]
}
```

Cada evento tiene la misma forma que la respuesta de `POST /api/v1/traceability/events`, con sus dos hashes, así que quien audita puede comprobar que cada `previous_hash` es el `hash` del evento anterior. El orden es el de `sequence` y no el de `occurred_at`: un evento puede decir que ocurrió antes que otro que se registró antes. La lista no está paginada, porque la cadena de un documento tiene pocos eventos.

| Respuesta | Código | Cuándo |
|---|---|---|
| `404` | `EVENTS_NOT_FOUND` | El documento no tiene ningún evento |
| `422` | `VALIDATION_ERROR` | El identificador no es un UUID |

Un documento que no existe y uno al que todavía no le ha ocurrido nada responden lo mismo (`404`). `traceability-service` no guarda los documentos, solo los eventos que se refieren a ellos, así que no puede distinguirlos. Un documento recién creado, por ejemplo un pedido o un albarán, no tiene eventos hasta que se registra uno: de momento solo las facturas generan el evento `INVOICE_ISSUED`.

## submission-service

Normalmente el envío se dispara solo al recibir el evento `invoice.issued`. `POST /api/v1/submissions` permite lanzarlo manualmente.

### `POST /api/v1/submissions` (CU-13)

Pide el envío de una factura a la AEAT simulada. Solo lleva el identificador de la factura:

```json
{ "invoice_id": "5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52" }
```

Responde `202` porque la factura **todavía no se ha enviado**: el envío queda registrado como `PENDING` y un proceso en segundo plano lo envía y lo reintenta.

```json
{
  "id": "c8f4a1d0-7e22-4b0c-9d51-6a3e8f2b1c04",
  "invoice_id": "5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52",
  "invoice_number": null,
  "status": "PENDING",
  "attempts": 0,
  "next_attempt_at": "2026-10-14T09:30:00.123456Z",
  "last_error": null,
  "aeat_reference": null
}
```

| Código | `error.code` | Cuándo |
|---|---|---|
| `409` | `SUBMISSION_ALREADY_EXISTS` | La factura ya tiene un envío (porque llegó su evento o porque ya se pidió a mano) |
| `422` | `VALIDATION_ERROR` | Falta `invoice_id`, no es un UUID o hay un campo desconocido |

El servicio **no comprueba que la factura exista**, porque las facturas pertenecen a `document-service`. Podría hacerlo con la consulta de documentos (CU-4), pero acoplaría los dos servicios: el envío dejaría de funcionar si el otro cae. Es la razón de que este endpoint no responda `404`.

**Envío automático.** Al arrancar, el servicio lee el *stream* `invoice.issued` con su propio grupo de consumidores (`submission-service`, distinto del de trazabilidad, así que los dos reciben cada factura) y registra un envío `PENDING` por cada una. Funciona igual que el consumidor de trazabilidad: confirma cada entrada después de guardar, la reintenta si el servicio cae y descarta las entradas mal formadas. Una factura solo tiene **un envío**, así que si su evento llega dos veces, o ya se pidió a mano, no se crea otro.

**Estados y reintentos.** Un segundo proceso en segundo plano busca cada segundo los envíos que toca intentar y los manda a la AEAT:

```
PENDING ──► SENT ──► ACCEPTED
              │ └──► REJECTED                (la AEAT lo rechaza: es definitivo)
              └────► RETRYING ──► SENT ...   (la AEAT no responde: se reintenta)
                        └──────► FAILED      (se agotaron los intentos: es definitivo)
```

- `SENT` significa que hay un intento en curso. Cada intento incrementa `attempts`.
- Si la AEAT no responde, el envío pasa a `RETRYING` y se reintenta con una **espera creciente**: el doble tras cada fallo (5, 10, 20, 40 segundos con los valores por defecto, con un máximo de una hora). Tras el último intento fallido pasa a `FAILED`. El último error queda en `last_error`.
- Si la AEAT rechaza la factura, no se reintenta solo: enviarla otra vez daría la misma respuesta. Una vez corregido el motivo, un `REJECTED` o un `FAILED` se puede reenviar a mano (CU-15).
- Los reintentos se guardan en la base de datos (`next_attempt_at`), no en memoria, así que sobreviven a un reinicio y cualquier réplica puede hacerlos. Un envío que lleva un minuto en `SENT` sin respuesta (el servicio cayó mientras lo enviaba) se da por perdido y se vuelve a enviar.

**AEAT simulada.** El servicio habla con la AEAT a través de una interfaz (`AeatClient`), y la implementación actual es una simulación dentro del propio servicio. Se elige con variables de entorno, que `compose.yaml` pasa al contenedor (se cambian en `.env`):

| Variable | Valor por defecto | Efecto |
|---|---|---|
| `AEAT_SIMULATION` | `accept` | `accept`: acepta todos los envíos. `reject`: los rechaza. `fail`: no responde nunca, así que acaban en `FAILED`. `flaky`: cada intento falla con la probabilidad de `AEAT_FAILURE_RATE` y si no, lo acepta |
| `AEAT_FAILURE_RATE` | `0.5` | Probabilidad de fallo con `flaky` (de 0 a 1) |
| `SUBMISSION_MAX_ATTEMPTS` | `5` | Intentos antes de pasar a `FAILED` |
| `SUBMISSION_RETRY_BASE_SECONDS` | `5` | Espera tras el primer fallo; se duplica después |

Para ver los reintentos, por ejemplo, con `AEAT_SIMULATION=flaky` en `.env`, `docker compose up -d submission-service` y emitir facturas. El estado se consulta con `GET /api/v1/submissions/{id}` o `GET /api/v1/submissions?invoice_id=` (CU-14).

### `GET /api/v1/submissions/{id}` (CU-14)

Consulta dónde está el envío de una factura. Devuelve el mismo cuerpo de envío que el `POST`:

```json
{
  "id": "c8f4a1d0-7e22-4b0c-9d51-6a3e8f2b1c04",
  "invoice_id": "5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52",
  "invoice_number": "F-2026-000001",
  "status": "RETRYING",
  "attempts": 2,
  "next_attempt_at": "2026-10-14T09:34:00Z",
  "last_error": "AEAT_UNAVAILABLE",
  "aeat_reference": null
}
```

Para saber si una factura llegó a la AEAT, mira `status`: `ACCEPTED` o `REJECTED` son definitivos, `PENDING`, `SENT` y `RETRYING` están en marcha (`next_attempt_at` dice cuándo se intenta de nuevo) y `FAILED` se rindió tras agotar los intentos. `last_error` guarda el motivo del último fallo o rechazo.

Para buscar el envío de una **factura** sin conocer el id del envío se usa el listado con `invoice_id` (ver CU-16). Como una factura tiene un solo envío, trae un elemento o ninguno: una factura sin envío, o que no existe, recibe `"items": []` y no un `404`.

| Respuesta | Código | Cuándo |
|---|---|---|
| `404` | `SUBMISSION_NOT_FOUND` | No existe un envío con ese id |
| `422` | `VALIDATION_ERROR` | El id no es un UUID |

### `GET /api/v1/submissions` (CU-16)

Lista los envíos, por ejemplo los pendientes o fallidos para actuar sobre las facturas que no han llegado a la AEAT. Todos los parámetros son opcionales y **los filtros se suman**.

| Parámetro | Filtra por |
|---|---|
| `invoice_id` | La factura: devuelve su envío, si lo tiene |
| `status` | Estado: `PENDING`, `SENT`, `ACCEPTED`, `REJECTED`, `RETRYING` o `FAILED` |
| `page` | Número de página, desde 1 (por defecto `1`) |
| `size` | Envíos por página, de 1 a 100 (por defecto `20`) |

```
GET /api/v1/submissions?status=FAILED&page=1&size=2
```

Respuesta `200`, con los envíos más recientes primero:

```json
{
  "items": [
    {
      "id": "5dc8bcd3-fd2f-465d-ab32-ef6d76e30f58",
      "invoice_id": "95062623-057a-46ae-a2ff-7871954df138",
      "invoice_number": "F-2026-000004",
      "status": "FAILED",
      "attempts": 5,
      "next_attempt_at": null,
      "last_error": "AEAT_UNAVAILABLE",
      "aeat_reference": null
    }
  ],
  "page": 1,
  "size": 2,
  "total": 1
}
```

`total` es el número de envíos que cumplen los filtros **en todas las páginas**, no solo en esta, para que el cliente sepa cuántas hay. Una página más allá del final devuelve `items` vacío con el mismo `total`, y un filtro que no encuentra nada, una lista vacía y no un `404`. Si dos envíos se crearon a la vez, se ordenan por su `id`, así que al pasar de página no se repite ni se salta ninguno.

| Respuesta | Código | Cuándo |
|---|---|---|
| `422` | `VALIDATION_ERROR` | `invoice_id` no es un UUID, `status` no es uno de los estados, `page` es menor que 1 o `size` está fuera de 1 a 100 |

La paginación usa `OFFSET`, con la limitación que se explica en [`docs/arquitectura.md`](arquitectura.md).

### `POST /api/v1/submissions/{id}/retry` (CU-15)

Envía otra vez un envío que no llegó a buen puerto, por ejemplo cuando se ha corregido la causa del fallo. No lleva cuerpo.

Responde `202` porque la factura **todavía no se ha enviado**: el envío vuelve a `PENDING` con los intentos a cero y el proceso en segundo plano lo envía, como a cualquier otro. Para ver cómo acaba se consulta con `GET /api/v1/submissions/{id}` (CU-14).

```json
{
  "id": "c8f4a1d0-7e22-4b0c-9d51-6a3e8f2b1c04",
  "invoice_id": "5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52",
  "invoice_number": "F-2026-000001",
  "status": "PENDING",
  "attempts": 0,
  "next_attempt_at": "2026-10-14T10:15:00.123456Z",
  "last_error": "AEAT_UNAVAILABLE",
  "aeat_reference": null
}
```

Solo se puede reintentar un envío **`FAILED`** (se agotaron los intentos) o **`REJECTED`** (la AEAT lo rechazó, y merece la pena reenviarlo una vez corregido el motivo). Uno `ACCEPTED` no se reenvía, para no enviar dos veces la misma factura, y uno `PENDING`, `SENT` o `RETRYING` ya está en marcha.

- Los intentos **empiezan de nuevo**, para que el reintento tenga un juego completo: con la cuenta anterior, un envío que agotó sus intentos volvería a `FAILED` tras un solo fallo.
- `last_error` se **conserva** hasta que el siguiente intento responda, para que no se pierda por qué se había parado. Si la AEAT lo acepta, se borra.
- Dos peticiones a la vez sobre el mismo envío no lo reenvían dos veces: se bloquea la fila, así que la segunda espera y ve que ya está `PENDING`, y recibe `409`.

| Respuesta | Código | Cuándo |
|---|---|---|
| `404` | `SUBMISSION_NOT_FOUND` | No existe un envío con ese id |
| `409` | `SUBMISSION_NOT_RETRYABLE` | El envío no está `FAILED` ni `REJECTED`. El mensaje dice en qué estado está |
| `422` | `VALIDATION_ERROR` | El id no es un UUID |
