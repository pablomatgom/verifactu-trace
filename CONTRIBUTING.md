# Guía de contribución

Este documento recoge el flujo de trabajo del repositorio tal como la estrategia de ramas y la convención de commits.

> **Idioma:** los nombres de las ramas y los mensajes de commit se escribiran siempre **en inglés**, aunque la documentación del proyecto (README, hitos) se mantenga en español.

## Estrategia de ramas

El proyecto sigue un flujo basado en *feature branches*:

- `main`: rama estable. No se trabaja directamente sobre ella por lo que los cambios llegan mediante *pull request*.
- Ramas de trabajo, una por issue, creadas a partir de `main`. El nombre va en inglés, en minúsculas y con guiones:

| Prefijo | Uso | Ejemplo |
|---|---|---|
| `feature/` | Nueva funcionalidad | `feature/invoice-service` |
| `fix/` | Corrección de errores | `fix/chained-hash` |
| `docs/` | Documentación | `docs/contributing` |
| `refactor/` | Reestructuración sin cambio de comportamiento | `refactor/api-layer` |

### Flujo de trabajo

1. Crear o elegir un issue.
2. Crear la rama desde `main` actualizada:
   ```bash
   git switch main
   git pull
   git switch -c docs/contributing
   ```
3. Hacer commits pequeños, cada uno con una sola tarea y comprobando funcionalidad.
4. Subir la rama y abrir un *pull request* hacia `main` usando la plantilla, indicando `closes #n`.
5. Tras integrar el PR, borrar la rama.

## Convención de commits

Se usa [Conventional Commits](https://www.conventionalcommits.org). El mensaje se escribe en inglés:

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

### Tipos

| Tipo | Cuándo usarlo |
|---|---|
| `feat` | Nueva funcionalidad |
| `fix` | Corrección de un error |
| `docs` | Cambios solo de documentación |
| `refactor` | Cambio de código sin alterar el comportamiento |
| `test` | Añadir o modificar tests |
| `chore` | Tareas de mantenimiento (configuración, dependencias) |

### Reglas

- Los mensajes de commit y los nombres de rama se escriben en inglés.
- Descripción breve, en imperativo, en minúscula y sin punto al final.
- Un commit corresponde a una tarea concreta y debe dejar el proyecto en un estado correcto.
- Cada commit se relaciona con un issue. Para cerrarlo se incluye `closes #n` mientras que para solo referenciarlo, `#n`.

### Ejemplos

```
docs: add branching strategy and commit convention (closes #1)
feat(invoice): compute the chained hash of each invoice
fix(validation): reject invoices with a negative tax base
refactor(api): separate routes from business logic
```
