# verifactu-trace

Aplicación nativa de la nube para la emisión y la trazabilidad de facturación electrónica B2B, desarrollada como proyecto de prácticas de la asignatura *Cloud Computing: Fundamentos e Infraestructuras* (Máster en Ingeniería Informática, Universidad de Granada).

[![CI](https://github.com/pablomatgom/verifactu-trace/actions/workflows/ci.yml/badge.svg)](https://github.com/pablomatgom/verifactu-trace/actions/workflows/ci.yml)
[![Docker](https://github.com/pablomatgom/verifactu-trace/actions/workflows/docker.yml/badge.svg)](https://github.com/pablomatgom/verifactu-trace/actions/workflows/docker.yml)

> **Estado:** Hito 1 completado. Hito 2 (empaquetado cloud native, entorno local e integración continua) completado en la versión `v0.2.0`: los 16 casos de uso están implementados, el sistema completo se levanta con Docker Compose y el CI valida el código y publica las imágenes. Las decisiones del hito están en [`docs/hito2.md`](docs/hito2.md). Hito 3 (infraestructura como código con Terraform en AWS y verificación del patrón *Reconciler*) completado en la versión `v0.3.0`: la infraestructura se define en [`infra/`](infra/) con tres módulos (red, almacenamiento y cómputo), se crea y se destruye con Terraform, y el experimento de deriva y reconciliación está documentado más abajo, en [Infraestructura en AWS](#infraestructura-en-aws). Las decisiones del hito están en [`docs/hito3.md`](docs/hito3.md).

## Índice

1. [Descripción del dominio y casos de uso](#descripción-del-dominio-y-casos-de-uso)
2. [Justificación NIST SP 800-145](#justificación-nist-sp-800-145)
3. [Actores NIST SP 500-292](#actores-nist-sp-500-292)
4. [Arquitectura](#arquitectura)
5. [Especificación de la API REST](#especificación-de-la-api-rest)
6. [Desarrollo local](#desarrollo-local)
7. [Integración continua](#integración-continua)
8. [Infraestructura en AWS](#infraestructura-en-aws)
9. [Documentación](#documentación)
10. [Gestión del proyecto](#gestión-del-proyecto)
11. [Licencia](#licencia)

## Descripción del dominio y casos de uso

### Problema

La normativa española de facturación (Reglamento de requisitos de los sistemas informáticos de facturación, conocido como *Verifactu*) exige que el software que emite facturas genere un **registro por cada factura**, que ese registro quede **encadenado criptográficamente** con el anterior para que no pueda alterarse sin dejar rastro, y que pueda **remitirse a la Agencia Tributaria (AEAT)**.

Para una pyme o un despacho profesional esto supone tres problemas operativos:

1. **Emitir correctamente**: aplicar las reglas fiscales (numeración por serie, IVA, retenciones, facturas rectificativas) sin errores.
2. **Garantizar la integridad**: poder demostrar que ninguna factura emitida se ha modificado ni eliminado.
3. **Controlar el envío**: saber en todo momento si cada factura ha llegado a la AEAT, ha sido rechazada o está pendiente de reintento.

`verifactu-trace` es una plataforma de microservicios que cubre este ciclo y mantiene la **trazabilidad completa de cada documento**, desde su emisión hasta su aceptación o rechazo.

### Por qué es un problema para la nube

- **Carga irregular**: la emisión se concentra en cierres de mes y de trimestre, con picos que justifican elasticidad.
- **Disponibilidad**: un fallo del servicio de envío no debe impedir emitir facturas por lo que los envíos se reintentan de forma asíncrona.
- **Servicios independientes**: emisión, trazabilidad y envío tienen necesidades de escalado y fallo diferentes, lo que justifica separarlos.
- **Servicio medido**: el volumen de facturas procesadas es una métrica natural de uso.

### Base conceptual

El proyecto toma como base conceptual mi Trabajo de Fin de Grado, *Arquitectura para la Trazabilidad Documental y Detección de Cuellos de Botella en Redes B2B mediante Grafos y Generación Sintética* (Universidad de Burgos, julio de 2026; [repositorio](https://github.com/pablomatgom/TFG-B2B)). De él se reutiliza únicamente la idea de modelar la trazabilidad como una **cadena de documentos relacionados** (pedido, albarán, factura).

No se copia código del TFG ya que este proyecto resuelve un problema totalmente distinto. Mientras el TFG **analiza** redes B2B con grafos y datos sintéticos, `verifactu-trace` **opera** el ciclo de vida de facturas reales conforme a la normativa, con una arquitectura de microservicios pensada para desplegarse en la nube.

### Casos de uso principales

La cadena documental que se modela es **pedido → albarán → factura**, por lo que cada documento referencia al anterior, de forma que desde una factura se puede reconstruir su origen.

| Código | Caso de uso | Servicio | Prioridad |
|---|---|---|---|
| CU-1 | Registrar un pedido | `document-service` | MVP |
| CU-2 | Registrar un albarán que referencia a un pedido, validando que existe y que las cantidades no lo superan | `document-service` | MVP |
| CU-3 | Emitir una factura (líneas, impuestos y numeración por serie) que referencia a un albarán | `document-service` | MVP |
| CU-4 | Consultar un documento por su identificador | `document-service` | MVP |
| CU-5 | Listar documentos filtrando por tipo, cliente, serie, fechas o estado | `document-service` | MVP |
| CU-6 | Anular un pedido o un albarán que aún no ha sido facturado | `document-service` | Extra |
| CU-7 | Detectar discrepancias de cantidades o importes entre pedido, albarán y factura | `document-service` | Extra |
| CU-8 | Emitir una factura rectificativa que referencia a la factura original | `document-service` | Extra |
| CU-9 | Registrar cada evento de un documento con su hash encadenado | `traceability-service` | MVP |
| CU-10 | Verificar la integridad de la cadena de registros | `traceability-service` | MVP |
| CU-11 | Consultar la cadena documental completa de una factura (pedido → albarán → factura) | `traceability-service` | MVP |
| CU-12 | Consultar el histórico de eventos de un documento (auditoría) | `traceability-service` | MVP |
| CU-13 | Enviar una factura a la AEAT (simulada) con estados y reintentos automáticos | `submission-service` | MVP |
| CU-14 | Consultar el estado de envío de una factura | `submission-service` | MVP |
| CU-15 | Reintentar manualmente un envío fallido o rechazado | `submission-service` | Extra |
| CU-16 | Listar los envíos pendientes o fallidos | `submission-service` | Extra |

### Alcance del producto mínimo viable (MVP)

Incluye el registro de pedidos, albaranes y facturas con validación de sus referencias, el registro encadenado y su verificación, la consulta de la cadena documental y el envío simulado a la AEAT con reintentos. El producto se expone únicamente mediante la **API REST**. Los casos de uso marcados como *Extra* en la tabla anterior forman parte del backlog y se abordan si el tiempo lo permite.

Quedan **fuera** del MVP:

- La firma electrónica real y la integración con los servicios reales de la AEAT.
- La **interfaz web**. No forma parte del MVP, pero se contempla como una posible ampliación futura con un cliente sencillo sobre la API existente para consultar la cadena documental y el estado de envío.

## Justificación NIST SP 800-145

La definición de computación en la nube del NIST (SP 800-145) la caracteriza por cinco características esenciales. A continuación se analiza cómo las aprovecha `verifactu-trace` y qué decisión del proyecto las materializa.

| Característica (NIST) | Definición | Cómo la aprovecha `verifactu-trace` |
|---|---|---|
| **Autoservicio bajo demanda** | El consumidor aprovisiona capacidades de cómputo por sí mismo, sin interacción humana con el proveedor. | Un emisor puede darse de alta y empezar a registrar documentos a través de la API sin intervención de un operador. La infraestructura se describe como código, de modo que el entorno se crea y se destruye de forma automática. |
| **Acceso amplio a la red** | Las capacidades se ofrecen a través de la red mediante mecanismos estándar, para clientes heterogéneos. | Toda la funcionalidad se expone por **API REST sobre HTTP con JSON**, por lo que puede consumirla cualquier software de gestión, un ERP, un script o, en el futuro, una interfaz web. Al ampliarse la base de usuarios potenciales aumenta el riesgo de seguridad, por lo que el acceso se limita a emisores autenticados. |
| **Asignación común de recursos** | Los recursos del proveedor se agrupan para atender a varios consumidores (*multi-tenancy*), asignándose y reasignándose dinámicamente según la demanda. | Los servicios atienden a varios emisores sobre la misma infraestructura, y cada documento queda asociado a su emisor para aislar los datos. La virtualización mediante contenedores permite compartir los recursos del nodo donde se despliegan. |
| **Rápida elasticidad** | Las capacidades se aprovisionan y liberan de forma rápida y automática según la demanda; para el consumidor parecen ilimitadas. | Los picos de emisión de fin de mes o de trimestre se absorben con **escalabilidad horizontal**, añadiendo réplicas de los servicios sin estado y retirándolas cuando baja la demanda. El envío a la AEAT se desacopla mediante una cola, de modo que `submission-service` escala de forma independiente. |
| **Servicio medido** | El uso de recursos se monitoriza, controla y reporta, con transparencia para proveedor y consumidor (pago por uso). | Cada servicio expone métricas de uso (documentos registrados, facturas emitidas, envíos y reintentos, latencias) que sirven tanto para la observabilidad como para calcular el consumo de cada emisor, siguiendo la lógica de *utility computing*. |

*Fuente:* material del Tema 1 de la asignatura.

### Modelo de servicio y de despliegue

- **Modelo de servicio:** el producto se ofrece al consumidor como **SaaS** (una API lista para usarse). Internamente, el despliegue se apoya en un **PaaS o IaaS** del proveedor.
- **Modelo de despliegue:** **nube pública**, aprovechando un proveedor externo.

## Actores NIST SP 500-292

La arquitectura de referencia del NIST (SP 500-292) identifica cinco actores: consumidor, proveedor, intermediario, auditor y operador. En este proyecto hay que distinguir **dos niveles**, porque `verifactu-trace` es a la vez un servicio que se ofrece a emisores de facturas (SaaS) y un cliente de la infraestructura de un proveedor cloud (IaaS o PaaS).

### Mapeo de actores

| Actor (NIST) | Definición | Quién lo es en `verifactu-trace` |
|---|---|---|
| **Consumidor** | Persona u organización que mantiene una relación comercial con los proveedores y utiliza sus recursos. | **Nivel de producto:** las pymes y profesionales que emiten facturas a través de la API, y los programas de gestión que las integran. <br> **Nivel de infraestructura:** el propio proyecto, que consume cómputo y almacenamiento del proveedor cloud. |
| **Proveedor** | Entidad responsable de poner un recurso a disposición de los interesados: gestiona la infraestructura, ejecuta el software y se encarga del acceso a la red. | **Nivel de producto:** el proyecto, que ejecuta los tres microservicios y se responsabiliza de su despliegue, orquestación, gestión, seguridad y privacidad. <br> **Nivel de infraestructura:** el proveedor IaaS o PaaS que se elegirá en el hito 5. |
| **Intermediario** (*broker*) | Entidad que gestiona el uso, el rendimiento y la prestación de recursos, y negocia las relaciones entre proveedores y consumidores. | `submission-service` actúa como intermediario de **intermediación** entre el emisor y la AEAT: añade valor al envío con validación, estados y reintentos. Los programas de gestión o asesorías que integran la API podrían ejercer además de **agregación**. |
| **Auditor** | Entidad que realiza una evaluación independiente de los recursos, las operaciones, el rendimiento y la seguridad. | La **AEAT** y los auditores externos que verifican la integridad de los registros encadenados (CU-10 y CU-12), y quien audite la seguridad y la privacidad del servicio. |
| **Operador** (*carrier*) | Intermediario que proporciona conectividad para los recursos en la nube. | Los operadores de red y la conectividad del proveedor cloud, que permiten al emisor llegar a la API y a la API llegar a la AEAT. |

### Acuerdos de nivel de servicio (SLA)

- **SLA con el consumidor:** el proyecto, como proveedor del producto, define la disponibilidad y los tiempos de respuesta que ofrece a los emisores.
- **SLA con el proveedor cloud:** el proveedor de infraestructura fija la disponibilidad del cómputo y de la red, que condiciona el nivel que el proyecto puede prometer. Normalmente su política de precios y sus SLA no son negociables.

### Impacto económico

| Actor | Impacto económico |
|---|---|
| Consumidor (emisor) | Evita adquirir y mantener un sistema propio de facturación conforme a la normativa, y paga en función del uso. Reduce el riesgo de sanciones por incumplimiento. |
| Proveedor (el proyecto) | Asume el coste de la infraestructura, que escala con la demanda gracias a la elasticidad, y debe compensarlo con el modelo de cobro por uso medido. |
| Proveedor cloud | Ingresa por el consumo de cómputo, almacenamiento y red del proyecto. Para el proyecto es un coste operativo variable en lugar de una inversión inicial. |
| Intermediario | Obtiene valor de la integración y de la reducción de la complejidad que asume el consumidor. |
| Auditor | Su coste se asocia al cumplimiento: disponer de registros verificables reduce el esfuerzo de inspección. |
| Operador | Ingresa por la conectividad, y su calidad condiciona el SLA que el proveedor puede ofrecer. |

*Fuente:* material del Tema 1 de la asignatura.  

## Arquitectura

### Diagrama de referencia

![Diagrama de arquitectura de referencia de verifactu-trace](docs/architecture.drawio.svg)

### Componentes

| Componente | Responsabilidad | Persistencia | Casos de uso |
|---|---|---|---|
| `api-gateway` | Punto de entrada único. Enruta las peticiones al servicio correspondiente. | — | Todos |
| `document-service` | Gestiona pedidos, albaranes y facturas, valida sus referencias y la numeración por serie. | PostgreSQL (esquema `documents`) | CU-1 a CU-8 |
| `traceability-service` | Registra los eventos de cada documento con su hash encadenado, verifica la integridad y reconstruye la cadena documental. | PostgreSQL (esquema `traceability`) | CU-9 a CU-12 |
| `submission-service` | Envía las facturas a la AEAT (simulada), controla el estado y reintenta los fallos. | PostgreSQL (esquema `submissions`) | CU-13 a CU-16 |
| PostgreSQL | Base de datos relacional. Una única instancia con un esquema por servicio (`documents`, `traceability` y `submissions`). | — | — |
| Redis | Cola de eventos entre servicios. Desacopla la emisión del registro y del envío. | Streams en memoria | — |
| AEAT simulada | Sustituye al servicio real de la AEAT con respuestas aceptadas, rechazadas o con error transitorio. | — | CU-13 |

### Flujo de emisión de una factura

1. El cliente envía la factura al `document-service` a través del gateway.
2. El `document-service` valida que el albarán referenciado existe, calcula la numeración y los impuestos, y guarda la factura.
3. Publica el evento `invoice.issued` en la cola de Redis y responde al cliente sin esperar al resto.
4. El `traceability-service` consume el evento, calcula el hash encadenado con el registro anterior y lo guarda.
5. El `submission-service` consume el evento, intenta el envío a la AEAT simulada y, si falla, lo reintenta con espera creciente.
6. El cliente consulta la cadena documental en el `traceability-service` o el estado del envío en el `submission-service`.

### Decisiones de diseño

- **Una base de datos lógica por servicio**: cada servicio es el único propietario de su esquema en PostgreSQL y ningún otro accede a él directamente. Se despliega una única instancia para reducir el coste, pero la separación por esquema permite repartirlas en instancias independientes si el escalado lo exige.
- **Comunicación asíncrona mediante eventos**: la emisión no depende de la disponibilidad de la trazabilidad ni del envío. Si la AEAT cae, las facturas se siguen emitiendo y los envíos se reintentan después.
- **Orden de los eventos**: se usan *streams* de Redis, que conservan el orden, algo necesario para encadenar los hashes de cada documento.
- **Servicios sin estado**: ningún servicio guarda estado en memoria, de modo que se pueden replicar tras un balanceador para dar elasticidad en los picos de cierre de mes.
- **Contenedores**: cada componente se empaqueta en su propia imagen Docker, lo que permite desplegarlo en el proveedor cloud que se elija en hitos posteriores.

## Especificación de la API REST

Esta sección resume el contrato de la API que expone `verifactu-trace` a través del gateway. El detalle de cada endpoint (cuerpos, respuestas y errores) está en [`docs/api.md`](docs/api.md). Cada servicio genera además su documentación OpenAPI con FastAPI (`/docs`), alineada con este contrato.

### Convenciones

- **Prefijo y versión**: todas las rutas cuelgan de `/api/v1`. El gateway enruta por el recurso: `/api/v1/documents`, `/api/v1/orders`, `/api/v1/delivery-notes` y `/api/v1/invoices` al `document-service`, `/api/v1/traceability` al `traceability-service` y `/api/v1/submissions` al `submission-service`.
- **Formato**: JSON en UTF-8, fechas en ISO 8601 e importes como números con dos decimales.
- **Identificadores**: UUID asignado por el servidor.
- **Paginación**: los listados admiten `page` y `size` y devuelven `items`, `page`, `size` y `total`.

  ```
  GET /api/v1/documents?type=INVOICE&page=2&size=20
  ```

  ```json
  {
    "items": [ { "id": "5d2e8a6c-...", "type": "INVOICE", "number": "A-2026-000021" } ],
    "page": 2,
    "size": 20,
    "total": 134
  }
  ```

- **Códigos de estado**: `200` consulta, `201` creación, `202` operación aceptada de forma asíncrona, `404` recurso inexistente, `409` conflicto con el estado actual, `422` datos o referencias inválidas.
- **Comprobación de salud**: cada servicio expone `GET /health`, que utilizará la orquestación en hitos posteriores.
- **Errores**: un cuerpo común con el código HTTP correspondiente.

  ```json
  { "error": { "code": "REFERENCE_NOT_FOUND", "message": "El pedido 3f1c... no existe" } }
  ```

### Endpoints

Los 16 endpoints, por servicio. Cada ruta enlaza con su detalle en [`docs/api.md`](docs/api.md).

| Servicio | Método | Ruta | Descripción | CU | Respuestas |
|---|---|---|---|---|---|
| `document-service` | `POST` | [`/api/v1/orders`](docs/api.md#post-apiv1orders-cu-1) | Registra un pedido | CU-1 | `201`, `422` |
| `document-service` | `POST` | [`/api/v1/delivery-notes`](docs/api.md#post-apiv1delivery-notes-cu-2) | Registra un albarán que referencia a un pedido | CU-2 | `201`, `404`, `422` |
| `document-service` | `POST` | [`/api/v1/invoices`](docs/api.md#post-apiv1invoices-cu-3) | Emite una factura que referencia a un albarán | CU-3 | `201`, `404`, `422` |
| `document-service` | `GET` | [`/api/v1/documents/{id}`](docs/api.md#get-apiv1documentsid-cu-4) | Consulta un documento por identificador | CU-4 | `200`, `404`, `422` |
| `document-service` | `GET` | [`/api/v1/documents`](docs/api.md#get-apiv1documents-cu-5) | Lista documentos. Filtros: `type`, `customer`, `series`, `from`, `to`, `status` | CU-5 | `200`, `422` |
| `document-service` | `POST` | [`/api/v1/documents/{id}/cancel`](docs/api.md#post-apiv1documentsidcancel-cu-6) | Anula un pedido o albarán no facturado | CU-6 (extra) | `200`, `404`, `409`, `422` |
| `document-service` | `GET` | [`/api/v1/documents/{id}/discrepancies`](docs/api.md#get-apiv1documentsiddiscrepancies-cu-7) | Detecta diferencias entre pedido, albarán y factura | CU-7 (extra) | `200`, `404`, `422` |
| `document-service` | `POST` | [`/api/v1/invoices/{id}/corrections`](docs/api.md#post-apiv1invoicesidcorrections-cu-8) | Emite una factura rectificativa | CU-8 (extra) | `201`, `404`, `422` |
| `traceability-service` | `POST` | [`/api/v1/traceability/events`](docs/api.md#post-apiv1traceabilityevents-cu-9) | Registra un evento con su hash encadenado. **Interno**: se alimenta de la cola y no se publica en el gateway | CU-9 | `201`, `422` |
| `traceability-service` | `GET` | [`/api/v1/traceability/documents/{id}/verification`](docs/api.md#get-apiv1traceabilitydocumentsidverification-cu-10) | Verifica la integridad de la cadena de registros | CU-10 | `200`, `404`, `422` |
| `traceability-service` | `GET` | [`/api/v1/traceability/documents/{id}/chain`](docs/api.md#get-apiv1traceabilitydocumentsidchain-cu-11) | Devuelve la cadena documental (pedido → albarán → factura) | CU-11 | `200`, `404`, `422`, `502`, `503` |
| `traceability-service` | `GET` | [`/api/v1/traceability/documents/{id}/events`](docs/api.md#get-apiv1traceabilitydocumentsidevents-cu-12) | Devuelve el histórico de eventos de un documento | CU-12 | `200`, `404`, `422` |
| `submission-service` | `POST` | [`/api/v1/submissions`](docs/api.md#post-apiv1submissions-cu-13) | Solicita el envío de una factura a la AEAT simulada | CU-13 | `202`, `409`, `422` |
| `submission-service` | `GET` | [`/api/v1/submissions/{id}`](docs/api.md#get-apiv1submissionsid-cu-14) | Consulta el estado de un envío | CU-14 | `200`, `404`, `422` |
| `submission-service` | `GET` | [`/api/v1/submissions`](docs/api.md#get-apiv1submissions-cu-16) | Lista envíos paginados. Filtros: `invoice_id`, `status` | CU-14, CU-16 (extra) | `200`, `422` |
| `submission-service` | `POST` | [`/api/v1/submissions/{id}/retry`](docs/api.md#post-apiv1submissionsidretry-cu-15) | Reintenta manualmente un envío fallido o rechazado | CU-15 (extra) | `202`, `404`, `409`, `422` |

Normalmente el envío de una factura se dispara solo al recibir el evento `invoice.issued`; `POST /api/v1/submissions` permite lanzarlo a mano.

### Ejemplo de petición

Registrar un pedido (`POST /api/v1/orders`, CU-1). El servidor asigna el `id`, el número de la serie `P`, la fecha y los importes, y no se aceptan en la petición.

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

### Ejemplos

**Consultar la cadena documental** (`GET /api/v1/traceability/documents/{id}/chain`):

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

**Verificar la integridad** (`GET /api/v1/traceability/documents/{id}/verification`):

```json
{ "document_id": "5d2e8a6c-...", "valid": true, "events_checked": 3, "first_invalid_sequence": null }
```

**Estado de un envío** (`GET /api/v1/submissions/{id}`):

```json
{
  "id": "c8f4a1d0-...",
  "invoice_id": "5d2e8a6c-...",
  "invoice_number": "F-2026-000001",
  "status": "RETRYING",
  "attempts": 2,
  "next_attempt_at": "2026-10-14T09:34:00Z",
  "last_error": "AEAT_UNAVAILABLE",
  "aeat_reference": null
}
```

### Estados y reglas

- **Documento**: `ISSUED` o `CANCELLED`. Se pueden anular los pedidos y albaranes que nada ha aprovechado (CU-6). Una factura emitida no se puede anular, solo rectificar.
- **Envío**: `PENDING` → `SENT` → `ACCEPTED` o `REJECTED`. Ante un fallo transitorio pasa a `RETRYING` con espera creciente y, agotados los intentos, a `FAILED`.
- **Hash encadenado**: cada evento guarda `sequence`, `previous_hash` y `hash`, calculado como SHA-256 del contenido canónico del evento concatenado con `previous_hash`. Cada documento tiene su propia cadena. La verificación recalcula la cadena y devuelve la primera posición inválida si la hay.
- **Autenticación**: queda fuera del MVP. Se planteará una clave de API en cabecera (`X-API-Key`) en hitos posteriores.

## Desarrollo local

### Estructura del repositorio

```
services/
├── document-service/        # puerto 8001
├── traceability-service/    # puerto 8002
└── submission-service/      # puerto 8003
infra/                       # infraestructura en la nube con Terraform
```

Cada servicio es una aplicación FastAPI independiente con su código en `app/`, sus pruebas en `tests/` y sus dependencias en `requirements.txt`. La infraestructura en AWS se define en `infra/` (ver [`docs/terraform.md`](docs/terraform.md)). `requirements-dev.txt` agrupa las de los tres servicios y las herramientas de desarrollo, y `ruff.toml` la configuración común del linter.

### Preparar el entorno

Requiere Python 3.12 o superior.

```bash
python -m venv .venv
source .venv/bin/activate        # en Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

### Ejecutar un servicio

```bash
cd services/document-service
uvicorn app.main:app --port 8001 --reload
```

Cada servicio responde en `GET /health` y publica su documentación OpenAPI en `/docs`.

### Ejecutar todo el sistema con Docker Compose

Levanta los tres servicios, PostgreSQL y Redis con un único comando. Requiere Docker con Compose v2.

```bash
cp .env.example .env        # en Windows (PowerShell): Copy-Item .env.example .env
docker compose up --build
```

`.env` contiene las credenciales de PostgreSQL, está excluido de Git y se crea a partir de `.env.example`, que solo lleva valores de ejemplo. Una vez arrancado, cada servicio responde en su puerto:

| Servicio | Comprobación de salud |
|---|---|
| `document-service` | http://localhost:8001/health |
| `traceability-service` | http://localhost:8002/health |
| `submission-service` | http://localhost:8003/health |

```bash
docker compose ps           # estado y salud de cada contenedor
docker compose down         # detiene el sistema y conserva los datos
docker compose down -v      # detiene el sistema y borra los datos
```

PostgreSQL y Redis solo son accesibles desde los demás contenedores, y los puertos de los servicios se publican únicamente en `127.0.0.1`. Las redes, los volúmenes y las decisiones de diseño están en [`docs/compose.md`](docs/compose.md).
### Pruebas y linter

Las pruebas se ejecutan por servicio, porque los tres usan el paquete `app`. Necesitan una PostgreSQL y una Redis, cuyas URLs leen de `DATABASE_URL` y `REDIS_URL`; sin ellas, las pruebas que dependen de esos servicios se omiten en local y fallan en el CI (ver [`docs/database.md`](docs/database.md)).

Los comandos se lanzan con un [`Makefile`](Makefile) en la raíz, que es el **gestor de tareas** del proyecto y el mismo que usa el CI:

```bash
make help                            # lista los objetivos
make test                            # pytest de los tres servicios, uno detrás de otro
make test SERVICE=document-service   # pytest de un solo servicio
make test PYTEST_ARGS="-x -k invoice" # argumentos extra para pytest
make lint                            # ruff check y ruff format --check
make format                          # ruff check --fix y ruff format
make up                              # construye y levanta el sistema con Docker Compose
make down                            # lo para, conservando los datos
make clean                           # lo para y borra los datos (los volúmenes)
```

`make test` avisa si `DATABASE_URL` o `REDIS_URL` no están definidas, porque entonces se omiten los tests que necesitan PostgreSQL o Redis (en el CI fallan). `make` viene con Linux y macOS. En Windows se instala con `choco install make` o `scoop install make`, y las órdenes se lanzan desde Git Bash. Los comandos que hay detrás de cada objetivo están en el propio `Makefile`.

## Integración continua

Cada pull request hacia `main` y cada push a `main` ejecutan dos workflows de [GitHub Actions](.github/workflows/). El resultado se muestra en el propio pull request antes de mergearlo.

| Workflow | Trabajo | Qué comprueba |
|---|---|---|
| [`ci.yml`](.github/workflows/ci.yml) | `Lint` | `make lint`: `ruff check` y `ruff format --check` sobre todo el repositorio |
| [`ci.yml`](.github/workflows/ci.yml) | `Test` | `make test`: `pytest` de cada servicio, en una matriz con un trabajo por servicio |
| [`ci.yml`](.github/workflows/ci.yml) | `Integration` | Levanta el sistema completo con Docker Compose y comprueba la salud de los servicios y los esquemas de PostgreSQL |
| [`docker.yml`](.github/workflows/docker.yml) | `Hadolint` | Análisis del `Dockerfile` de cada servicio |
| [`docker.yml`](.github/workflows/docker.yml) | `Build` | Construcción de la imagen de cada servicio y, fuera de los pull requests, su publicación |

Además, SonarCloud analiza el código y los Dockerfiles en cada pull request.

### Imágenes publicadas

Al mergear a `main`, o al subir un tag `v*`, `docker.yml` publica una imagen por servicio en GitHub Container Registry (`ghcr.io/pablomatgom/verifactu-trace/<servicio>`):

| Etiqueta | Cuándo se crea |
|---|---|
| `sha-<commit>` | En cada push a `main` |
| `latest` | En cada push a `main` |
| `0.2.0` | Al subir el tag `v0.2.0` (la versión del Hito 2) |
| `0.3.0` | Al subir el tag `v0.3.0` (la versión del Hito 3) |

En un pull request la imagen se construye para comprobar que el Dockerfile funciona, pero **no se publica**.

### Reproducir las comprobaciones en local

```bash
make lint                                                              # lint
make test SERVICE=document-service                                     # tests de un servicio (necesita DATABASE_URL y REDIS_URL)
docker run --rm -i hadolint/hadolint < services/document-service/Dockerfile   # análisis del Dockerfile
docker build -t document-service services/document-service             # construcción de la imagen
make up                                                                # integración (crea .env si falta)
```

El detalle de los workflows, los permisos y las decisiones de diseño está en [`docs/ci.md`](docs/ci.md).

## Infraestructura en AWS

La infraestructura se define con Terraform en [`infra/`](infra/), en tres módulos: la red (VPC, subredes y grupo de seguridad), el almacenamiento (un disco de EBS para los datos de PostgreSQL) y el cómputo (una instancia de EC2 que arranca los cinco contenedores con las imágenes de GHCR). Se crea en la región `eu-north-1` (Estocolmo). Los diagramas están en [`docs/despliegue.md`](docs/despliegue.md), la estructura del código en [`docs/terraform.md`](docs/terraform.md) y las decisiones en [`docs/hito3.md`](docs/hito3.md).

### Verificación del patrón Reconciler

El patrón *Reconciler* consiste en comparar de forma continua el estado deseado con el real y corregir la diferencia. Terraform lo hace cada vez que se ejecuta: el código es el estado deseado, el estado guardado en S3 es lo que recuerda haber creado, y en cada `plan` consulta a AWS cómo está ahora la infraestructura. El experimento lo comprueba en cuatro fases, con una modificación manual: borrar en la consola de AWS la regla del puerto 8002 del grupo de seguridad `verifactu-trace-compute`.

| Fase | Qué se hace | Qué se observa | Evidencia |
|---|---|---|---|
| **1. Estado deseado** | `terraform apply` | Se crean los 22 recursos | `01-apply.txt`, `02-consola-antes.pdf` |
| **2. Deriva** | Se borra a mano la regla del puerto 8002 en la consola | El servicio del puerto 8002 deja de responder desde fuera; los otros dos siguen igual | `03-consola-cambio.pdf`, `04-health-roto.txt` |
| **3. Observación** | `terraform plan` | Terraform avisa de que la regla ya no existe en AWS y propone crearla (`1 to add`) | `05-plan-deriva.txt` |
| **4. Reconciliación** | `terraform apply` | Se crea de nuevo la regla, el puerto 8002 vuelve a responder y un nuevo `plan` no propone cambios | `06-apply-reconcilia.txt`, `07-plan-limpio.txt` |

Los ficheros de evidencia, con la salida completa de cada comando y las capturas de la consola, están en [`docs/evidencias/hito3/`](docs/evidencias/hito3/README.md). A continuación, los extractos de cada fase.

#### 1. Estado deseado

Las capturas de la consola ([antes del cambio](docs/evidencias/hito3/02-consola-antes.pdf)) muestran las tres reglas de entrada (8001, 8002 y 8003). La salida de `terraform apply`:

```text
Plan: 22 to add, 0 to change, 0 to destroy.
...
Apply complete! Resources: 22 added, 0 changed, 0 destroyed.
```

#### 2. Inducción de la deriva

En la consola de AWS, *EC2 → Security Groups → `verifactu-trace-compute` → Edit inbound rules*, se borra la regla del puerto 8002 ([captura](docs/evidencias/hito3/03-consola-cambio.pdf): quedan dos reglas). El efecto se ve desde fuera:

```text
{"status":"ok","service":"document-service"} -> HTTP 200
 -> HTTP 000
{"status":"ok","service":"submission-service"} -> HTTP 200
```

#### 3. Observación: `terraform plan`

Terraform actualiza el estado con lo que hay en AWS, no encuentra la regla y propone crearla:

```text
  # module.network.aws_vpc_security_group_ingress_rule.app["8002-0.0.0.0/0"] will be created
  + resource "aws_vpc_security_group_ingress_rule" "app" {
      + cidr_ipv4              = "0.0.0.0/0"
      + description            = "Application port 8002"
      + from_port              = 8002
      + ip_protocol            = "tcp"
      + to_port                = 8002
      ...
    }

Plan: 1 to add, 0 to change, 0 to destroy.

Warning: AWS resource not found during refresh
```

#### 4. Reconciliación: `terraform apply`

```text
module.network.aws_vpc_security_group_ingress_rule.app["8002-0.0.0.0/0"]: Creating...
module.network.aws_vpc_security_group_ingress_rule.app["8002-0.0.0.0/0"]: Creation complete after 1s [id=sgr-0db46b4a35fd82079]

Apply complete! Resources: 1 added, 0 changed, 0 destroyed.
```

El puerto 8002 vuelve a responder (`{"status":"ok","service":"traceability-service"} -> HTTP 200`) y un `terraform plan` posterior confirma que ya no hay diferencias:

```text
No changes. Your infrastructure matches the configuration.
```

#### Apagado

Al terminar, `terraform destroy` elimina los 22 recursos ([`08-destroy.txt`](docs/evidencias/hito3/08-destroy.txt)):

```text
Plan: 0 to add, 0 to change, 22 to destroy.
...
Destroy complete! Resources: 22 destroyed.
```

Para comprobar que no queda nada que genere costes, se consulta a EC2 por la etiqueta `Project=verifactu-trace` (todos los recursos la llevan): la única instancia que figura está terminada y no queda ningún volumen, VPC ni grupo de seguridad. También se confirma que el rol de IAM y el parámetro de Parameter Store ya no existen ([`09-sin-recursos.txt`](docs/evidencias/hito3/09-sin-recursos.txt)) y se revisa la consola de AWS ([EC2](docs/evidencias/hito3/10-consola-ec2-vacia.pdf) y [VPC](docs/evidencias/hito3/10-consola-vpc-vacia.pdf)).

El desarrollo del experimento y las observaciones están en [`docs/hito3.md`](docs/hito3.md#experimento-del-patrón-reconciler), y cómo crear y destruir la infraestructura paso a paso, en [`docs/hito3.md`](docs/hito3.md#cómo-crear-y-destruir-la-infraestructura).

## Documentación

Documentación adicional del proyecto, en la carpeta [`docs/`](docs/). Hay dos tipos de documentos: los **temáticos**, que explican cómo funciona una parte del sistema y se actualizan en varios hitos, y los **de cada hito**, que recogen sus decisiones y sus evidencias.

### Por tema

- [Especificación de la API REST](docs/api.md): el detalle de los 16 endpoints, con sus cuerpos, respuestas y errores. El `README.md` tiene el resumen.
- [Arquitectura interna de los servicios](docs/arquitectura.md): arquitectura en capas (api, services, repositories), su equivalencia con controller/service/repository y reglas.
- [Capa de datos y migraciones](docs/database.md): estructura por capas de los servicios, migraciones con Alembic y tests con PostgreSQL.
- [Empaquetado con Docker](docs/docker.md): estructura de los Dockerfiles y decisiones de diseño de las imágenes.
- [Entorno local con Docker Compose](docs/compose.md): puesta en marcha del sistema completo, redes, volúmenes y decisiones de diseño.
- [Integración continua](docs/ci.md): lint, tests, validación de Terraform, análisis de Dockerfiles y publicación de imágenes en GHCR.
- [Infraestructura con Terraform](docs/terraform.md): qué es Terraform y cómo funciona, estructura de `infra/`, estado remoto en S3 con bloqueo, región de la UE y gestión de las credenciales.
- [AWS: conceptos y comandos](docs/aws.md): S3, IAM, regiones, redes, EBS, EC2 y Systems Manager, y los comandos de la AWS CLI usados para preparar la cuenta y acceder a la instancia.
- [Arquitectura de despliegue](docs/despliegue.md): diagramas de lo que se despliega en AWS, de los contenedores de la instancia y del primer arranque.

### Por hito

| Hito | Decisiones | Evidencias |
|---|---|---|
| **Hito 2**: empaquetado cloud native, entorno local e integración continua | [`docs/hito2.md`](docs/hito2.md): justificación del gestor de tareas, la biblioteca de aserciones, el marco de pruebas y el sistema de CI, y qué lógica de negocio se prueba | [`docs/evidencias/hito2/`](docs/evidencias/hito2/README.md): salida de los comandos y capturas de la CI, GHCR y SonarCloud |
| **Hito 3**: infraestructura como código en AWS | [`docs/hito3.md`](docs/hito3.md): elección del proveedor y de la persistencia, con sus alternativas, y las decisiones de las capas de red, almacenamiento y cómputo, el experimento del *Reconciler* y cómo crear y destruir la infraestructura | [`docs/evidencias/hito3/`](docs/evidencias/hito3/README.md): salida de los comandos y capturas del experimento del patrón *Reconciler* y del apagado de la infraestructura |

## Gestión del proyecto

- [Tablero del proyecto (GitHub Projects)](https://github.com/users/pablomatgom/projects/1)
- [Milestones](https://github.com/pablomatgom/verifactu-trace/milestones)
- [Issues](https://github.com/pablomatgom/verifactu-trace/issues)
- [Historias de usuario](https://github.com/pablomatgom/verifactu-trace/issues?q=label:user-story)
- [Guía de contribución: ramas y commits](CONTRIBUTING.md)

## Licencia

Distribuido bajo licencia MIT. Consulta el fichero [LICENSE](LICENSE).
