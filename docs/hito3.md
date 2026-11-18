# Decisiones del Hito 3

Este documento recoge las decisiones del Hito 3 (infraestructura como código con Terraform), el resultado del experimento del patrón *Reconciler*, dónde se cumple cada entregable del enunciado y cómo crear y destruir la infraestructura. Cómo está organizado el código está en [`terraform.md`](terraform.md), y los conceptos y comandos de AWS en [`aws.md`](aws.md). Los diagramas de lo que se despliega están en [`despliegue.md`](despliegue.md).

## Proveedor de nube

**Decisión: AWS**, en la región `eu-north-1` (Estocolmo).

### Alternativas consideradas

El enunciado permite una nube pública con capa gratuita o créditos de estudiante, o una nube privada propia. No se dispone de infraestructura propia, así que se compararon tres nubes públicas:

| Proveedor | Oferta para cuentas nuevas | Base de datos gestionada | Tarjeta de pago |
|---|---|---|---|
| **AWS** | Hasta 200 $ en créditos durante 6 meses (plan gratuito) | RDS, con cargo a los créditos | Según el tipo de cuenta |
| **Azure para estudiantes** | 100 $ durante un año, renovables | PostgreSQL Flexible Server | No, pero exige verificar el correo académico |
| **Google Cloud** | 300 $ durante 90 días | Cloud SQL | Sí |

Las cifras son las que publican los proveedores en el momento de la elección y pueden cambiar. El crédito real de la cuenta usada, que es un proyecto gestionado (ver más abajo), es el que muestra el panel de EC2 el 17 de noviembre de 2026: **120 USD restantes, con 172 días hasta su caducidad** (el 8 de mayo de 2027). Se ve en [`10-consola-ec2-vacia.pdf`](evidencias/hito3/10-consola-ec2-vacia.pdf). El saldo se consulta en la consola de AWS, en *Billing and Cost Management*.

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
| Riesgo con la cuenta | Bajo: la red, el volumen y la instancia se crearon sin que la política de la organización bloqueara nada | No se sabe si la política de la organización lo permite |
| Subredes | Una subred privada basta | RDS exige subredes en dos zonas de disponibilidad |

### Por qué el contenedor con volumen

- **Coste:** el crédito de la cuenta es limitado (120 USD), y RDS es la parte más cara.
- **Riesgo:** la cuenta pertenece a una organización que aplica una política que ya bloqueó una acción. Un servicio más complejo como RDS aumenta la probabilidad de otro bloqueo.
- **Sin cambios en la aplicación:** `DATABASE_URL`, `compose.yaml`, las migraciones y las pruebas de integración siguen valiendo tal cual.
- **Cumple el enunciado:** el volumen aparte de la instancia es "almacenamiento en bloque".

### Qué se pierde

- Las copias de seguridad y los parches de PostgreSQL pasan a ser responsabilidad del proyecto.
- No hay conmutación automática a otra zona si la que aloja la instancia falla.
- Es menos habitual en un despliegue real, donde se usaría un servicio gestionado.

El volumen se crea en la **misma zona de disponibilidad** que la instancia, porque solo se puede conectar a instancias de su zona. Por eso el módulo de red devuelve la zona como salida y pone las dos subredes en ella.

## Estructura de módulos

La infraestructura está en tres módulos de [`infra/modules/`](../infra/modules/), uno por capa del enunciado, y la raíz de [`infra/`](../infra/) solo los conecta:

| Módulo | Qué crea | Recibe | Devuelve |
|---|---|---|---|
| `network` | VPC, subredes, rutas y grupos de seguridad | Nombre del proyecto, puertos y direcciones permitidas | Identificadores de la red, de las subredes y del grupo de seguridad, y la zona |
| `storage` | Disco de EBS para PostgreSQL | La zona que devuelve `network` | `volume_id` |
| `compute` | Instancia, rol de IAM, parámetro con la contraseña y conexión del disco | Subred y grupo de `network`, disco de `storage` y la contraseña | `instance_id` y `public_ip` |

Las dependencias van en un solo sentido (`network`, después `storage`, después `compute`), y un módulo nunca lee los recursos de otro: solo recibe sus salidas como variables. Por eso se pudo construir, aplicar y destruir capa a capa.

| Decisión | Motivo |
|---|---|
| Un módulo por capa, y no un único `main.tf` | Cada capa tiene un motivo claro para cambiar y se prueba por separado. Con un único fichero, la red, el disco y la instancia quedarían mezclados |
| No un módulo por recurso | Sería demasiada fragmentación para unas 22 piezas: cada módulo exigiría su propio `variables.tf` y `outputs.tf` solo para un recurso |
| El disco se crea en `storage` pero se conecta en `compute` | La conexión necesita la instancia, que pertenece a `compute`. Así `storage` no depende de ella |
| Los valores que dependen de otro módulo no tienen valor por defecto | Si se olvida pasarlos, Terraform falla en el `plan` y no crea nada a medias |

