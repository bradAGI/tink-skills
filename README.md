# Skill Scout and Skill Eval Loop

This repo contains two agent skills.

`skill-scout` helps you find a skill for a specific job, compare the candidates,
and check whether any of them are worth installing. It cares more about fit,
working examples, safety, and maintenance than stars. Sometimes the honest
answer is that none of the candidates are good enough.

`skill-eval-loop` tests one skill against a no-skill control on your own
computer. It keeps the prompt, model, tools, and trial settings fixed, then
changes whether the agent can load the skill. The result is a local diagnostic,
not proof that the skill will work everywhere.

Skill Scout only researches and recommends. It will not install a candidate,
change your configuration, publish anything, or run code from a candidate
without separate permission.

## Install

### Skills CLI

Install either skill with the [Skills CLI](https://skills.sh/):

```sh
npx skills add jon-devlapaz/skill-scout --skill skill-scout \
  --agent codex cursor claude-code hermes-agent pi -g -y --copy

npx skills add jon-devlapaz/skill-scout --skill skill-eval-loop \
  --agent codex cursor claude-code hermes-agent pi -g -y --copy
```

You can add other compatible agents, including `gemini-cli`, `github-copilot`,
and `opencode`, to the `--agent` list.

> [!IMPORTANT]
> The Hermes community registry has a different package named `skill-scout`.
> Use the repository command above or install this copy manually. Running
> `hermes skills install skill-scout` installs the other package.

### Manual install

Clone this repository and copy or symlink the skill you want into your agent's
personal skill directory:

| Agent | Personal skill directory |
| --- | --- |
| Codex | `~/.agents/skills/<skill-name>` |
| Cursor | `~/.cursor/skills/<skill-name>` |
| Claude Code | `~/.claude/skills/<skill-name>` |
| Hermes Agent | `~/.hermes/skills/<skill-name>` |
| Pi | `~/.pi/agent/skills/<skill-name>` or `~/.agents/skills/<skill-name>` |

For a project-only install, use the matching directory inside the project,
such as `.agents/skills`, `.cursor/skills`, `.claude/skills`, or `.pi/skills`.

Pi can also install the repository as a package:

```sh
pi install git:github.com/jon-devlapaz/skill-scout
```

## Use Skill Scout

Ask your agent to use `skill-scout` for a recurring job you want help with.
Depending on the agent, explicit invocation may look like `$skill-scout`,
`/skill-scout`, or `/skill:skill-scout`.

```text
Use skill-scout to find a maintained skill for reviewing database migrations.
Compare these two supplied skills without searching for more candidates.
Check whether this skill repository is safe and compatible with my agent.
```

## Use Skill Eval Loop

Use `skill-eval-loop` when you have a skill and want to see whether it changes
the result. If the skill has no eval suite, a fresh subagent writes one without
sharing its hidden cases with the coordinating chat. That separation makes it
harder to teach the agent to pass the test by accident.

The workflow asks one question at a time. First it asks which harness to use:
Hermes, Claude Code, Codex, or Pi. It then checks the models available through
that harness and suggests a budget, balanced, or quality option. You confirm
the exact model before anything runs.

The first run is a single paired trial. You can watch it headlessly or through
Herdr. The dry run is free and creates no artifacts. Before a live run, the
skill shows the target calls, judge calls, and total paid calls, then waits for
your approval. Model graders can add calls quickly, so this check is worth
reading.

```text
Use skill-eval-loop to test this skill against a no-skill control.
Run a quick diagnostic of this skill with Codex.
Test whether this skill works across the available Pi model tiers.
```

## What works where

Each skill follows the open [Agent Skills specification](https://agentskills.io/specification):
a `SKILL.md` file, relative references, and optional metadata.
[Codex](https://learn.chatgpt.com/docs/build-skills),
[Claude Code](https://code.claude.com/docs/en/skills),
[Hermes Agent](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/guides/work-with-skills.md),
and [Pi](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/skills.md)
all use this package shape. [Cursor](https://www.cursor.com/changelog/2-4)
supports Agent Skills in its editor and CLI.

The `agents/openai.yaml` files add Codex UI metadata. Other agents can ignore
them. Tool access still differs between agents, so compatibility means the
agent can find and read the skill. It does not mean every optional integration
is installed.

## Repository layout

```text
skills/skill-scout/
├── SKILL.md
├── agents/openai.yaml
├── references/scouting-workflow.md
└── evals/

skills/skill-eval-loop/
├── SKILL.md
├── agents/openai.yaml
├── references/
├── scripts/
└── tests/
```

## License

[MIT](LICENSE)
