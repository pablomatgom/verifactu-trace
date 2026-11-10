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
- No se pidió tarjeta de pago al crear la cuenta.

Cualquier otro recurso puede estar limitado por la misma política. Por eso cada capa se prueba al crearla y se anota aquí lo que la política impida.

## Persistencia

**Decisión: PostgreSQL en un contenedor de la instancia, con los datos en un volumen de bloque (EBS)** aparte de la instancia. La alternativa era una base de datos gestionada (Amazon RDS).

El enunciado admite las dos: pide "almacenamiento en bloque o base de datos gestionada". No es, por tanto, un requisito, sino una decisión práctica.

### Efecto sobre la configuración

Hoy PostgreSQL y Redis son contenedores de [`compose.yaml`](../compose.yaml), y los servicios leen la dirección de la base de datos de `DATABASE_URL`.

| | Contenedor con volumen (elegida) | Base de datos gestionada (RDS) |
|---|---|---|
| `DATABASE_URL` | No cambia: sigue apuntando al contenedor `postgres` | Apuntaría a la dirección de RDS |
| `compose.yaml` en la nube | Igual que en local | Sin el servicio `postgres` |
| Redis | Contenedor en la instancia | Contenedor en la instancia |
| Copias de seguridad y parches | Los hace el proyecto | Los hace AWS |
| Coste | Solo el disco | Una instancia aparte, bastante más |
| Riesgo con la cuenta | Bajo: la red ya se creó sin bloqueo, y las instancias y los volúmenes son lo habitual, aunque aún no se han probado | No se sabe si la política de la organización lo permite |
| Subredes | Una subred privada basta | RDS exige subredes en dos zonas de disponibilidad |

### Por qué el contenedor con volumen

- **Coste:** el crédito de la cuenta no se ha podido comprobar, y RDS es la parte más cara.
- **Riesgo:** la cuenta pertenece a una organización que aplica una política que ya bloqueó una acción. Un servicio más complejo como RDS aumenta la probabilidad de otro bloqueo.
- **Sin cambios en la aplicación:** `DATABASE_URL`, `compose.yaml`, las migraciones y las pruebas de integración siguen valiendo tal cual.
- **Cumple el enunciado:** el volumen aparte de la instancia es "almacenamiento en bloque".

### Qué se pierde

- Las copias de seguridad y los parches de PostgreSQL pasan a ser responsabilidad del proyecto.
- No hay conmutación automática a otra zona si la que aloja la instancia falla.
- Es menos habitual en un despliegue real, donde se usaría un servicio gestionado.

El volumen se crea en la **misma zona de disponibilidad** que la instancia, porque solo se puede conectar a instancias de su zona. Por eso el módulo de red devuelve la zona como salida y pone las dos subredes en ella.

## Capa de red

Definida en el módulo [`infra/modules/network`](../infra/modules/network/) (14 recursos). Sus decisiones:

| Decisión | Motivo |
|---|---|
| Una VPC `10.0.0.0/16`, con una subred pública (`10.0.1.0/24`) y una privada (`10.0.2.0/24`) | El enunciado pide subredes públicas y privadas |
| Las dos subredes están en la misma zona de disponibilidad (`eu-north-1a`) | El volumen de EBS con los datos solo se conecta a instancias de su zona |
| Lo que distingue una subred pública de una privada es su **tabla de rutas**: la pública tiene la ruta `0.0.0.0/0` hacia el *internet gateway* y la privada no | Así funciona AWS: la subred en sí no es ni pública ni privada |
| Sin *NAT Gateway* | Tiene un coste fijo por hora y la subred privada no necesita salir a Internet |
| La subred pública no asigna IP pública por sí sola | La pedirá la instancia que se cree en ella |
| El grupo de seguridad del servidor abre solo los puertos de la aplicación (8001, 8002 y 8003) y deja salir todo el tráfico | La instancia necesita descargar las imágenes de GHCR |
| El puerto 22 (SSH) está cerrado, salvo que se indique una dirección en `admin_cidr_blocks` | Mínimo privilegio: el acceso de administración se decide al crear el servidor |
| Los puertos 5432 (PostgreSQL) y 6379 (Redis) no se abren | Son contenedores de la instancia y hablan con los servicios dentro de ella |
| El grupo de seguridad por defecto de la VPC se declara sin reglas | Un recurso creado sin indicar grupo no hereda ningún permiso |

