# Evidencias del Hito 3

Pruebas del experimento del patrón *Reconciler* y del apagado de la infraestructura, descritos en el [`README.md`](../../../README.md#verificación-del-patrón-reconciler) del proyecto. Hay dos tipos: la **salida de terminal**, guardada como texto, y las **capturas de la consola de AWS**, que no se pueden obtener desde la línea de órdenes.

Todas las evidencias son del mismo ciclo: un `terraform apply`, un cambio manual en la consola, su detección, su corrección y un `terraform destroy`, con la infraestructura de [`despliegue.md`](../../despliegue.md).

| Fase | Evidencia | Qué demuestra |
|---|---|---|
| 1. Estado deseado | `01-apply.txt` | `terraform apply` crea los 22 recursos |
| 1. Estado deseado | `02-consola-antes.pdf` | La regla del puerto 8002 en el grupo de seguridad, tal como la define el código |
| 2. Deriva | `03-consola-cambio.pdf` | La regla borrada a mano en la consola de AWS |
| 2. Deriva | `04-health-roto.txt` | El servicio del puerto 8002 deja de responder desde fuera (`HTTP 000`), mientras los otros dos siguen respondiendo (`HTTP 200`) |
| 3. Observación | `05-plan-deriva.txt` | `terraform plan` avisa de que la regla no existe en AWS (*AWS resource not found during refresh*) y propone crearla (`1 to add`) |
| 4. Reconciliación | `06-apply-reconcilia.txt` | `terraform apply` crea de nuevo la regla, y `/health` del puerto 8002 vuelve a responder |
| 4. Reconciliación | `07-plan-limpio.txt` | Un `terraform plan` posterior no propone ningún cambio (`No changes`) |
| Apagado | `08-destroy.txt` | `terraform destroy` elimina los 22 recursos |
| Apagado | `09-sin-recursos.txt` | Ninguna instancia en ejecución (la única que figura está `terminated`) y ningún volumen, VPC ni grupo de seguridad con la etiqueta del proyecto; el rol de IAM y el parámetro de Parameter Store ya no existen |
| Apagado | `10-consola-ec2-vacia.pdf` | El panel de EC2 en Estocolmo: 0 instancias en ejecución y 0 volúmenes. Queda un grupo de seguridad, el de la VPC por defecto de la región |
| Apagado | `10-consola-vpc-vacia.pdf` | La lista de VPC: solo queda la VPC predeterminada de la región; la del proyecto (`10.0.0.0/16`) ya no existe |

## Cómo se han obtenido

- **Salida de terminal.** Los ficheros `.txt` son la salida real de cada comando, guardada en UTF-8 (con `Tee-Object -Variable` y `Add-Content`, porque `Tee-Object -FilePath` escribe en UTF-16 en Windows PowerShell 5.1). Cada uno empieza con la fecha y el comando que lo generó. En `05-plan-deriva.txt` se corrigió una línea separadora que la consola de Windows había codificado mal; el contenido es el original.
- **Capturas.** Se guardan desde la consola de AWS, en la región `eu-north-1` (Estocolmo), como PDF (imprimir y guardar como PDF), igual que las del Hito 2. Llevan la fecha y la URL en el pie.
- **Qué se cambia a mano.** Se borra la regla de entrada del puerto 8002 del grupo de seguridad `verifactu-trace-compute`. Se elige esta porque su efecto se ve desde fuera: el servicio deja de responder, y vuelve a hacerlo cuando Terraform la restaura.
- **Que no queda nada.** Se consulta directamente a EC2 con la etiqueta `Project=verifactu-trace` (`describe-instances`, `describe-volumes`, `describe-vpcs` y `describe-security-groups`), y a IAM y Parameter Store con `aws iam get-role` y `aws ssm get-parameter`, que fallan con *NoSuchEntity* y *ParameterNotFound*. No se usó `resourcegroupstaggingapi get-resources`: esa API se actualiza con retraso y siguió listando recursos ya borrados, entre ellos la VPC y los grupos de seguridad que `describe-*` confirma que no existen. Una instancia terminada se sigue listando durante aproximadamente una hora, sin coste.
