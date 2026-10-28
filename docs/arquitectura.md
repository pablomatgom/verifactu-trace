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
4. **Las excepciones de negocio se traducen en `api`.** Un servicio lanza una excepción propia (por ejemplo, un pedido sin líneas) y la capa `api` la convierte en el código HTTP, como un `422`. El servicio no conoce los códigos de estado.

## Limitaciones conocidas

- Solo `document-service` tiene las capas con la estructura creada. `traceability-service` y `submission-service` la aplicarán cuando tengan lógica.
- Las capas `services` y `repositories` están vacías hasta que lleguen las historias de usuario (CU-1 en adelante).
- La regla de que cada capa solo habla con la siguiente la garantiza la revisión de código, no una herramienta. Se podría automatizar con una herramienta como `import-linter`.