Los puertos abiertos son una variable (`app_ports`), para reducirlos a uno solo cuando exista el *gateway* de la API. Mientras tanto, esos tres puertos están abiertos a todo Internet (`app_allowed_cidr_blocks`); es una limitación temporal.

`terraform apply` creó los 14 recursos sin que la política de la organización bloqueara ninguno, y `terraform destroy` los eliminó todos.

## Capa de persistencia

Definida en el módulo [`infra/modules/storage`](../infra/modules/storage/), que crea un volumen de EBS para los datos de PostgreSQL.

| Decisión | Motivo |
|---|---|
| Tipo `gp3`, 10 GB por defecto (`data_volume_size_gb`) | Es el tipo de propósito general actual, y el tamaño sobra para un laboratorio |
| Cifrado en reposo (`encrypted = true`) con la clave por defecto de EBS | Los datos de las facturas no deben guardarse sin cifrar |
| El disco está en la zona de disponibilidad que devuelve el módulo de red | Un volumen solo se conecta a instancias de su zona |
| El módulo no conecta el disco | La conexión necesita el identificador de la instancia, que pertenece a la capa de cómputo |
| Sin copia final al destruir (`terraform destroy` borra el disco y sus datos) | El laboratorio se apaga al terminar cada sesión, y el enunciado exige que no quede nada generando costes |

`terraform apply` creó los 15 recursos (los 14 de la red y el volumen) sin que la política de la organización bloqueara ninguno, y `terraform destroy` los eliminó todos, también el volumen.

### `DATABASE_URL`

No cambia respecto a local. [`compose.yaml`](../compose.yaml) la construye con las tres variables de PostgreSQL y el nombre del servicio, dentro de la red interna de Docker:

```text
postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
```

El módulo de almacenamiento no necesita devolver ninguna dirección: PostgreSQL es un contenedor de la propia instancia, y su única salida es `volume_id`, para que el cómputo conecte el disco. La contraseña es la variable sensible `db_password`, que la capa de cómputo entregará al contenedor como `POSTGRES_PASSWORD`, sin escribirla en el repositorio.

### Lo que queda para la capa de cómputo

- Conectar el disco a la instancia, formatearlo la primera vez y montarlo en una carpeta.
- Hacer que el contenedor de PostgreSQL guarde sus datos ahí. Un disco recién formateado trae una carpeta `lost+found` en la raíz, y PostgreSQL no inicializa un directorio de datos que no esté vacío. Los datos irán en una subcarpeta (con `PGDATA`).

### Limitaciones

- **No hay copias de seguridad.** Si el disco se borra (por ejemplo con `terraform destroy`), los datos se pierden.
- **Redis no usa este disco.** El *stream* de eventos de Redis queda en el disco de la instancia. La fuente de la verdad es PostgreSQL, y el *stream* solo transporta los eventos hasta que se procesan.
- **Una sola zona.** Si esa zona falla, no hay conmutación a otra.

## Pendiente

Se completa en las issues de las capas y en la de documentación del hito:

- El módulo de cómputo (los de red y de almacenamiento ya están hechos).
- Justificación del backend remoto y del bloqueo del estado, más allá de lo descrito en [`terraform.md`](terraform.md).
- Tabla con los entregables del enunciado y el lugar donde se cumple cada uno.
- Cómo desplegar y destruir la infraestructura, paso a paso.
- El experimento del patrón *Reconciler* y la verificación del apagado.