## Estado remoto y secretos

El estado de Terraform es la lista de lo que ha creado, y **puede contener datos sensibles** (aquí, la contraseña de la base de datos). Se guarda en un bucket de S3 y no en el repositorio ni en el portátil:

| Decisión | Motivo |
|---|---|
| Backend remoto en S3 | Un estado local se pierde con el portátil, no se puede compartir con el pipeline del Hito 4 y acabaría en el repositorio por descuido |
| Bloqueo con `use_lockfile` | Dos `apply` a la vez podrían corromper el estado. Con Terraform 1.10 o superior el bloqueo es un objeto del propio bucket, sin la tabla de DynamoDB que antes hacía falta |
| Versionado y cifrado en el bucket, y acceso público bloqueado | Permite recuperar un estado anterior y protege los datos sensibles que contiene |
| El bucket se crea a mano, no con Terraform | Terraform necesita el bucket antes de poder guardar su estado. Es lo habitual |
| La contraseña de la base de datos entra por `TF_VAR_db_password`, sin valor por defecto y con `sensitive = true` | Nunca está escrita en el repositorio ni se muestra en el `plan` |
| `*.tfvars` y el estado local excluidos en `.gitignore`, con un `terraform.tfvars.example` sin secretos | El enunciado exige aislar los secretos y no subir los `.tfvars` |
| Claves de AWS en el perfil `verifactu` de `~/.aws/credentials` | El código no las menciona |

