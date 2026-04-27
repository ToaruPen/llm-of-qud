# ADR Decision Record

timestamp: 2026-04-27T00:11:30Z
change: PR-G2 Devin follow-up: HeuristicPolicy [Serializable] for save/load compatibility
adr_required: false
rationale: Devin AI review (BUG severity) flagged that HeuristicPolicy lacks `[Serializable]` while LLMOfQudSystem (decompiled XRL/IGameSystem.cs:11 `[Serializable]`) holds an `IDecisionPolicy` `_policy` instance field. .NET binary serializer would throw SerializationException on save. Verified pattern at decompiled/XRL/CheckpointingSystem.cs:13 (`[Serializable]` system + `[NonSerialized]` for opt-out fields). Added `[Serializable]` attribute to HeuristicPolicy — stateless class, serialization is effectively a no-op. Phase 0-F memo Open Hazards already noted save/load was untested in Phase 0-G; this is a defensive fix that closes the latent bug class without behavioral change.
files:
  - mod/LLMOfQud/HeuristicPolicy.cs
adr_paths: []
