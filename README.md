# Skill Scout

Skill Scout finds and compares existing agent skills for a concrete workflow. It
prefers contextual fit, demonstrated behavior, safety, and maintenance evidence
over popularity. A valid result can be that no candidate qualifies.

The skill is intentionally research-only: discovering or recommending a skill
does not authorize installation, configuration, publishing, or execution of
candidate code.

## Install

### Skills CLI (recommended)

Install to the five primary targets:

```sh
npx skills add jon-devlapaz/skill-scout --skill skill-scout \
  --agent codex cursor claude-code hermes-agent pi -g -y --copy
```

The same installer also recognizes other Agent Skills harnesses. Add targets
such as `gemini-cli`, `github-copilot`, or `opencode` to the `--agent` list.

> [!IMPORTANT]
> Hermes's community registry currently contains an unrelated skill also named
> `skill-scout`. Use the repository-specific command above or the manual copy
> below; `hermes skills install skill-scout` selects that other package.

### Manual installation

Clone the repository, then copy or symlink `skills/skill-scout` into the skill
directory used by your agent:

| Agent | Personal skill directory |
| --- | --- |
| Codex | `~/.agents/skills/skill-scout` |
| Cursor | `~/.cursor/skills/skill-scout` |
| Claude Code | `~/.claude/skills/skill-scout` |
| Hermes Agent | `~/.hermes/skills/skill-scout` |
| Pi | `~/.pi/agent/skills/skill-scout` or `~/.agents/skills/skill-scout` |

For a project-local install, use the corresponding project skill directory,
such as `.agents/skills`, `.cursor/skills`, `.claude/skills`, or `.pi/skills`.

Pi can also install this repository as a package:

```sh
pi install git:github.com/jon-devlapaz/skill-scout@v1.0.0
```

## Use

Ask your agent to use `skill-scout` to discover, verify, or compare skills for a
specific recurring workflow. Explicit invocation varies by harness; examples
include `$skill-scout`, `/skill-scout`, or `/skill:skill-scout`.

Example prompts:

```text
Use skill-scout to find a maintained skill for reviewing database migrations.
Compare these two supplied skills without searching for additional candidates.
Verify whether this skill repository is safe and compatible with my agent.
```

## Compatibility

The package follows the open [Agent Skills specification](https://agentskills.io/specification):
one `SKILL.md` plus relative references and optional metadata. The same package
shape is documented by [Codex](https://learn.chatgpt.com/docs/build-skills),
[Claude Code](https://code.claude.com/docs/en/skills),
[Hermes Agent](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/guides/work-with-skills.md),
and [Pi](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/skills.md).
Cursor supports Agent Skills in its editor and CLI as of
[Cursor 2.4](https://www.cursor.com/changelog/2-4).

`agents/openai.yaml` adds optional Codex UI metadata. Other harnesses can ignore
it; the portable instructions remain in `SKILL.md`.

Compatibility here means the skill can be discovered and its instructions and
relative references can be loaded. Tool availability still varies by harness,
so Skill Scout tells the agent to use available local and public sources rather
than depending on one vendor-specific tool.

## Repository layout

```text
skills/skill-scout/
├── SKILL.md
├── agents/openai.yaml
├── references/scouting-workflow.md
└── evals/
```

## License

[MIT](LICENSE)
