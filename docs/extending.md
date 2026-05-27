# Extending Nengok with your own agent

The bundled `sample_agent/` and `sample_agent/qa_agent/` packages exist so
the SDK has a working monitored agent out of the box. In production
you point Nengok at your own agent. This page is the short version of
how to do that.

## Plug in your own agent in three steps

1. Define a class that satisfies the `AgentRunner` Protocol from
   `nengok.runners.protocol`. The class needs a `name` property and a
   `run(agent_input: dict, prompt: str) -> dict` method. The
   `agent_input` mapping is one row from the Phoenix dataset the
   verifier built; the `prompt` is the candidate prompt the experiment
   is testing.
2. Set `agent_runner` in `~/.nengok/config.toml` to the dotted path of
   that class (`my_pkg.runner:MyAgent`). Optional constructor arguments
   go under `agent_runner_kwargs` as a TOML table.
3. Run `nengok doctor` to confirm the runner imports and passes the
   Protocol check. If it does not, the doctor prints the missing
   member (a `name` property or a `run` method with the right
   signature). Fix that and rerun.

After the doctor is green, `nengok run --project <your-project>` walks
the four-stage loop against your traces.

## Minimal 30-line example

The example below is the smallest viable runner. It targets a
hypothetical retrieval-augmented agent that exposes an `answer`
function elsewhere in the package.

```python
# my_pkg/runner.py
from typing import Any


class RagAgent:
    """Runner for an in-house retrieval-augmented agent."""

    def __init__(self, *, knowledge_base_url: str) -> None:
        self.knowledge_base_url = knowledge_base_url

    @property
    def name(self) -> str:
        return "rag-agent"

    def run(self, agent_input: dict[str, Any], prompt: str) -> dict[str, Any]:
        from my_pkg.agent import answer

        question = str(agent_input.get("question", ""))
        result = answer(
            question,
            system_prompt=prompt,
            knowledge_base_url=self.knowledge_base_url,
        )
        return {
            "question": question,
            "answer": result.text,
            "snippets": result.snippets,
        }
```

The matching config block:

```toml
[nengok]
project_identifier = "rag-agent"
agent_runner = "my_pkg.runner:RagAgent"
agent_runner_kwargs = { knowledge_base_url = "https://kb.internal/api" }
baseline_prompt_path = "my_pkg/prompts/system.md"
```

## Worked example: the bundled QA agent

`sample_agent/qa_agent/` is a complete worked example. The agent has
its own corpus, three injectable failure modes (`retriever`,
`hallucination`, `wrong_attribution`), a seed script, and a five-case
golden dataset under `golden_dataset/qa_golden.json`. The runner class
is `QAAgent` and the config that wires it up is
`examples/config-qa-agent.toml`. Copy from there as a starting
template.

## Plugging in a custom baseline-prompt source

The default loader walks the bundled sample-agent file, then Phoenix
prompt management, then `config.baseline_prompt_path`. Teams that keep
their prompt somewhere else (a private secrets store, or an internal
CMS) point `baseline_prompt_loader` at a factory function:

```toml
baseline_prompt_loader = "my_pkg.loaders:build_loader"
```

The factory takes `(config, phoenix)` and returns any object with a
`load(project_name: str) -> str | None` method. The
`nengok.core.fixer.loaders` module ships `FileLoader`,
`PhoenixPromptLoader`, and `CompositeLoader` so a custom factory can
reuse them.
