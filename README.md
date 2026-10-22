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

| Agent | Lock or instruction | How the isolated interpreter is launched | Source |
|---|---|---|---|
| Claude Code | Lock: `disable-model-invocation: true` stops Claude from loading the skill on its own (also stops preloading into subagents). | Subagents: a skill can set `context: fork` plus `agent`, `model` and `effort` (for example `medium`). This skill does not set them; the flow asks for a subagent with a clean bundle. Not verified in a live run. | [Claude Code skills](https://code.claude.com/docs/en/skills) |
| Codex | Lock: `agents/openai.yaml` with `policy.allow_implicit_invocation: false` (included in this skill). Explicit `$explain-changes` still works. The frontmatter field is not documented by Codex. | Custom subagents (TOML in `.codex/agents/`) with `model_reasoning_effort`; Codex spawns them when the instructions ask for it. Not verified in a live run. | [Codex skills](https://learn.chatgpt.com/docs/build-skills), [subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents) |
| Cursor | Lock: `disable-model-invocation: true` (documented: the skill is only included when invoked with `/skill-name`). Not verified in a live run. | Subagents in `.cursor/agents/` with `model` (effort as `model[effort=...]`) and `readonly`. Not verified in a live run. | [Cursor skills](https://cursor.com/docs/context/skills), [subagents](https://cursor.com/docs/subagents) |
| OpenCode | Lock: not by frontmatter. `metadata: opencode/autoinvoke: "false"` hides it from model guidance, or `permission.skill` `deny`/`ask` in `opencode.json`. Neither is set by this skill; only the `description` is an instruction. Not verified. | Agents with `mode: subagent` and a model; effort only through provider options (`reasoningEffort`). Not verified in a live run. | [OpenCode skills](https://opencode.ai/docs/skills/), [agents](https://opencode.ai/docs/agents/) |
| Antigravity | No lock documented: only `name` and `description`; the agent decides by description. The skill text is the only instruction. | Subagents exist but their configuration is not verified. Not verified. | [Antigravity skills](https://antigravity.google/docs/skills) |

Docs were read on 2026-10-22; nothing was tested inside the installed agents yet. Where there is no lock, the skill still tells the agent to run only on explicit request.

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

| Agente | Candado o indicación | Cómo se lanza el intérprete aislado | Fuente |
|---|---|---|---|
| Claude Code | Candado: `disable-model-invocation: true` impide que Claude cargue la skill por su cuenta (y que se precargue en subagentes). | Subagentes: una skill puede fijar `context: fork` junto con `agent`, `model` y `effort` (por ejemplo `medium`). Esta skill no los fija; el flujo pide un subagente con un paquete limpio. No verificado en una ejecución real. | [Skills de Claude Code](https://code.claude.com/docs/en/skills) |
| Codex | Candado: `agents/openai.yaml` con `policy.allow_implicit_invocation: false` (incluido en esta skill). `$explain-changes` explícito sigue funcionando. El campo del frontmatter no está documentado por Codex. | Subagentes personalizados (TOML en `.codex/agents/`) con `model_reasoning_effort`; Codex los lanza cuando las instrucciones lo piden. No verificado en una ejecución real. | [Skills de Codex](https://learn.chatgpt.com/docs/build-skills), [subagentes](https://learn.chatgpt.com/docs/agent-configuration/subagents) |
| Cursor | Candado: `disable-model-invocation: true` (documentado: la skill solo se incluye si se invoca con `/nombre-de-skill`). No verificado en una ejecución real. | Subagentes en `.cursor/agents/` con `model` (esfuerzo como `model[effort=...]`) y `readonly`. No verificado en una ejecución real. | [Skills de Cursor](https://cursor.com/docs/context/skills), [subagentes](https://cursor.com/docs/subagents) |
| OpenCode | Candado: no por frontmatter. `metadata: opencode/autoinvoke: "false"` la oculta de la guía del modelo, o `permission.skill` `deny`/`ask` en `opencode.json`. Esta skill no fija ninguno; solo la `description` es una indicación. No verificado. | Agentes con `mode: subagent` y un modelo; el esfuerzo solo mediante opciones del proveedor (`reasoningEffort`). No verificado en una ejecución real. | [Skills de OpenCode](https://opencode.ai/docs/skills/), [agentes](https://opencode.ai/docs/agents/) |
| Antigravity | No hay candado documentado: solo `name` y `description`; el agente decide por la descripción. El texto de la skill es la única indicación. | Existen subagentes, pero su configuración no está verificada. No verificado. | [Skills de Antigravity](https://antigravity.google/docs/skills) |

La documentación se leyó el 2026-10-22; todavía no se probó nada dentro de los agentes instalados. Donde no hay candado, la skill igualmente indica al agente que corra solo si se le pide de forma explícita.

### Licencia

MIT, ver [LICENSE](LICENSE).
