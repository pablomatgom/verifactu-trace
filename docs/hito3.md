# Decisiones del Hito 3

Este documento recoge las decisiones del Hito 3 (infraestructura como código con Terraform). Se completa a medida que se construyen las capas de la infraestructura. Cómo está organizado el código está en [`terraform.md`](terraform.md), y los conceptos y comandos de AWS en [`aws.md`](aws.md).

## Proveedor de nube

**Decisión: AWS**, en la región `eu-north-1` (Estocolmo).

### Alternativas consideradas

El enunciado permite una nube pública con capa gratuita o créditos de estudiante, o una nube privada propia. No se dispone de infraestructura propia, así que se compararon tres nubes públicas:

| Proveedor | Oferta para cuentas nuevas | Base de datos gestionada | Tarjeta de pago |
|---|---|---|---|
| **AWS** | Hasta 200 $ en créditos durante 6 meses (plan gratuito) | RDS, con cargo a los créditos | Según el tipo de cuenta |
| **Azure para estudiantes** | 100 $ durante un año, renovables | PostgreSQL Flexible Server | No, pero exige verificar el correo académico |
| **Google Cloud** | 300 $ durante 90 días | Cloud SQL | Sí |

Las cifras son las que publican los proveedores en el momento de la elección y pueden cambiar. **No se ha comprobado cuál es el crédito real de la cuenta usada**, que es un proyecto gestionado (ver más abajo): su saldo y su caducidad se consultan en la consola de AWS, en *Billing and Cost Management*.

### Por qué AWS

1. **El vocabulario del enunciado es el de AWS.** Habla de VPC, grupos de seguridad y de una política IAM para el rol de GitHub Actions. Con otro proveedor habría que traducir esos conceptos.
2. **La autenticación de GitHub Actions contra AWS con OIDC**, sin guardar claves, que se necesita en el Hito 4, está muy documentada.
3. **El estado remoto con bloqueo es sencillo**: un bucket de S3 con `use_lockfile` basta con Terraform 1.10 o superior, sin la tabla de DynamoDB que antes se usaba.
4. Dispone de regiones de la Unión Europea, necesarias por el RGPD.

### Características de la cuenta

La cuenta no es una cuenta de AWS independiente, sino un **proyecto gestionado** que pertenece a una organización de AWS:

- La organización aplica una política de control de servicios (SCP) que **limita lo que se puede hacer**, aunque el usuario IAM tenga `AdministratorAccess`.
- Crear un bucket en `eu-west-1` fue rechazado por esa política. En `eu-north-1`, la región del proyecto, funcionó.
- Por eso el proyecto usa `eu-north-1`. Es una región de la Unión Europea, así que cumple con el RGPD.
- No se pidió tarjeta de pago al crear la cuenta, de modo que no puede generar cargos.

Cualquier otro recurso puede estar limitado por la misma política. Por eso cada capa se prueba al crearla y se anota aquí lo que la política impida.

## Persistencia

**Decisión provisional: base de datos gestionada (Amazon RDS para PostgreSQL)**, con la posibilidad de volver a PostgreSQL en un contenedor con un volumen en la instancia si la política de la cuenta o el coste lo impiden. La decisión se confirma al crear la capa de persistencia.

### Efecto sobre la configuración

Hoy PostgreSQL y Redis son contenedores de [`compose.yaml`](../compose.yaml), y los servicios leen la dirección de la base de datos de `DATABASE_URL`.

| | Base de datos gestionada (RDS) | Volumen en la instancia |
|---|---|---|
| `DATABASE_URL` | Apunta a la dirección de RDS (una salida de Terraform) | Sigue apuntando al contenedor `postgres` |
| `compose.yaml` en la nube | Sin el servicio `postgres` | Igual que en local |
| Redis | Contenedor en la instancia | Contenedor en la instancia |
| Copias de seguridad y parches | Los hace AWS | Los hace el proyecto |
| Coste | Más alto, con cargo a los créditos | Más bajo |
| Seguridad de red | En una subred privada, accesible solo desde el grupo de seguridad del servidor | En la instancia, sin exposición adicional |

Los servicios aplican sus migraciones al arrancar, así que funcionan igual contra RDS. Habrá que comprobar que el usuario de la base de datos puede crear los tres esquemas (`documents`, `traceability` y `submissions`).

### Por qué RDS

- Es lo que pide el enunciado como ejemplo de capa de persistencia ("base de datos gestionada") y refleja mejor un despliegue real.
- La base de datos queda en una subred privada, sin acceso desde Internet.

El principal riesgo es el coste y que la política de la cuenta limite el servicio. Una instancia pequeña de RDS cuesta más que una instancia de cómputo equivalente, y su coste real debe comprobarse en la calculadora de AWS antes de dejarla encendida. La infraestructura se destruye al terminar cada sesión de trabajo.

## Pendiente

Se completa en las issues de las capas y en la de documentación del hito:

- Estructura de módulos (red, persistencia y cómputo).
- Justificación del backend remoto y del bloqueo del estado, más allá de lo descrito en [`terraform.md`](terraform.md).
- Tabla con los entregables del enunciado y el lugar donde se cumple cada uno.
- Cómo desplegar y destruir la infraestructura, paso a paso.
- El experimento del patrón *Reconciler* y la verificación del apagado.
