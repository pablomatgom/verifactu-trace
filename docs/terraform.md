# Infraestructura con Terraform

La infraestructura en la nube se define como código en la carpeta [`infra/`](../infra/). Este documento describe cómo está organizada, dónde se guarda el estado, cómo se protegen las credenciales y cómo se usa. Los conceptos de AWS (S3, IAM, redes) y los comandos de la CLI están en [`aws.md`](aws.md).

## Qué es Terraform y cómo funciona

**Terraform** permite describir la infraestructura en ficheros de texto. Esos ficheros se versionan en Git, se revisan en las pull requests y se ejecutan para crear, cambiar o destruir la infraestructura. A esto se le llama *Infraestructura como Código* (IaC). Frente a crearla a mano en la consola del proveedor, queda registrada, se puede repetir igual en otra cuenta o región, y se puede destruir entera con un solo comando.

### Enfoque declarativo

Terraform es **declarativo**: no se le dicen los pasos, sino el resultado que se quiere.

```hcl
resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
}
```

Terraform compara lo que se quiere con lo que existe y calcula él solo qué hacer: crear, modificar o borrar. Si se ejecuta dos veces seguidas, la segunda no hace nada, porque ya coincide (`No changes`).

### Piezas

| Pieza | Qué es | En `infra/` |
|---|---|---|
| **Provider** | Traductor a un proveedor concreto (AWS, Azure...). Sabe llamar a su API | `hashicorp/aws`, en `providers.tf` |
| **Resource** | Algo que Terraform crea y gestiona (red, servidor, base de datos) | Se añaden con las capas de red, persistencia y cómputo |
| **Data source** | Algo que Terraform solo lee, sin crearlo | `aws_caller_identity`, que lee la cuenta |
| **Variable** | Dato de entrada | `aws_region`, `db_password` |
| **Output** | Dato de salida | `account_id`, `region` |
| **Module** | Carpeta de recursos reutilizable | Uno por capa, en `infra/modules/` |
| **Backend** | Dónde se guarda el estado | El bucket de S3 |

### El estado

Terraform necesita recordar qué recursos creó, para poder cambiarlos o destruirlos después. Lo guarda en el **estado** (`terraform.tfstate`), que relaciona cada recurso del código con el recurso real. Por ejemplo, que `aws_vpc.main` es la red `vpc-0abc123` de AWS.

- Sin el estado, Terraform no sabe qué es suyo: volvería a crearlo todo o no podría borrar nada.
- Puede contener datos sensibles, así que **no va al repositorio**.
- Si dos ejecuciones lo modifican a la vez se corrompe, por eso se **bloquea** mientras hay una en marcha.
- Guardarlo en S3 lo hace compartible y lo protege de que se pierda un equipo.

### Ciclo de trabajo

```text
terraform init       Prepara la carpeta: descarga el provider y conecta con el backend
terraform plan       Calcula qué cambiaría y lo enseña. No modifica nada
terraform apply      Aplica esos cambios, tras pedir confirmación
terraform destroy    Borra todo lo que Terraform gestiona
```

`plan` enseña el cambio **antes** de hacerlo: `+` para crear, `~` para modificar y `-` para borrar. Se revisa como el diff de un código.

### Cómo calcula los cambios

Terraform compara tres cosas:

```text
  el código   ──┐
  el estado   ──┼──►  plan: lo que hay que hacer
  la realidad ──┘
```

El **código** es lo que se quiere, el **estado** es lo que Terraform recuerda haber creado y la **realidad** es lo que hay ahora en AWS, que consulta con su API durante el `plan`. Si alguien cambia un recurso a mano en la consola, el estado ya no coincide con la realidad: es la **deriva** (*drift*), y `plan` la detecta.

### El patrón *Reconciler*

Es el principio sobre el que se apoya el experimento del Hito 3: un bucle que compara el estado deseado con el observado y corrige la diferencia. Es el mismo que usa Kubernetes.

1. `apply`: la infraestructura queda como dice el código (estado deseado).
2. Se cambia algo a mano en la consola (deriva).
3. `plan` detecta la diferencia entre lo deseado y lo real.
4. `apply` la reconcilia: devuelve la infraestructura a lo que dice el código.

## Estructura

```
infra/
├── providers.tf               # versiones de Terraform y del provider, y backend remoto
├── variables.tf               # variables de entrada
├── main.tf                    # etiquetas comunes y lectura de la cuenta
├── outputs.tf                 # valores de salida
├── terraform.tfvars.example   # ejemplo de valores, sin nada sensible
└── .terraform.lock.hcl        # versiones exactas de los providers (se commitea)
```

Las capas de red, persistencia y cómputo se añaden como módulos en `infra/modules/`.

