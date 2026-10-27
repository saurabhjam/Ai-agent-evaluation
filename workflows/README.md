# Workflow Catalog

Place workflow definitions here, outside executable `scenarios/` discovery.
No existing scenario is automatically mapped or classified.

```yaml
workflow_id: example_workflow
name: Example Workflow
description: Describe the capability under test.
coverage: {positive: 3, negative: 3, edge: 2}
agent_keys: ["chatbot:example-connection-id"]
```

Only explicit canonical management `agent_keys` associate unrun authored cases
with an agent; their channel must also match. An empty list leaves the workflow
in the global catalog without attaching it to every agent. Legacy/unmapped cases
are associated only through that agent's selected qualifying evaluation history,
never filenames or prefixes. Each independent scenario
opts in with `test_case: {workflow_id: example_workflow, type: positive, version: "1"}`.
Its `scenario_id` remains its sole executable test-case identity.

Coverage counts distinct valid authored cases, not evaluation runs. Missing cases
are warnings and never block a structurally valid individual execution. Duplicate
IDs are excluded from authored coverage and surfaced as catalog issues.
