# CodeLab614 AI skills

[English](#english) | [Español](#espanol)

<a id="english"></a>

## English

A collection of agent skills, installable with the [`skills`](https://github.com/vercel-labs/skills) CLI.

### Skills

| Skill | What it does |
|---|---|
| `explain-changes` | Explains the changes on your current Git branch group by group (what they do, which project rules they touch, what is mechanical) and writes a report. Read-only. Usage guide: [docs/explain-changes.md](docs/explain-changes.md) |

### Install

```bash
npx skills add CodeLab614-AI/skills                          # interactive picker
npx skills add CodeLab614-AI/skills --skill explain-changes  # only this skill
npx skills add CodeLab614-AI/skills --list                   # list the skills, install nothing
npx skills add CodeLab614-AI/skills --all                    # install every skill
```

Only the folder `skills/<name>/` is installed. Tests, docs and CI stay in this repository.

### Requirements

- Git
- Python 3, version 3.9 or newer (standard library only, nothing to `pip install`)

### Use

Invoke the skill yourself (for example `/explain-changes`). It is meant to run only when you ask for it. See [docs/explain-changes.md](docs/explain-changes.md) for the flow, an example walkthrough and troubleshooting.

### Invocation lock per agent

Invocation lock per agent: to be verified. This table will say, agent by agent, whether the `disable-model-invocation` field is enforced or is only an instruction in the skill text.

### License

MIT, see [LICENSE](LICENSE).

---

<a id="espanol"></a>

## Español

Colección de skills para agentes, instalables con la CLI [`skills`](https://github.com/vercel-labs/skills).

### Skills

| Skill | Qué hace |
|---|---|
| `explain-changes` | Explica los cambios de tu rama de Git grupo por grupo (qué hacen, qué reglas del proyecto tocan, qué es mecánico) y escribe un reporte. Solo lectura. Guía de uso: [docs/explain-changes.md](docs/explain-changes.md) |

### Instalación

```bash
npx skills add CodeLab614-AI/skills                          # selector interactivo
npx skills add CodeLab614-AI/skills --skill explain-changes  # solo esta skill
npx skills add CodeLab614-AI/skills --list                   # lista las skills, no instala nada
npx skills add CodeLab614-AI/skills --all                    # instala todas las skills
```

Solo se instala la carpeta `skills/<nombre>/`. Las pruebas, la documentación y el CI se quedan en este repositorio.

### Requisitos

- Git
- Python 3, versión 3.9 o superior (solo biblioteca estándar, nada que instalar con `pip`)

### Uso

Invoca la skill tú mismo (por ejemplo `/explain-changes`). Está pensada para correr solo cuando tú la pides. En [docs/explain-changes.md](docs/explain-changes.md) están el flujo, un ejemplo del recorrido y la solución de problemas.

### Candado de invocación por agente

Candado de invocación por agente: por verificar. Esta tabla dirá, agente por agente, si el campo `disable-model-invocation` se respeta o es solo una indicación en el texto de la skill.

### Licencia

MIT, ver [LICENSE](LICENSE).
