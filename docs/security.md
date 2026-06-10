# Security model

This is a stub. The full document lands later. For now it covers the
PII redactor that runs before any span text leaves the local process.

## What the redactor does

`Redactor` (in [`nengok/core/observer/redactor.py`](../nengok/core/observer/redactor.py))
applies an ordered list of regex substitutions to every input value,
output value, exemplar body, and RCA excerpt before either Gemini or
the on-disk artifact bundle sees it. The default rule set covers:

- Email addresses
- Google API keys (`AIza…`) and AWS access keys (`AKIA…`)
- Bearer tokens inside `Authorization:` headers
- `password=…` and `secret=…` form fields
- 16-digit credit card patterns
- US-style SSNs (`NNN-NN-NNNN`)
- US phone numbers
- IPv4 and IPv6 addresses

Redaction runs everywhere span text leaves the local process: the
clusterer prompt, the hypothesizer exemplar block, the prompt proposer
exemplar block, and the RCA bundle written under `artifacts/`.

## What the redactor does not catch

Regex is a blunt tool. The defaults will miss anything that does not
match a literal pattern: handwritten free-form addresses, non-US phone
formats, names, dates of birth, internal customer ids, JWTs with
non-bearer prefixes, hashed identifiers, base64 blobs that happen to
contain PII, and anything in a language or encoding the patterns were
not written for. The redactor is best-effort defense in depth; it is
not a SOC2 control and it is not a substitute for a proper data loss
prevention pipeline.

## Configuration

`config.redaction_enabled` defaults to `true`. Set it to `false` only
when you have a stricter scrubber upstream and you are sure Gemini and
the local artifact tree can hold raw span text. The CLI logs a single
INFO line at startup that names the current redaction state.

`config.redaction_rules` accepts a list of `{name, pattern, replacement}`
tables in `~/.nengok/config.toml` so a team can add organisation-specific
identifiers (employee ids, internal urls, tenant ids).

`config.redaction_default_rules` accepts a list of default rule names
to enable. Leaving it unset keeps every default rule on. Set it to
`["email", "credit_card"]` to keep only those two and drop the rest.

`config.redactor_callable = "mycorp.scrubbers:enterprise_scrubber"`
fully replaces the bundled redactor with a dotted-path callable that
takes a `str` and returns a `str`. Use this when you already have a
hardened in-house scrubber and want the SDK to defer to it.

## The triage agent's credential surface

The ADK triage agent ([docs/agent-builder.md](agent-builder.md)) inherits
the existing Phoenix API key surface; it introduces no new credential
boundary. The `McpToolset` passes the key to the Phoenix MCP subprocess
through environment variables, the same channel the preflight check
already uses, so the key stays out of process argument lists. Span text
the agent reads through MCP stays between Phoenix and the local process;
only the agent's own tool-call reasoning reaches Gemini.

## What you should do before production

Run the redactor against a representative sample of your own traces
and check the output by hand. Pay attention to:

- Free-form fields where users paste data that does not match any rule.
- Tool inputs that pack PII into JSON keys (the default rules look at
  values; structured keys are not visited).
- Long opaque tokens (signed urls, OAuth refresh tokens) that do not
  match the bearer or API-key rules.

If anything slips through, add a rule under `redaction_rules` in
`~/.nengok/config.toml` or set `redactor_callable` to a function you
own and trust. The redactor is the last line of defense before span
text reaches an external API; treat its rule list as something you
maintain alongside the agents you monitor.
