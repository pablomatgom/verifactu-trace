# Arquitectura de despliegue

Este documento muestra, con diagramas, qué se despliega en AWS y cómo se comunican las piezas. Los conceptos de AWS están en [`aws.md`](aws.md), el código de Terraform en [`terraform.md`](terraform.md) y las decisiones en [`hito3.md`](hito3.md). La organización interna de cada servicio está en [`arquitectura.md`](arquitectura.md).

Los diagramas son de Mermaid: GitHub los dibuja al abrir el fichero.

## Vista general

Quién habla con quién, desde fuera de AWS hasta los discos.

```mermaid
flowchart LR
    client["Cliente<br/>curl o navegador"]
    dev["Desarrollador<br/>terraform y aws CLI"]
    ghcr["GitHub Container Registry<br/>imágenes de los servicios"]

    subgraph aws["AWS · región eu-north-1 (Estocolmo)"]
        s3[("S3<br/>estado de Terraform")]
        iam["IAM<br/>rol verifactu-trace-app"]
        ssm["Systems Manager<br/>Session Manager y<br/>Parameter Store"]

        subgraph vpc["VPC 10.0.0.0/16"]
            igw["Internet Gateway"]

            subgraph pub["Subred pública 10.0.1.0/24"]
                ec2["EC2 t3.small<br/>Docker con los 5 contenedores<br/>Security group: 8001-8003"]
            end

            priv["Subred privada 10.0.2.0/24<br/>vacía, sin ruta a Internet"]
        end

        ebs[("EBS gp3 10 GB<br/>datos de PostgreSQL")]
    end

    client -- "HTTP 8001, 8002, 8003" --> igw
    igw --> ec2
    ec2 ---|"montado en /mnt/postgres"| ebs
    ec2 -- "docker pull al arrancar" --> ghcr
    ec2 -. "asume el rol" .-> iam
    ec2 -- "lee la contraseña" --> ssm
    dev -- "terraform apply" --> aws
    dev -- "estado y bloqueo" --> s3
    dev -- "aws ssm start-session<br/>(sin puerto 22)" --> ssm
    ssm -. "terminal" .-> ec2
```

Cosas que el diagrama deja ver:

- **El único tráfico que entra desde Internet son los puertos de los servicios** (8001 a 8003). No hay SSH: el terminal se abre a través de Systems Manager, que es la instancia quien lo pide hacia fuera.
- **La instancia sale a Internet por el Internet Gateway** para descargar las imágenes de GHCR y hablar con Systems Manager. Por eso la subred es pública y no hay NAT.
- **La subred privada está vacía.** Se creó para separar, en el futuro, lo que no debe tener dirección pública (por ejemplo una base de datos gestionada). Hoy PostgreSQL es un contenedor y vive en la instancia.
- **El disco de datos y la instancia son recursos distintos.** El disco sobrevive a la instancia, pero no a `terraform destroy`.
- **Terraform no pasa por la instancia.** Lo ejecuta el desarrollador desde su máquina, contra la API de AWS, y guarda el estado en S3.

## Dentro de la instancia

Los cinco contenedores y las dos redes de Docker.

```mermaid
flowchart TB
    internet(("Internet"))

    subgraph host["Instancia EC2 · Docker Compose"]
        subgraph edge["Red edge: publica los puertos"]
            doc["document-service<br/>:8001"]
            tra["traceability-service<br/>:8002"]
            sub["submission-service<br/>:8003"]
        end

        subgraph data["Red data: interna, sin acceso a Internet"]
            pg[("postgres<br/>esquemas documents,<br/>traceability y submissions")]
            redis[("redis<br/>stream invoice.issued")]
        end

        disk[("/mnt/postgres<br/>disco EBS")]
        vol[("volumen redis-data")]
    end

    internet --> doc
    internet --> tra
    internet --> sub

    doc --> pg
    tra --> pg
    sub --> pg

    doc -- "publica invoice.issued" --> redis
    redis -- "lee el stream" --> tra
    redis -- "lee el stream" --> sub
    tra -- "GET: reconstruir la cadena<br/>documental" --> doc

    pg --- disk
    redis --- vol
```

- Los tres servicios usan **la misma base de datos con un esquema cada uno**, y se comunican entre sí a través del *stream* de Redis, salvo una consulta: trazabilidad pide a `document-service` los documentos de una cadena (CU-11).
- PostgreSQL y Redis están en una red **interna** que no es alcanzable desde fuera ni tiene salida a Internet. Solo se publican los servicios.
- Los datos de PostgreSQL están en el disco de EBS. Los de Redis, en un volumen de Docker del disco de la propia instancia, así que **los eventos del *stream* no sobreviven a `terraform destroy`** ni a la sustitución de la instancia.

## Cómo arranca

Qué ocurre desde `terraform apply` hasta que un servicio responde.

```mermaid
sequenceDiagram
    actor Dev as Desarrollador
    participant TF as Terraform
    participant AWS as API de AWS
    participant EC2 as Instancia
    participant SSM as Parameter Store
    participant GH as GHCR

    Dev->>TF: terraform apply
    TF->>AWS: crea red, disco, rol y parámetro con la contraseña
    TF->>AWS: crea la instancia con el script user_data
    TF->>AWS: conecta el disco a la instancia
    TF-->>Dev: Apply complete (instance_id, public_ip, health_urls)

    Note over EC2: Primer arranque, unos minutos
    EC2->>EC2: instala Docker y Docker Compose
    EC2->>EC2: espera el disco, lo formatea si está vacío y lo monta
    EC2->>SSM: GetParameter con el rol de la instancia
    SSM-->>EC2: contraseña de la base de datos
    EC2->>GH: descarga las imágenes de los servicios
    GH-->>EC2: imágenes
    EC2->>EC2: docker compose up -d

    Dev->>EC2: curl health_urls (puertos 8001 a 8003)
    EC2-->>Dev: 200 OK
```

El script deja su registro en `/var/log/verifactu-setup.log`, que se lee abriendo una sesión (ver [`aws.md`](aws.md#acceder-a-la-instancia-y-comprobarla)).

## Qué cambia en el Hito 4

- Un **gateway** será el único servicio publicado: los puertos 8001 a 8003 se cierran en el grupo de seguridad y se abre solo el del gateway.
- Un **pipeline de GitHub Actions** desplegará con un rol de IAM asumido por OIDC, sin guardar claves de acceso.
- Se acotarán las direcciones que pueden llegar a la instancia (`app_allowed_cidr_blocks` hoy admite `0.0.0.0/0`).