## Proveedor y región

El proveedor es AWS. Toda la infraestructura se crea en **`eu-north-1` (Estocolmo)**, una región de la Unión Europea, que es la región del proyecto de AWS donde está la cuenta. En esta cuenta, crear un bucket en otra región (`eu-west-1`) fue rechazado por una política de la organización; en `eu-north-1` funcionó.

`aws_region` solo acepta regiones cuyo nombre empiece por `eu-`, de modo que no se puede desplegar fuera de la UE por error:

```hcl
validation {
  condition     = startswith(var.aws_region, "eu-")
  error_message = "The region must be one of the European Union (eu-*)."
}
```

## Estado remoto

El estado de Terraform describe qué recursos existen y puede contener datos sensibles, así que **no se guarda en el repositorio** sino en un bucket de S3, configurado como backend en [`providers.tf`](../infra/providers.tf):

| Propiedad | Valor |
|---|---|
| Bucket | `verifactu-trace-tfstate-<id de cuenta>` |
| Clave | `verifactu-trace/terraform.tfstate` |
| Cifrado | `encrypt = true`, además del cifrado por defecto del bucket (AES256) |
| Bloqueo | `use_lockfile = true`: crea un objeto de bloqueo en el mismo bucket mientras hay una operación en marcha, de modo que dos ejecuciones no pueden modificar el estado a la vez |
| Versionado | Activado en el bucket, para recuperar un estado anterior si se corrompe |
| Acceso público | Bloqueado por completo |

El bloqueo con `use_lockfile` requiere Terraform 1.10 o superior y evita la tabla de DynamoDB que antes se usaba para esto.

### Crear el bucket (una sola vez)

El bucket no lo crea Terraform: necesita existir antes de poder guardar el estado. Se crea a mano con la AWS CLI, con las credenciales del perfil `verifactu`: los comandos, uno a uno y con su explicación, están en [`aws.md`](aws.md#crear-el-bucket-del-estado), y su comprobación en [`aws.md`](aws.md#comprobar-el-bucket).

Los nombres de los buckets de S3 son únicos en todo el mundo, por eso el nombre lleva el identificador de la cuenta. Este identificador no es un secreto. Si el nombre cambia, hay que actualizarlo en `providers.tf`.

## Credenciales y secretos

| Qué | Dónde vive | Cómo se evita filtrarlo |
|---|---|---|
| Claves de acceso a AWS | `~/.aws/credentials`, perfil `verifactu`, solo en la máquina del desarrollador | El código no las menciona: Terraform las lee del perfil indicado en `AWS_PROFILE` |
| Contraseña de la base de datos | Variable de entorno `TF_VAR_db_password` | `db_password` está declarada con `sensitive = true` y **sin valor por defecto** |
| Estado | Bucket de S3 | `.gitignore` excluye `*.tfstate*` y `.terraform/` |
| Valores propios (`terraform.tfvars`) | Fichero local | `.gitignore` excluye `*.tfvars`; en el repositorio solo está `terraform.tfvars.example`, sin secretos |

El usuario IAM que usa Terraform en local es `terraform-verifactu`, solo para la máquina del desarrollador. Su clave de acceso debe borrarse al terminar el trabajo. El pipeline de despliegue usará un rol con permisos mínimos, sin claves almacenadas.

## Uso

Desde `infra/`, en PowerShell:

```powershell
$env:AWS_PROFILE = "verifactu"
$env:TF_VAR_db_password = "<contraseña>"
terraform init
terraform plan
terraform apply
```

- `terraform init` configura el backend remoto y descarga el provider.
- `terraform plan` compara el código con el estado y con la infraestructura real, y enseña lo que cambiaría.
- `terraform apply` lo aplica, tras pedir confirmación.

Las variables de entorno solo duran mientras la ventana está abierta, así que la contraseña no queda guardada.

En el **Símbolo del sistema (cmd)** la sintaxis es `set AWS_PROFILE=verifactu`, sin comillas ni espacios alrededor del `=`.

## Integración continua

El trabajo `terraform` de [`ci.yml`](../.github/workflows/ci.yml) ejecuta `terraform fmt -check`, `terraform init -backend=false` y `terraform validate`. No necesita credenciales de AWS ni accede al estado. Ver [`ci.md`](ci.md).

## Limitaciones conocidas

- El bucket del estado se crea a mano, fuera de Terraform. Es lo habitual, porque Terraform necesita el bucket antes de poder guardar su estado.
- El estado es único, sin separar entornos. Para este proyecto, con un solo entorno, es suficiente.
- Las credenciales locales son una clave de acceso de larga duración. Se limita el riesgo con que vive solo en la máquina del desarrollador y se borra al terminar.
