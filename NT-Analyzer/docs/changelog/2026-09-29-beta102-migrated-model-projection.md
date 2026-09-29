# beta.102 — migrated owner models in AI Center

Release title: beta.102 migrated server-model projection.
Release summary: Show the five already-migrated owner Model connections under “Мои модели” when the legacy Lab registry is empty; no model, key or sharing data changes.
Release PRs: #305.
Affected subsystems: AI Center model roster projection and UI regression tests.
Release impact: new beta.102 source and, only after owner-authorized merge and final-main CI, a new signed immutable artifact and fresh Canary acceptance. beta.101 artifact is not modified.

- Existing migrated owner models appear in the main model roster instead of only under additional connections.
- ProviderAccount, Model, encrypted secrets and share descriptors remain unchanged.
- The owner can test an existing connection without entering its key again.

Change summary: the current owner-approved beta.96 product package remains open. Immutable beta.101 is on Canary with partial acceptance. Its owner Model records and server-encrypted provider credentials imported correctly, but an empty legacy Lab registry incorrectly won the AI Center presentation branch, leaving “Мои модели” empty and placing the imported records only in “Мои дополнительные подключения”. beta.102 changes only that presentation choice and its regression coverage; it neither creates nor rewrites a ProviderAccount, Model, key or share binding.

Source: [PR #305](https://github.com/OMNOM-111/NT-Analyzer/pull/305), branch `codex/beta102-migrated-model-projection`, application change `78e51078` based on final beta.101 `main` SHA `58fbb23d1551e267dd7fe622c2414580820f3f8c`. The branch also carries the two unmerged, unchanged beta.101 Canary evidence commits from PR #304, so no separate evidence is lost. Final merge SHA, CI and artifact identity are pending. This version must first pass Development/CI and the normal signed-artifact → Canary sequence; beta.101 must not be rebuilt or patched in place. Production remains beta.99. Production scheduler OFF and Local `StratForge Vitek` ON.

Canary diagnostic evidence before code change: owner-scoped read found five imported Models, five decryptable `ServerSecrets`, four active and one retired Model, and two share descriptors; non-owner RLS could read only the two secret-free descriptors and no owner Model/key. The owner UI's separate “Доступные общие модели” panel shows models shared *by other users*, so it is expected to be empty for this owner if nobody shares with them. The first short test of the existing DeepSeek connection, Model `9a3b3c33-7d75-500b-9f6e-82fcbec3381e`, produced provider-origin task `9ac80f21-6943-5fa3-90b1-a4d492a9ac55` with `real_model_response`, persisted cost and `provider_verified` / `connected=true`. No key was re-entered, printed or sent to a browser; no connection was duplicated. At that checkpoint only one provider route was verified; the subsequent tests below cover all active connections, not the non-owner shared route.

Follow-up on all five existing records: all four **active** connections passed an actual provider `connection_exact` request with provider-origin receipt and measured cost, and now project `connected=true` / `provider_verified`. The separate bounded DeepSeek `json_arithmetic` task `55ef2eb7-5ea5-516a-844e-0b5e67dec8e6` also succeeded as an ordinary provider invocation. The fifth GLM/Z.AI record was already `retired` in the Local source; it was preserved for history with its account and encrypted secret but correctly has no test/task action and was not reactivated. There were no new ProviderAccounts or Models, and no key re-entry. This maintenance-service execution proves the server transport and vault, not the owner browser admission or non-owner shared call.

| Connection / preserved Local registry ID | Canary ProviderAccount → Model | Explicit outbound share | Canary result |
| --- | --- | --- | --- |
| GPT 5 Mini / `AGT-14C850458EDC` | `9d7c3e73-3cb3-5507-ba6f-b6bb6b9331e3` → `bd80b782-1c31-5036-bd9b-1808fe994599` | off | active, provider verified |
| DeepSeek V4 Flash / `AGT-1503FE01CC55` | `16db720e-86c9-57c4-af4a-672bef9cd1a2` → `9a3b3c33-7d75-500b-9f6e-82fcbec3381e` | off | active, provider verified; ordinary invocation PASS |
| Gemini 2.5 Flash / `AGT-B1C26A936A18` | `02aa2e99-68d7-581e-a52e-6a77f6b14126` → `0a476279-1a62-591a-bdaa-8d96f96ac5dc` | on | active, provider verified |
| Gemini 2.5 Flash / `AGT-9CD0BBB0BA0C` | `42b15eca-a293-5013-9c1c-1e6350b51b9f` → `9c65612d-33a7-52e4-a96c-bc91ee8ff50b` | on | active, provider verified |
| GLM 4.7 Flash / `AGT-161642FB14B6` | `569dcb1c-f087-5cfd-8cc8-cd8b9b19e05d` → `6fdf98cd-807d-5764-baea-43777cdcaf1c` | off | retired, intentionally not callable |

`local_registry_id` is provenance retained on the imported Model profile. `existing_registry_id` is intentionally absent in the server profile: Linux must not resolve a Local DPAPI registry binding. The same original Model ID is the live share binding for the two Gemini connections. A successful first use updates `connected` and usage, not the separate legacy Lab catalogue; hence the UI projection fix is required.

Development verification: the AI Center regression exercises an empty Lab registry with an existing workspace Model and confirms it renders under “Мои модели”, not “Мои дополнительные подключения”, with no POST. Full UI test module: 207 PASS. Node syntax, bundle pre-release, context validation, required CI and Canary acceptance remain separate gates until recorded below. Owner's previous Local product approval is 7/7 and is not being repeated.

Remaining Canary checks: all active imported connections' testability, owner UI test, restart persistence, real non-owner shared invocation and usage/cost/audit, share-off, private model isolation, new-user BYOK, and the rest of the frozen beta.96 server-parity package. No Production promotion before full Canary PASS and artifact-specific owner approval.
