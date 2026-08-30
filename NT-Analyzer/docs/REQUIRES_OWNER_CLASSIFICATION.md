# REQUIRES_OWNER_CLASSIFICATION


Files that were **not** relocated during the Phase 10B documentation move because
their canonical destination or content resolution needs an explicit owner
decision. All unambiguous files were moved (see `docs/DOCS_STRUCTURE.md`); these
remain at their current path until the owner decides.

| File | Current path | Why it needs owner classification |
|---|---|---|
| `AGENT_PERSONAS.md` | `docs/AGENT_PERSONAS.md` | Has **uncommitted local modifications** (stray dirty working-tree file). Moving or editing it would fold the owner's in-progress changes into an unrelated commit, which the workspace rules forbid. Move to `docs/agents/` after the owner commits or discards its pending changes. |
| `VITEK.md` | `docs/VITEK.md` | Referenced as a sibling (`[VITEK.md](VITEK.md)`) by the dirty `docs/AGENT_PERSONAS.md`, which cannot be edited. Moving it would break that link and fail the committed-tree markdown scan. Move to `docs/agents/` together with `AGENT_PERSONAS.md`. |
| `AI_DIALOGUE_CONTRACT.md` | `docs/AI_DIALOGUE_CONTRACT.md` | Same as `VITEK.md`: referenced as a sibling by the dirty `AGENT_PERSONAS.md`. Move to `docs/agents/` together with it. |
| `repository-hygiene.md` | `docs/repository-hygiene.md` **and** `docs/operations/repository-hygiene.md` | **Two files with the same name but divergent content** (different SHA-256). The owner must decide which version is canonical (or merge them) before the root duplicate is removed; a blind delete would lose content. |

Everything else under `docs/` was moved to its canonical directory per the
migration map, with all inbound links updated in the same change.
