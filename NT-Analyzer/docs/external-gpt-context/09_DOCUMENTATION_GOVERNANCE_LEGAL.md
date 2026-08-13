# 09. Documentation, Governance and Legal

- Context Pack document: 09_DOCUMENTATION_GOVERNANCE_LEGAL.md
- Last verified UTC: 2026-08-13T09:49:37Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Scope: Docs source-of-truth model, revision rules, localization policy and legal status
- Status: DONE

## Canonical documentation structure

The docs tree is intentionally partitioned into `current`, `architecture`,
`operations`, `security`, `product`, `agents`, `strategies`, `governance`,
`changelog`, `adr`, `archive`, `schemas`, `legal` and this compact
`external-gpt-context` upload set.

## Governance model

- Editable governance source of truth lives in `data/governance/*`.
- `docs/governance/*` is the rendered human-facing layer, not the editable source.
- Global governance is a separate control plane from workspace/strategy docs.
- Workspace or strategy document revisions must never mutate global governance or
  safety limits.

## Revision / amendment system

| Area | Current rule |
| --- | --- |
| Global/governance docs | owner or `docs.manage_global` capability required |
| Workspace/strategy docs | scoped by workspace and separate from global governance |
| Revision chain | additive append-only statuses such as `draft`, `review`, `approved`, `published`, `superseded` |
| Amendment log | actor, reason, UTC timestamp and change details are recorded |
| Public view | internal provenance and owner-only metadata stay hidden |

## Russian canonical language policy

- Russian is the canonical language for user/product/governance documentation.
- Technical architecture docs may contain English technical terms.
- API names, table names, env vars, file paths and machine values are not
  translated.
- A future English layer should be derived from the Russian source, not become a
  second manually edited canonical copy.

## Legal package status

| Document set | Status | Meaning |
| --- | --- | --- |
| Key legal points | `IN DEVELOPMENT` | DRAFT, not yet a published legal commitment |
| ToS / EULA | `IN DEVELOPMENT` | requires owner placeholders and counsel review |
| Privacy Policy | `IN DEVELOPMENT` | based on current code/data-flow, still DRAFT |
| Trading / automation risk disclosure | `IN DEVELOPMENT` | maps current live-trading gate and trading risk, still DRAFT |
| Third-party integrations / market data | `IN DEVELOPMENT` | reflects NinjaTrader, TopstepX, Telegram, AI integrations, still DRAFT |
| AI disclosure / data processing | `IN DEVELOPMENT` | current provider/data-flow based, still DRAFT |
| Live trading activation consent | `IN DEVELOPMENT` | needed before any public live automation release |
| Electronic acceptance / cookies / regional addenda | `IN DEVELOPMENT` | policy-ready but not final legal publication |

## Owner / counsel decisions still required

- operator legal entity and registered address;
- governing law / arbitration stance;
- support/privacy/security/legal contact addresses;
- liability cap and retention schedule;
- monetization/refund model;
- exact publication timing for any live-automation consent.

## Canonical evidence

- [../DOCUMENTATION_GOVERNANCE.md](../DOCUMENTATION_GOVERNANCE.md)
- [../DOCS_STRUCTURE.md](../DOCS_STRUCTURE.md)
- [../LOCALIZATION.md](../LOCALIZATION.md)
- [../legal/README.md](../legal/README.md)
- `data/governance/change_log.jsonl`
- `app/production_storage/migrations/0011_document_specifications.sql`
