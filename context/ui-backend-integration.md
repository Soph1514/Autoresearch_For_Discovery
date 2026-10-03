# UI/backend integration boundary

Current behavior and gaps live in [UI integration](../docs/ui-integration-status.md).
The [API/event contract](../docs/api-events.md) defines the evolution wire format;
[shared semantics](../docs/shared-semantics.md) and
[evolution design](../docs/evolution.md) define backend policy.

- The frontend owns problem entry, attachment review, graph layout, inspection and
  controls. Use the shared AntiAI paper theme across the workbench and demos.
- The backend owns model credentials, checking, generation, evaluation, ancestry,
  metrics and elite selection. Render supplied evidence rather than inferring it.
- Preparation uses attachment extraction and streamed formalization endpoints.
  Evolution uses explicit demo run creation, snapshots, ordered SSE and controls.
  Custom Lean-to-evolution orchestration remains outstanding.
- Preserve failed and inactive candidates, distinguish missing metrics from zero,
  recover event gaps from snapshots, and show acknowledged run states.
- Keep demo behavior explicit. Mock fixtures are not a runtime fallback, inspiration
  references are not parent edges, and crossover does not imply extra mutation.
