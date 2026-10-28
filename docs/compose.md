# Entorno local con Docker Compose

El fichero [`compose.yaml`](../compose.yaml) levanta todo el sistema en local con un único comando: los tres microservicios, PostgreSQL y Redis.

## Puesta en marcha

```bash
cp .env.example .env        # en Windows (PowerShell): Copy-Item .env.example .env
docker compose up --build
```

El fichero `.env` contiene las credenciales de PostgreSQL. Está excluido de Git, y `.env.example` solo lleva valores de ejemplo. Si falta `.env`, Compose se detiene con un mensaje que indica qué variable falta.

Una vez arrancado:

| Servicio | URL | Comprobación de salud |
|---|---|---|
| `document-service` | http://localhost:8001 | http://localhost:8001/health |
| `traceability-service` | http://localhost:8002 | http://localhost:8002/health |
| `submission-service` | http://localhost:8003 | http://localhost:8003/health |

PostgreSQL y Redis no se publican en el equipo anfitrión por lo que son solo accesibles desde los demás contenedores.

## Comandos útiles

```bash
docker compose ps                       # estado y salud de cada contenedor
docker compose logs -f document-service # logs de un servicio
docker compose down                     # detiene y elimina los contenedores, conserva los datos
docker compose down -v                  # además elimina los volúmenes (borra los datos y reinicia la BD)
docker compose exec postgres psql -U verifactu -d verifactu   # consola de PostgreSQL
```

## Componentes

| Contenedor | Imagen | Función |
|---|---|---|
| `postgres` | `postgres:17-alpine` | Base de datos, con un esquema por servicio |
| `redis` | `redis:7-alpine` | Cola de eventos entre servicios |
| `document-service` | construida desde `services/document-service` | Pedidos, albaranes y facturas |
| `traceability-service` | construida desde `services/traceability-service` | Cadena de hashes y auditoría |
| `submission-service` | construida desde `services/submission-service` | Envío a la AEAT simulada |

## Decisiones de diseño

| Decisión | Elección | Motivo |
|---|---|---|
| Redes | `edge` para los servicios y `data` para PostgreSQL y Redis | Aísla los almacenes de datos: solo los servicios los alcanzan |
| Red de datos | `internal: true` | PostgreSQL y Redis no son accesibles desde el exterior ni tienen salida a internet |
| Puertos publicados | `127.0.0.1:<puerto>` | Los servicios solo son accesibles desde el propio equipo y no desde la red local (por ejemplo, la wifi de la universidad). Sin el prefijo, Docker publica en `0.0.0.0`, y en Windows esa publicación no pasa por el cortafuegos |
| Persistencia de PostgreSQL | Volumen `postgres-data` | Los datos sobreviven a reiniciar o recrear los contenedores |
| Persistencia de Redis | Volumen `redis-data` y `--appendonly yes` | Los eventos pendientes no se pierden si Redis se reinicia |
| Orden de arranque | `depends_on` con `condition: service_healthy` | Los servicios solo arrancan cuando PostgreSQL y Redis responden, y no basta con que sus contenedores existan |
| Comprobación de salud | `pg_isready` y `redis-cli ping` | Es lo que usa `depends_on` para saber que están listos. Los servicios usan el `HEALTHCHECK` de su Dockerfile |
| Configuración | Variables de entorno desde `.env` | Las credenciales no se escriben en el repositorio y se pueden cambiar sin tocar `compose.yaml` |
| Variables obligatorias | `${VARIABLE:?mensaje}` | Si falta una, Compose falla con un mensaje claro en lugar de arrancar con una contraseña vacía |
| Reinicio | `restart: unless-stopped` | Los contenedores se recuperan de un fallo y no se reinician si los detienes a mano |

## Esquemas de PostgreSQL

Una única instancia de PostgreSQL aloja un esquema por servicio (`documents`, `traceability` y `submissions`). Los crea el script [`db/init/01-schemas.sql`](../db/init/01-schemas.sql), que PostgreSQL ejecuta **solo la primera vez**, cuando el volumen de datos está vacío. Si modificas el script y no ves ningún cambio, es porque el volumen `postgres-data` ya contiene datos y PostgreSQL no vuelve a ejecutarlo. Para forzarlo hay que eliminar el volumen con `docker compose down -v`, lo que **borra los datos** de la base de datos.

Cada servicio recibe en sus variables de entorno la URL de conexión (`DATABASE_URL`), su esquema (`DATABASE_SCHEMA`) y la URL de Redis (`REDIS_URL`). De momento solo `document-service` las utiliza, y aplica sus migraciones al arrancar (ver [`database.md`](database.md)). Los otros dos las recibirán cuando necesiten base de datos.

Si la contraseña de `.env` contiene caracteres especiales, deben codificarse como URL en `DATABASE_URL`.

## Limitaciones conocidas

- **Un único usuario de PostgreSQL.** Los tres servicios se conectan con el mismo usuario, que puede leer y escribir en todos los esquemas. La separación por esquemas es una convención y no una restricción. Crear un rol por servicio con permisos solo sobre su esquema se aborda en el hito de secretos e IAM.
- **Redis sin contraseña.** Solo es accesible desde la red `data`, que es interna, pero cualquier contenedor conectado a ella puede leer y escribir en las colas.
- **Credenciales en claro en `.env`.** Es válido para desarrollo local. En la nube se sustituirán por un gestor de secrets.

## Consejos

- `docker compose config` muestra el fichero con las variables ya sustituidas, **incluida la contraseña**, cuidado con compartirlo.
- Todos los comandos de Compose, incluido `docker compose down`, necesitan que exista `.env`, porque las variables se resuelven antes de ejecutar nada.
- Si se actualiza PostgreSQL a la versión 18 o superior, cambia la ruta de datos del contenedor (`/var/lib/postgresql`), y hay que ajustar el volumen.
