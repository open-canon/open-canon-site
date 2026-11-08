# Agent instructions

Shared skills for every coding agent (Claude Code, Codex, Copilot) live in
`.agents/skills/`. `.claude/skills` and `.github/skills` are symlinks to it, so add
or edit skills only under `.agents/skills/`.

- **`osis-text-triage`**: whenever an XML file in `open-canon-osis-documents/` is
  added or changed (including by regenerating it with a scraper), render it and
  triage oddities in the text before committing. Preserve the original text; fix
  scraping bugs in the scraper, never by hand-editing the XML. See
  `.agents/skills/osis-text-triage/SKILL.md`.

Commit messages follow Conventional Commits; see `CONTRIBUTING.md`.
