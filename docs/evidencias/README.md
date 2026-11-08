# Evidencias del Hito 2

Pruebas de que lo descrito en [`hito2.md`](../hito2.md) funciona. Hay dos tipos: la **salida de terminal**, guardada como texto y reproducible con los comandos que aparecen en cada fichero, y las **páginas web guardadas como PDF** (GitHub, SonarCloud y Swagger), que no se pueden obtener desde la línea de órdenes.

| Evidencia | Qué demuestra | Requisito del enunciado |
|---|---|---|
| [`compose-ps.txt`](compose-ps.txt) | El sistema completo (cinco contenedores) arranca con un solo comando y todos están sanos; los servicios responden en `/health`; corren como `appuser` (UID 10001) y sin compilador en la imagen final; hay dos volúmenes y dos redes | Compose, volúmenes, redes, mínimo privilegio, multietapa |
| [`make-test.txt`](make-test.txt) | `make lint` y `make test` pasan: 220, 141 y 137 pruebas | Linters y pruebas unitarias y de integración |
| [`ci-runs.txt`](ci-runs.txt) | Cuatro ejecuciones reales de GitHub Actions (los workflows `CI` y `Docker`, en un push a `main` y en una pull request), con la URL de cada una, su commit, su resultado y la duración de cada trabajo | Eventos `push` y `pull_request`, linters, pruebas y construcción |
| [`ghcr.txt`](ghcr.txt) | Las tres imágenes están publicadas en GHCR, son públicas y se descargan sin iniciar sesión; llevan las etiquetas `latest` y `sha-<commit>`, incluida la del `main` actual | Publicación en GHCR con el hash del commit |
| [`ci-run.pdf`](ci-run.pdf) | Una ejecución del workflow `CI` sobre `main`: estado `Success` y los trabajos `Lint`, `Test` (uno por servicio) e `Integration Validation`, con su duración | Workflow de CI |
| [`docker-run.pdf`](docker-run.pdf) | Una ejecución del workflow `Docker` sobre `main`: análisis de los Dockerfiles con `hadolint` y construcción y publicación de las tres imágenes | Linter de Dockerfiles y construcción |
| [`ghcr-paquetes.pdf`](ghcr-paquetes.pdf) | Los tres paquetes en el perfil de GitHub. Que son públicos lo demuestra `ghcr.txt`, porque esta página no muestra la visibilidad | Publicación en GHCR |
| [`sonarcloud.pdf`](sonarcloud.pdf) | El análisis de SonarCloud: *Quality Gate* superado, calificación A en seguridad, fiabilidad y mantenibilidad, 0 *hotspots* y 0,0 % de duplicación (la cobertura no se mide) | Calidad del código |
| [`swagger-docs.pdf`](swagger-docs.pdf) | La documentación interactiva (`/docs`) de `document-service` en funcionamiento, con todos sus endpoints | Servicio levantado en local |

## Cómo se han obtenido

- **Salida de terminal.** Los ficheros `.txt` son la salida real de los comandos que indican, sobre el commit de `main` que figura en su primera línea. `ci-runs.txt` sale de la API de GitHub (`gh run list` y `gh run view`) y cada ejecución lleva su URL para comprobarla.
  - `make` no está instalado en el Windows de desarrollo, así que `make-test.txt` se generó en un contenedor `python:3.12` con una PostgreSQL 17 y una Redis 7 desechables. El CI ejecuta los mismos objetivos en `ubuntu-24.04`.
  - `ghcr.txt` se consultó sin credenciales: la comprobación anónima es lo que demuestra que los paquetes son públicos.
- **Páginas web en PDF.** Las de GitHub, SonarCloud y Swagger se guardan desde el navegador (imprimir y guardar como PDF). Conservan el texto y los números, y llevan la fecha y la URL en el pie; el de GitHub, además, el commit en el título. Se enlazan y no se incrustan, porque Markdown no muestra PDFs.
- **Los 7 *issues* de SonarCloud.** El panel muestra "Issues: 7", pero los siete están marcados como *Accepted*: la instalación de dependencias sin versiones bloqueadas con *hashes* en los Dockerfiles y en `ci.yml` (regla `S8544`) y la instalación sin `--only-binary` en `ci.yml` (`S8541`). Es una limitación conocida y documentada en [`docker.md`](../docker.md). No hay ningún *issue* abierto.