Los detalles (propiedades del bucket, comandos y gestión de las credenciales) están en [`terraform.md`](terraform.md#estado-remoto).

Una limitación: el usuario IAM de Terraform (`terraform-verifactu`) tiene `AdministratorAccess`, más de lo necesario, y es una clave de larga duración. Se acepta mientras el despliegue sea manual, y el pipeline del Hito 4 usará un rol con permisos mínimos y sin claves.

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
| No hay ninguna regla para el puerto 22 (SSH) | La instancia se administra con Session Manager (ver [Capa de cómputo](#capa-de-cómputo)), que no necesita ningún puerto abierto ni claves |
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

El módulo de almacenamiento no necesita devolver ninguna dirección: PostgreSQL es un contenedor de la propia instancia, y su única salida es `volume_id`, para que el cómputo conecte el disco. La contraseña es la variable sensible `db_password`, que la capa de cómputo guarda en Parameter Store y entrega al contenedor como `POSTGRES_PASSWORD`, sin escribirla en el repositorio.

### Lo que hace la capa de cómputo con el disco

- Lo conecta a la instancia, lo formatea la primera vez y lo monta en una carpeta.
- Hace que el contenedor de PostgreSQL guarde sus datos ahí. Un disco recién formateado trae una carpeta `lost+found` en la raíz, y PostgreSQL no inicializa un directorio de datos que no esté vacío. Los datos van en una subcarpeta (con `PGDATA`).

### Limitaciones

- **No hay copias de seguridad.** Si el disco se borra (por ejemplo con `terraform destroy`), los datos se pierden.
- **Redis no usa este disco.** El *stream* de eventos de Redis queda en el disco de la instancia. La fuente de la verdad es PostgreSQL, y el *stream* solo transporta los eventos hasta que se procesan.
- **Una sola zona.** Si esa zona falla, no hay conmutación a otra.

## Capa de cómputo

Definida en el módulo [`infra/modules/compute`](../infra/modules/compute/): una instancia de EC2 que instala Docker, monta el disco de datos y arranca el sistema completo con las imágenes publicadas en GHCR.

| Decisión | Motivo |
|---|---|
| Instancia `t3.small` (2 GB) | Ejecuta cinco contenedores (los tres servicios, PostgreSQL y Redis). Con 1 GB iría justa |
| Arquitectura x86, no ARM | Las imágenes se construyen solo para amd64 |
| Amazon Linux 2023 | Imagen oficial de AWS, con el agente de Systems Manager y la AWS CLI ya incluidos |
| Arranque con `user_data`, en un script de la plantilla [`user_data.sh.tftpl`](../infra/modules/compute/templates/user_data.sh.tftpl) | Es la forma habitual de configurar una instancia al crearla. Un cambio en el script la sustituye |
| `compose.yaml` propio de la nube ([`files/compose.yaml`](../infra/modules/compute/files/compose.yaml)) | Usa las imágenes de GHCR en lugar de construirlas, publica los puertos en todas las interfaces (decide el grupo de seguridad) y guarda los datos de PostgreSQL en el disco |
| Docker Compose se descarga con versión y suma de comprobación fijadas | No está en los repositorios de Amazon Linux, y una descarga sin verificar sería un riesgo |
| Acceso con Session Manager, sin SSH | No se abre el puerto 22 ni hay claves que guardar o rotar |
| La contraseña de la base de datos vive en Parameter Store, no en el script | El script lo puede leer cualquiera que pueda describir la instancia. La instancia lee la contraseña al arrancar, con un permiso limitado a ese parámetro |
| IMDSv2 obligatorio, disco raíz cifrado | Buenas prácticas de seguridad |
| `ami` ignorada en los cambios | Una imagen nueva de Amazon Linux no debe sustituir una instancia que está funcionando |
| El disco se desconecta parando antes la instancia (`stop_instance_before_detaching`) | Sin esto, `terraform destroy` espera a un disco que sigue en uso |

### Cómo arranca el sistema

El script se ejecuta una vez, en el primer arranque, y deja el registro en `/var/log/verifactu-setup.log`:

1. Instala Docker y Docker Compose.
2. Espera a que aparezca el disco de datos, lo formatea **solo si no tiene sistema de ficheros** (así conserva los datos si ya los tenía), lo monta en `/mnt/postgres` y lo añade a `/etc/fstab`.
3. Escribe el `compose.yaml` y el script SQL que crea los esquemas (el mismo [`db/init/01-schemas.sql`](../db/init/01-schemas.sql) del repositorio).
4. Lee la contraseña de Parameter Store y escribe el `.env`.
5. Arranca los contenedores con `docker compose up -d`.

PostgreSQL guarda sus datos en una subcarpeta del disco (`PGDATA`), porque un disco recién formateado trae una carpeta `lost+found` y PostgreSQL no inicializa un directorio de datos que no esté vacío.

### Verificación

Con `terraform apply` se crearon los 22 recursos (la red, el disco y las piezas de cómputo). Pasados unos minutos, los tres servicios respondieron `200` desde fuera, en `/health` de los puertos 8001, 8002 y 8003, sin haber abierto ninguna sesión en la instancia. Con una sesión de Session Manager, `docker compose ps` mostró los cinco contenedores en `healthy`. Los servicios ejecutan `alembic upgrade` al arrancar, así que las migraciones se aplicaron sobre PostgreSQL, lo que confirma que la contraseña de Parameter Store y el disco de datos funcionan.

### Limitaciones

- **El `compose.yaml` de la nube duplica la configuración del de la raíz.** Si se añade una variable o un servicio a uno, hay que añadirlo al otro.
- **La dirección pública cambia** si la instancia se para y se vuelve a arrancar.
- **Las imágenes se descargan en el primer arranque** (por defecto, `latest`), así que tarda unos minutos en responder y depende de que GHCR esté disponible.
- **Una sola instancia**: si se cae, el servicio está caído hasta que se sustituya.
- **Los datos de Redis no están en el disco de EBS**, sino en un volumen de Docker del disco de la instancia. Los eventos del *stream* se pierden si la instancia se sustituye o se destruye; los de PostgreSQL, no.
- **La contraseña está en el estado de Terraform** (cifrado, en S3) además de en Parameter Store.
- **La contraseña solo se aplica al inicializar el disco.** PostgreSQL lee `POSTGRES_PASSWORD` la primera vez que crea la base de datos; cambiarla después, con el disco ya creado, no cambia la de PostgreSQL y dejaría de coincidir con la del parámetro. Con `terraform destroy` el disco se borra, así que cada sesión puede usar una contraseña nueva.

## Experimento del patrón *Reconciler*

El experimento se hizo sobre la infraestructura desplegada, y su desarrollo con las salidas de los comandos está en el [`README.md`](../README.md#verificación-del-patrón-reconciler). Las evidencias están en [`evidencias/hito3/`](evidencias/hito3/README.md).

| Fase | Qué ocurrió |
|---|---|
| **Estado deseado** | `terraform apply` creó los 22 recursos |
| **Deriva** | Se borró a mano, en la consola de AWS, la regla del puerto 8002 del grupo de seguridad. El servicio de ese puerto dejó de responder desde fuera, y los otros dos siguieron respondiendo |
| **Observación** | `terraform plan` avisó de que la regla ya no existía en AWS (*AWS resource not found during refresh*) y propuso crearla: `Plan: 1 to add, 0 to change, 0 to destroy` |
| **Reconciliación** | `terraform apply` creó de nuevo la regla (`1 added`), el servicio volvió a responder y un nuevo `plan` dio `No changes` |

Tres observaciones:

- **Qué ve Terraform y cuándo.** Al empezar, `plan` actualiza el estado con lo que hay en AWS (*refresh*): al no encontrar la regla, la quita del estado y, al comparar con el código, ve que falta y la crea. Por eso la deriva sale como una creación y no como un cambio.
- **Se eligió borrar una regla** porque su efecto se ve desde fuera, y el enunciado propone como ejemplo modificar la regla de un grupo de seguridad.
- **Terraform solo detecta lo que gestiona.** Una regla añadida a mano, que no está en el estado, no aparecería en el `plan`. No se probó, pero se deduce de cómo funciona la comparación. El Hito 4 prevé una auditoría periódica de la deriva.

## Entregables del hito y dónde se cumplen

El enunciado del Hito 3 pide cuatro entregables. Esta tabla dice dónde está cada requisito.

### Código de Terraform modularizado

| Requisito | Dónde se cumple |
|---|---|
| Archivos estándar (`main.tf`, `variables.tf`, `outputs.tf`, `providers.tf`) | En [`infra/`](../infra/), con la versión de Terraform (`>= 1.10`) y la del provider (`~> 6.0`) fijadas, y `.terraform.lock.hcl` en el repositorio. La estructura está en [`terraform.md`](terraform.md#estructura) |
| **Capa de red:** VPC, subredes públicas y privadas, tablas de enrutamiento y grupos de seguridad con mínimo privilegio | Módulo `network`: VPC `10.0.0.0/16`, una subred pública y una privada, una tabla de rutas por subred, y un grupo de seguridad que solo abre los puertos 8001 a 8003 (ver [Capa de red](#capa-de-red)) |
| **Capa de cómputo:** instancia que ejecuta contenedores | Módulo `compute`: instancia de EC2 que arranca los cinco contenedores con las imágenes de GHCR (ver [Capa de cómputo](#capa-de-cómputo)) |
| **Capa de persistencia:** almacenamiento en bloque o base de datos gestionada | Módulo `storage`: volumen de EBS cifrado, donde PostgreSQL guarda sus datos (ver [Persistencia](#persistencia)) |

### Gestión de estado remoto y credenciales

| Requisito | Dónde se cumple |
|---|---|
| Backend remoto | Bucket de S3 con bloqueo, versionado y cifrado, declarado en [`providers.tf`](../infra/providers.tf) (ver [Estado remoto y secretos](#estado-remoto-y-secretos)) |
| Variables sensibles declaradas | `db_password`, con `sensitive = true` y sin valor por defecto, que se pasa con `TF_VAR_db_password` |
| `.tfvars` fuera del repositorio | `.gitignore` excluye `*.tfvars` y el estado; solo está `terraform.tfvars.example`, sin secretos |

### Documentación del experimento del *Reconciler*

| Requisito | Dónde se cumple |
|---|---|
| `README.md` con capturas y trazas de las cuatro fases | Sección [«Verificación del patrón Reconciler»](../README.md#verificación-del-patrón-reconciler) del `README.md`, y las salidas y capturas en [`evidencias/hito3/`](evidencias/hito3/README.md) |
| Estado deseado, inducción de la deriva, observación (`plan`) y reconciliación (`apply`) | Ficheros `01` a `07` de las evidencias (ver [arriba](#experimento-del-patrón-reconciler)) |

### Verificación de apagado

| Requisito | Dónde se cumple |
|---|---|
| `terraform destroy` ejecutado con éxito | [`08-destroy.txt`](evidencias/hito3/08-destroy.txt): `Destroy complete! Resources: 22 destroyed` |
| Que no queda nada generando costes | [`09-sin-recursos.txt`](evidencias/hito3/09-sin-recursos.txt) (consulta a EC2, IAM y Parameter Store) y las capturas de la consola ([EC2](evidencias/hito3/10-consola-ec2-vacia.pdf) y [VPC](evidencias/hito3/10-consola-vpc-vacia.pdf)) |

## Cómo crear y destruir la infraestructura

Requisitos previos: Terraform 1.10 o superior, la AWS CLI, un usuario IAM con clave de acceso guardada en el perfil `verifactu` y el bucket del estado, que se crea una sola vez con los comandos de [`aws.md`](aws.md#crear-el-bucket-del-estado). Los comandos son de PowerShell y se ejecutan desde `infra/`.

**1. Credenciales y contraseña** (valen solo para esa ventana):

```powershell
$env:AWS_PROFILE = "verifactu"
$env:TF_VAR_db_password = -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 20 | ForEach-Object {[char]$_})
```

**2. Preparar Terraform:**

```powershell
terraform init
```

**3. Ver qué se va a crear.** Debe decir `Plan: 22 to add`:

```powershell
terraform plan
```

**4. Crear la infraestructura.** Pide confirmación y tarda menos de un minuto:

```powershell
terraform apply
```

**5. Comprobar el sistema.** Los servicios tardan unos 5 minutos en responder, porque la instancia instala Docker y descarga las imágenes:

```powershell
terraform output health_urls
curl.exe http://<public_ip>:8001/health
```

Repite el `curl.exe` con los puertos 8002 y 8003. Si no responden, el registro del arranque se lee abriendo una sesión (ver [`aws.md`](aws.md#acceder-a-la-instancia-y-comprobarla)).

**6. Destruir la infraestructura.** Es lo que más cuenta: la instancia genera coste mientras exista.

```powershell
terraform destroy
```

Debe terminar con `Destroy complete! Resources: 22 destroyed`. Escribe `yes` cuando lo pida, con la misma `TF_VAR_db_password` si la ventana sigue abierta.

**7. Comprobar que no queda nada.** Se pregunta directamente a EC2: no debe haber instancias en ejecución ni volúmenes, VPC o grupos de seguridad con la etiqueta del proyecto.

```powershell
aws ec2 describe-instances --region eu-north-1 --filters Name=tag:Project,Values=verifactu-trace --query "Reservations[].Instances[].{id:InstanceId,estado:State.Name}"
aws ec2 describe-volumes --region eu-north-1 --filters Name=tag:Project,Values=verifactu-trace --query "Volumes[].VolumeId"
aws ec2 describe-vpcs --region eu-north-1 --filters Name=tag:Project,Values=verifactu-trace --query "Vpcs[].VpcId"
```

Las instancias terminadas siguen apareciendo durante aproximadamente una hora y no cuestan nada. La API de etiquetas (`resourcegroupstaggingapi get-resources`) se actualiza con retraso y puede seguir listando recursos ya borrados, así que no sirve para esta comprobación.

Con `terraform destroy` el disco se borra con los datos de PostgreSQL, así que cada sesión empieza con una base de datos vacía, y la contraseña puede ser distinta.

## Versión

El estado entregado del hito es la versión **`v0.3.0`**, un tag anotado sobre `main`. Al subirlo, `docker.yml` publica en GHCR las imágenes `ghcr.io/pablomatgom/verifactu-trace/<servicio>:0.3.0` (y `sha-<commit>`) de los tres servicios, igual que con la `0.2.0`.

El Hito 3 añade la infraestructura (`infra/`) y su documentación, y no cambia el comportamiento de los servicios: su código solo se toca en dos comentarios. Por eso las imágenes de la `0.3.0` contienen la misma aplicación que las de la `0.2.0`.

Las evidencias se tomaron con el código de `infra/` tal como está en la versión: no se ha modificado desde que se añadió la capa de cómputo, y lo posterior al experimento solo cambia la documentación. El tag fija lo entregado, y el trabajo posterior en `main` no lo modifica.

## Mejoras posibles

Lo desplegado es el mínimo que cumple el enunciado: una instancia, con PostgreSQL y Redis en contenedores. Una puesta en producción cambiaría esto:

| Mejora | Qué resuelve | Por qué no se hizo |
|---|---|---|
| **RDS** en lugar del contenedor de PostgreSQL (en la subred privada) | Copias automáticas, parches y alta disponibilidad gestionados por AWS | Coste, y complica el `destroy` y la verificación del Reconciler (ver [Persistencia](#persistencia)) |
| **ElastiCache** en lugar del contenedor de Redis | Los eventos del *stream* sobreviven a la sustitución de la instancia, que hoy los pierde | Coste y complejidad para un solo *stream* |
| **Varias instancias detrás de un balanceador** (Load Balancer, en varias zonas de disponibilidad) | Hoy, si la instancia cae, el servicio está caído hasta que se sustituya | Una sola instancia basta para la práctica. El balanceador llegaría con el gateway |
| **Secrets Manager** en lugar de Parameter Store | Rotación automática de la contraseña | Parameter Store cubre lo necesario sin coste |
| **CloudWatch** (registros y alarmas) | Hoy el registro se lee abriendo una sesión en la instancia | Corresponde a la monitorización de un hito posterior |
| **HTTPS con dominio** (Route 53 y Certificate Manager) | Hoy el tráfico va por HTTP y a una dirección IP que cambia | Se decide con el gateway y la seguridad del Hito 4 |
