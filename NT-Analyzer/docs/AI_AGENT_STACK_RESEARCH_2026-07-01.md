# AI agent stack: benchmark, routing and operating result

Date: 2026-07-01. Scope: historical-only StratForge AI Lab. No paper/live
authority and no automatic promotion authority were granted to any model.

## Production decision

| Lane | Primary | Failover | Deterministic authority |
|---|---|---|---|
| Hypothesis/spec | Azure GPT-5 mini | Gemini pool → OpenRouter Free → local GPT-OSS | JSON/spec contract |
| Code/review/compile fix | Azure GPT-5 mini | OpenRouter Free → Gemini → local GPT-OSS | renderer, static validator, NT compile |
| Backtest analysis | Gemini 2.5 Flash pool | Azure → OpenRouter | analysis pack + arbitration |
| Risk/overfit/final judge | Azure GPT-5 mini | OpenRouter → Gemini → local GPT-OSS | quality gates and manual promotion |
| Mutation/optimizer | Gemini pool | Azure → OpenRouter | one structural mutation per iteration |
| Embeddings | Azure text-embedding-3-small | local Nomic for local retrieval | no execution authority |

The four Gemini keys are one ordered failover pool. A retryable `429`, quota,
timeout or `5xx` response puts the failing key on cooldown and immediately tries
the next key. Priority preserves the configured order; the pool does not use a
VPN or attempt to evade provider limits.

## Measured model benchmark

Same nine task types were used where a model could complete them. Scores are
heuristic contract scores from 0 to 5; they do not prove trading profitability.

| Model | Quality | Success | Median | Practical decision |
|---|---:|---:|---:|---|
| Azure GPT-5 mini | 4.72 | 100% (9/9) | 10.1 s | primary critical model |
| OpenRouter `openrouter/free` | 3.92 | 100% (9/9) | 21.9 s | variable-model reserve |
| local GPT-OSS 20B | 4.23 on 8 saved tasks; final judge 4.38 | completed | 94.2 s (8-task median) | no-cost emergency fallback |
| Gemini 2.5 Flash | 2.76 | 75% (6/8) | 6.7 s | analysis/mutation only; not safety/coding primary |
| Qwen3 Coder 30B | 0 | timeout | >180 s | removed |
| Codestral 22B | 0 | timeout | >300 s | removed |
| DeepSeek Coder V2 Lite | 0 | timeout | >180 s | removed |
| Qwen 3.6 35B-A3B | 0 | timeout | >180 s | removed |

OpenRouter Free returned several different actual models during one benchmark
(Liquid LFM, NVIDIA Nemotron, GPT-OSS and Poolside Laguna). It is therefore a
useful availability reserve, not a deterministic primary judge.

The four Gemini accounts and the Azure embedding deployment passed individual
acceptance calls. Gemini 2.5 Flash dynamic thinking initially consumed the
output allowance and truncated visible JSON. Structured service calls now use
`thinkingBudget=0`, producing a complete 1,238-character test report instead of
69–99 truncated characters. Google documents this control in the official
[Gemini thinking guide](https://ai.google.dev/gemini-api/docs/thinking).

## Real end-to-end verification

### EXP-20260701-0001

- Azure hypothesis request succeeded; the first run exposed and led to fixing
  the router `response`/`content` normalization bug.
- NinjaScript compile: 1/1 successful.
- 14-day smoke: 3 trades, PF after commission 0.609, net -$9.70.
- 180-day backtest: 288 trades, PF after commission 0.778, net -$481.20,
  drawdown -$511.40.
- Deterministic result: `reject / NO_EDGE`, arbitration score 29.38.
- Committee after the router fix: Gemini backtest analyst, Azure risk manager
  and Gemini optimizer all returned non-empty reports. Reports are advisory.

### EXP-20260701-0002

- Azure hypothesis was accepted directly after router normalization.
- NinjaScript compile: 1/1 successful.
- Pre-backtest signal sanity detected 86.13 raw signals/day and stopped the
  strategy as `OVERTRADING_RISK` before spending time on a full backtest.

These outcomes validate the workflow, not the strategy edge. The correct result
was rejection rather than manufacturing a profitable result.

## Usage and cost snapshot

Snapshot after implementation tests: 62 logged calls, 83,513 tokens and
approximately **$0.04142318** reference cost. Against a $100 Azure grant this is
about **0.041423% used**, approximately $99.95858 remaining based only on calls
observed by this application.

| Purpose | Calls | Tokens | Approx. cost |
|---|---:|---:|---:|
| External benchmark | 26 | 38,858 | $0.017046 |
| Hypotheses | 6 | 10,841 | $0.00689025 |
| Compile fixes | 5 | 22,536 | $0.014372 |
| Risk committee | 2 | 2,848 | $0.00311475 |
| Gemini committee analysis/optimization | 4 | 6,572 | $0 |
| Gemini thinking-budget acceptance | 1 | 1,253 | $0 |
| Pool/embedding acceptance | 5 | 205 | $0.00000018 |
| Earlier connection/error-path tests | 13 | 400 | $0 |

Azure figures use the public OpenAI model rates as a reference because an
inference key cannot read Azure billing. The Azure invoice/Cost Management is
authoritative. References: [GPT-5 mini](https://platform.openai.com/docs/models/gpt-5-mini),
[text-embedding-3-small](https://platform.openai.com/docs/models/text-embedding-3-small).
Gemini is configured as free tier; current provider/project rate limits remain
authoritative: [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing).

Current local budgets are `0`, meaning monitoring-only, not exhausted. The
global hard cap remains $0.50 per call. A positive daily/monthly limit activates
pre-request blocking and automatic disable when reached.

## Monitoring

`AI Agents / API Keys` shows encrypted-key masks, model/account, role, pool,
priority, pricing source, tokens, estimated cost, grant remaining/percent used,
cooldown and usage rows without prompt content.

`AI Lab` additionally shows:

- external requests currently in flight (role, model, account and purpose);
- recent completed requests with tokens/cost/status;
- grant remaining and percentage used;
- current role route and failover order;
- experiment activity and the model used at each stage.

Local usage and experiment data stay under gitignored `ai_lab/registry/` and
`ai_lab/experiments/`. API keys stay in Windows DPAPI storage and never enter
Git, usage logs, prompts, errors or reports.

## Local model cleanup

Codestral, DeepSeek Coder V2 Lite, Qwen3 Coder and Qwen 3.6 were removed after
timeouts. Disk usage fell from 70.89 GB to 12.19 GB, freeing about **58.70 GB**.
The retained local models are GPT-OSS 20B (12.11 GB) and Nomic embedding
(84.11 MB). Runtime role documents now reference GPT-OSS only.

## Known limits

- Estimated spend cannot include calls made outside StratForge, taxes, regional
  Azure adjustments or delayed provider billing.
- Free-tier limits are provider/project state, not a guaranteed fixed number.
- Rotation improves availability but cannot promise that work never stops; if
  every configured account is exhausted or the provider is down, the workflow
  fails safely or uses the local fallback.
- Models propose and explain. Static validation, NinjaTrader compile, historical
  backtest, arbitration and manual promotion remain mandatory.
