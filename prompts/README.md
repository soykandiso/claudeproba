# Prompts

One file per version: `prompts/<task>/<version>.md`, where the version is `yyyy-mm-dd.n`
(for example `prompts/extract_call/2026-09-20.1.md`). The task's current version is set in
`config/models.yaml`.

**A version file is immutable once it has run.** The gateway records each file's SHA-256 in
`prompt_version` the first time it is used, and refuses to run a file whose content no longer
matches. To change a prompt, copy it to a new version, edit the copy, point `config/models.yaml`
at it, and run the evaluation harness.

## Format

```markdown
Instructions for the model. This part is sent as the system prompt.

<!-- user -->
The part sent as the user message. Variables are written $like_this.
```

Everything before the `<!-- user -->` line is the system prompt; everything after it is the user
message. Both may use `$variables`, which the gateway fills from the caller's inputs **after
scrubbing identity data from them**. A variable the caller did not supply is an error, never an
empty string. Write a literal dollar sign as `$$`.
