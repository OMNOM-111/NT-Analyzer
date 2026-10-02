# 09. Documentation, Governance and Legal

- Context Pack document: 09_DOCUMENTATION_GOVERNANCE_LEGAL.md
- Last verified UTC: 2026-10-02T05:14:45Z
- Verified against Git SHA: e7ecd2133c65f7ec6ce2bf8dc02eb797819ea885
- Scope: Docs source-of-truth model, revision rules, localization policy and legal status
- Status: DONE

## Canonical documentation structure

The docs tree is intentionally partitioned into `current`, `architecture`,
`operations`, `security`, `product`, `agents`, `strategies`, `governance`,
`changelog`, `adr`, `archive`, `schemas`, `legal` and this compact
root `AI_CONTEXT` upload set.

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
| Amendment log | actor, reason, UTC timestamp and change details are stored as structured data |
| AI provenance | model name/version/environment comes only from trusted infrastructure or is absent; no inherited/manual model signature |
| Public view | owner-only metadata and files are excluded by registry and API boundaries |
| Release governance | local checks -> tests -> clean Git -> CI -> immutable artifact -> Canary acceptance -> same artifact Production |
| Governance scans | repository-wide governance/security/provenance scans run from the repository root; a subdirectory scan is not PASS evidence |

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
| Registration agreement | `AVAILABLE` | official current clickwrap, version `2026-08-30-v2` |
| ToS / EULA and Privacy Policy | `AVAILABLE` | official current informational documents |
| Trading, integration and AI disclosures | `AVAILABLE` | official current informational documents |
| Electronic acceptance and regional addenda | `AVAILABLE` | official current informational documents |
| Live Trading activation | `EXTERNAL BLOCKED` | Live Trading is unavailable until separate release, legal compliance and explicit consent |

## Owner-only legal configuration

- operator legal entity and registered address;
- governing law / arbitration stance;
- support/privacy/security/legal contact addresses;
- liability cap and retention schedule;
- monetization/refund model;
- exact activation timing for any Live Trading consent.

Unfilled operator requisites are isolated in the non-public
`docs/legal/OWNER_LEGAL_CONFIGURATION.md` and are not exposed through the
governance document registry.

Direct owner and non-owner API tests cover registry listing, exact IDs, encoded
path traversal candidates and the independent `/api/documents/*` namespace.

## Canonical evidence

- [../DOCUMENTATION_GOVERNANCE.md](../NT-Analyzer/docs/DOCUMENTATION_GOVERNANCE.md)
- [../DOCS_STRUCTURE.md](../NT-Analyzer/docs/DOCS_STRUCTURE.md)
- [../LOCALIZATION.md](../NT-Analyzer/docs/LOCALIZATION.md)
- [../legal/README.md](../NT-Analyzer/docs/legal/README.md)
- [../governance/AI_PROVENANCE_POLICY.md](../NT-Analyzer/docs/governance/AI_PROVENANCE_POLICY.md)
- [../governance/RELEASE_GOVERNANCE_POLICY.md](../NT-Analyzer/docs/governance/RELEASE_GOVERNANCE_POLICY.md)
- `data/governance/change_log.jsonl`
- `app/production_storage/migrations/0011_document_specifications.sql`
