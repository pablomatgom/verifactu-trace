# AWS: conceptos y comandos

Este documento explica los conceptos de AWS que usa el proyecto y los comandos de la AWS CLI con los que se ha preparado la cuenta. La definición de la infraestructura con Terraform está en [`terraform.md`](terraform.md).

Los comandos están escritos para **PowerShell**. En el Símbolo del sistema (cmd) cambia la sintaxis de las variables (ver [Variables](#variables)).

## Servicios de AWS que usa el proyecto

AWS es un catálogo de servicios que se alquilan por uso. Cada uno hace una cosa y tiene un nombre corto.

| Servicio | Para qué sirve | Uso en el proyecto |
|---|---|---|
| **S3** | Guardar ficheros | Estado de Terraform |
| **IAM** | Controlar quién puede hacer qué | Usuario con el que Terraform accede a AWS |
| **STS** | Decir con qué identidad se está actuando | Comprobar que las credenciales funcionan |
| **VPC** | Red privada virtual | Capa de red |
| **EC2** | Servidor (máquina virtual) | Capa de cómputo |
| **EBS** | Discos (volúmenes) que se conectan a una instancia | Capa de persistencia: los datos de PostgreSQL |

S3, IAM, STS, la red (VPC) y el almacenamiento (EBS) ya están en uso. EC2 se añade con la capa de cómputo.

## Cuenta, región y organización

- **Cuenta**: el contenedor de todos los recursos, usuarios y la facturación. Se identifica con un número de 12 dígitos.
- **Región**: una zona geográfica con varios centros de datos (Estocolmo, Irlanda, Fráncfort...). Los recursos viven en la región donde se crean y los datos no salen de ella salvo orden expresa. El proyecto usa **`eu-north-1` (Estocolmo)**, una región de la Unión Europea (RGPD).
- **Organización y política de control de servicios (SCP)**: una cuenta puede pertenecer a una *AWS Organization* cuyo administrador define reglas por encima de los permisos de IAM. Para que una acción funcione, deben permitirla las dos capas:

  ```text
  Organización   ← SCP: "en esta cuenta solo se permite X"
  └── Cuenta
      └── Usuario IAM y sus políticas   ← "este usuario puede hacer Y"
  ```

  En esta cuenta, crear un bucket en `eu-west-1` fue rechazado por una SCP (`explicit deny in a service control policy`); en `eu-north-1`, la región del proyecto, funcionó. Una SCP no puede quitarla el usuario, ni siquiera con `AdministratorAccess`.

## S3 y los buckets

**S3** (*Simple Storage Service*) es un almacén de ficheros en la nube. Un **bucket** es su contenedor de nivel superior: un espacio con nombre donde se guardan **objetos** (ficheros).

```text
bucket: verifactu-trace-tfstate-<id de cuenta>
└── verifactu-trace/terraform.tfstate     ← un objeto: el estado de Terraform
```

- No es un disco: es un servicio al que se suben y descargan ficheros mediante una API.
- El nombre del bucket es **único en todo el mundo**. Por eso el del proyecto lleva el identificador de la cuenta.
- Cada bucket vive en una región.
- Se paga por GB guardados y por peticiones. El fichero de estado ocupa poco más de 1 KB.
- Un bucket mal configurado puede quedar público por error. El del proyecto tiene tres protecciones:

| Protección | Qué hace |
|---|---|
| Bloqueo de acceso público | Impide que se haga público por accidente |
| Versionado | Conserva las versiones anteriores de cada objeto, para recuperar un estado corrupto |
| Cifrado AES256 | Los datos se guardan cifrados en el disco de AWS (S3 lo aplica por defecto) |

## IAM: identidades y permisos

**IAM** (*Identity and Access Management*) responde a dos preguntas: quién es el solicitante y qué se le permite hacer.

| Concepto | Qué es | En el proyecto |
|---|---|---|
| **Usuario raíz** | La identidad con la que se creó la cuenta, con poder absoluto | No se usa para trabajar |
| **Usuario IAM** | Identidad con permisos limitados, para personas o programas | `terraform-verifactu` |
| **Política** (*policy*) | Lista de permisos ("puede hacer X sobre Y") | `AdministratorAccess` |
| **Clave de acceso** | Par ID y secreto que permite a un programa identificarse como un usuario | Perfil `verifactu` de la CLI |
| **Rol** | Identidad temporal que se asume, sin claves almacenadas | Previsto para el pipeline de despliegue |

### Por qué no se trabaja con el usuario raíz

Si se filtrara la clave del usuario raíz, quien la tuviera controlaría toda la cuenta. Un usuario IAM se puede desactivar o borrar sin perder la cuenta, y se le pueden limitar los permisos.

El usuario `terraform-verifactu` tiene `AdministratorAccess` porque solo se usa en la máquina del desarrollador. El pipeline de despliegue usará un rol con permisos mínimos.

### Cómo se identifica un programa

Terraform y la CLI no usan usuario y contraseña, sino la **clave de acceso**:

1. `aws configure --profile verifactu` guarda el ID y el secreto en `~/.aws/credentials`.
2. Con `AWS_PROFILE=verifactu`, el programa lee esa clave y la envía a AWS.
3. AWS la valida y deja actuar como `terraform-verifactu`.

El secreto no debe salir de la máquina: quien lo tenga puede actuar como ese usuario. No se guarda en el repositorio, en ficheros `.tfvars` ni en mensajes. La clave se borra al terminar el trabajo.

## Redes en AWS

La capa de red define dónde corre la aplicación y quién puede llegar a cada pieza. Estos son los conceptos:

| Concepto | Qué es | Analogía |
|---|---|---|
| **VPC** (*Virtual Private Cloud*) | Red privada aislada de las de otros clientes, con un rango de direcciones IP | El edificio de oficinas alquilado |
| **Subred** | Porción de la VPC con su propio rango, dentro de una zona de disponibilidad | Una planta del edificio |
| **Zona de disponibilidad** (AZ) | Un centro de datos concreto dentro de una región (`eu-north-1a`, `eu-north-1b`...) | Un edificio distinto del mismo campus |
| **Subred pública** | Subred con salida directa a Internet | La planta con puerta a la calle |
| **Subred privada** | Subred sin acceso desde Internet | La planta interior |
| **Internet Gateway** | Puerta de la VPC hacia Internet | La puerta principal |
| **Tabla de enrutamiento** | Reglas que dicen por dónde sale el tráfico hacia cada destino | La señalización |
| **Grupo de seguridad** | Cortafuegos de un recurso: qué tráfico puede entrar y salir | El guardia de cada puerta |

### Notación CIDR

Un rango de direcciones se escribe como una IP seguida de `/n`. Cuanto mayor es `n`, más pequeña es la red:

| Notación | Direcciones | Uso típico |
|---|---|---|
| `10.0.0.0/16` | unas 65.000 | La VPC entera |
| `10.0.1.0/24` | 256 | Una subred |

### Diseño

Lo define el módulo [`infra/modules/network`](../infra/modules/network/):

```text
VPC 10.0.0.0/16
│
├── Subred pública 10.0.1.0/24   ← el servidor (EC2), con salida a Internet
│       grupo de seguridad: solo los puertos de la aplicación
│
└── Subred privada 10.0.2.0/24   ← sin ruta a Internet; de momento no aloja nada
```

PostgreSQL y Redis son contenedores de la propia instancia y hablan con los servicios dentro de ella, así que sus puertos (5432 y 6379) **no se abren al exterior**. Es el principio de **mínimo privilegio**: cada pieza ve solo lo que necesita. El puerto 22 (SSH) tampoco está abierto, salvo que se indique una dirección en `admin_cidr_blocks`.

AWS crea además un **grupo de seguridad por defecto** en cada VPC, que permite el tráfico entre sus miembros y en el que acaba cualquier recurso creado sin indicar grupo. El módulo lo declara **sin reglas**, de modo que Terraform se las quita todas y un recurso que llegue ahí por descuido no hereda ningún permiso.

La subred privada está vacía a propósito: el enunciado pide subredes públicas y privadas, y queda disponible para lo que nunca deba ser accesible desde fuera (por ejemplo, una base de datos gestionada en el futuro). Ambas subredes están en la misma zona de disponibilidad, porque el disco con los datos de PostgreSQL solo se puede conectar a una instancia de **su misma zona**.

Las VPC, las subredes y los grupos de seguridad no tienen coste en AWS. Lo que cuesta son el servidor y el disco.

## Almacenamiento en bloque (EBS)

**EBS** (*Elastic Block Store*) ofrece discos virtuales que se conectan a una instancia de EC2, como un disco duro a un ordenador. Se diferencia de S3 en cómo se usa:

| | S3 | EBS |
|---|---|---|
| Qué guarda | Ficheros (objetos), a los que se accede por una API | Un disco, con su sistema de ficheros |
| Cómo se usa | Se suben y se descargan | Se conecta a una instancia y se monta como una carpeta |
| Uso en el proyecto | El estado de Terraform | Los datos de PostgreSQL |

Lo que conviene saber de un volumen EBS:

- **Vive fuera de la instancia.** Si la instancia se para, se reinicia o se sustituye, el disco y sus datos siguen ahí y se pueden conectar a otra.
- **Está atado a una zona de disponibilidad.** Solo se puede conectar a instancias de la misma zona, por eso el módulo de red devuelve la zona y el de almacenamiento la recibe.
- **El tipo `gp3`** es el de propósito general actual, con un rendimiento base que no depende del tamaño.
- **Se cifra en reposo** con la clave que AWS gestiona por defecto para EBS (`encrypted = true`).
- **Se paga por GB y por mes mientras existe**, esté conectado o no. Un disco de 10 GB cuesta muy poco, pero no es cero.

## Comandos de la AWS CLI

Todos los comandos de la CLI siguen la misma forma:

```text
aws  <servicio>  <acción>  --opciones
aws  sts         get-caller-identity   --profile verifactu
aws  s3api       create-bucket         --bucket <nombre> --region eu-north-1
```

En S3, las acciones que empiezan por `put-` **configuran** y las que empiezan por `get-` **leen**. Después de configurar algo conviene leerlo, para comprobarlo en vez de fiarse de que no haya dado error.

### Instalar las herramientas

```powershell
winget install --id Hashicorp.Terraform -e
winget install --id Amazon.AWSCLI -e
terraform version
aws --version
```

`winget` es el instalador de programas de Windows. `--id` indica el programa y `-e` (*exact*) obliga a que el identificador coincida exactamente. Las dos últimas órdenes muestran la versión y sirven para comprobar que el terminal encuentra los programas. Tras instalar hay que **abrir una ventana nueva**, para que se actualice el `PATH`. Terraform necesita la versión 1.10 o superior.

### Credenciales y perfiles

```powershell
aws configure --profile verifactu
aws configure list --profile verifactu
aws configure get region --profile verifactu
aws configure set region eu-north-1 --profile verifactu
aws sts get-caller-identity --profile verifactu
```

| Comando | Qué hace |
|---|---|
| `aws configure --profile verifactu` | Pide la clave de acceso, la región por defecto y el formato de salida (`json`), y los guarda en `~\.aws\credentials` y `~\.aws\config` bajo el nombre `verifactu` |
| `aws configure list` | Muestra qué credenciales usa el perfil, con los secretos tapados |
| `aws configure get` / `set` | Lee o cambia un valor del perfil, por ejemplo la región |
| `aws sts get-caller-identity` | Pregunta a AWS con qué identidad lo está viendo. Devuelve la cuenta y el usuario. **Es la prueba de que las credenciales funcionan** |

`--profile verifactu` da nombre a un conjunto de credenciales, para tener varias cuentas en la misma máquina sin mezclarlas.

### Variables

```powershell
$env:AWS_PROFILE = "verifactu"
$region = "eu-north-1"
$account = aws sts get-caller-identity --query Account --output text
$bucket = "verifactu-trace-tfstate-$account"
```

| Línea | Qué hace |
|---|---|
| `$env:AWS_PROFILE = "verifactu"` | Fija una **variable de entorno**: indica a la CLI y a Terraform qué perfil usar, sin escribir `--profile` en cada comando. Dura mientras la ventana esté abierta |
| `$region = "eu-north-1"` | Crea una variable de PowerShell, para reutilizarla. La ve solo la sesión, no otros programas |
| `$account = aws sts ...` | Guarda en una variable el **resultado de un comando**. `--query Account` filtra la respuesta para quedarse solo con el número y `--output text` lo devuelve sin formato JSON |
| `$bucket = "...-$account"` | Compone el nombre del bucket con el valor de `$account` |

`$env:...` es para otros programas y `$variable` es solo de la sesión de PowerShell. En el **Símbolo del sistema (cmd)** una variable de entorno se escribe `set AWS_PROFILE=verifactu`, sin comillas ni espacios alrededor del `=`. Una variable de entorno que ya exista (`AWS_ACCESS_KEY_ID`, `AWS_SESSION_TOKEN`) tiene prioridad sobre el perfil, y se ve con `Get-ChildItem Env:AWS*`.

### Crear el bucket del estado

```powershell
aws s3api create-bucket --bucket $bucket --region $region --create-bucket-configuration LocationConstraint=$region
aws s3api put-public-access-block --bucket $bucket --region $region --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-versioning --bucket $bucket --region $region --versioning-configuration Status=Enabled
```

| Comando | Qué hace |
|---|---|
| `create-bucket` | Crea el bucket con el nombre de `--bucket`. `--create-bucket-configuration LocationConstraint=...` indica en qué región debe vivir, y es obligatorio en todas las regiones salvo `us-east-1`, por lo que parece repetir `--region` |
| `put-public-access-block` | Activa las cuatro protecciones que impiden que el bucket sea público |
| `put-bucket-versioning` | Activa el versionado |

### Comprobar el bucket

```powershell
aws s3api get-bucket-encryption --bucket $bucket --region $region
aws s3api get-bucket-versioning --bucket $bucket --region $region
aws s3api get-public-access-block --bucket $bucket --region $region
aws s3 ls s3://$bucket/verifactu-trace/
```

Los tres primeros muestran la configuración aplicada: debe aparecer `AES256`, `"Status": "Enabled"` y las cuatro protecciones en `true`. El último lista el contenido: aparece `terraform.tfstate`, la prueba de que el estado está en S3. `aws s3` (sin `api`) es la versión de alto nivel, con comandos como los del terminal (`ls`, `cp`, `rm`), y la ruta `s3://bucket/carpeta/` es la forma de escribir una ubicación en S3.

### `aws` y `terraform`

| Tipo | Ejemplos | Qué hace |
|---|---|---|
| `aws ...` | `s3api`, `sts`, `configure` | Habla con AWS **directamente** |
| `terraform ...` | `init`, `plan`, `apply` | Lee los ficheros `.tf` y llama a AWS por el usuario |

Con `aws` solo se hace a mano lo que Terraform no puede hacer: el bucket del estado, que debe existir antes de que Terraform pueda guardar nada. El resto de la infraestructura (red, base de datos, servidor) la crea Terraform.

## Limitaciones conocidas

- Las claves de acceso de larga duración son menos seguras que las credenciales temporales (`aws login`, roles). Se aceptan aquí porque la clave vive solo en la máquina del desarrollador y se borra al terminar.
- Los permisos reales de la cuenta los limita una SCP del administrador de la organización, que no se puede consultar ni cambiar desde la cuenta.
