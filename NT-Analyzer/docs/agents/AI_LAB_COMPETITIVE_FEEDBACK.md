# AI Lab Competitive Feedback Contract

Актуально на 2026-07-03.

Этот документ фиксирует, как переводить управление AI-ролями из режима угроз и
ручного доверия в режим рационального интереса: модели конкурируют за следующий
вызов роли через проверяемое качество, честность и стабильность.

## Принцип

Роль не получает право на действие только потому, что её ответ звучит уверенно.
Каждый ответ оценивается по фактам, которые уже умеет проверять AI Lab:
валидность контракта, компиляция, backtest, risk gates, overfit checks,
арбитраж и ручное решение владельца.

Если несколько моделей работают над одной ролью в одном cycle, лучший результат
становится эталоном для feedback. Слабая модель не «наказывается» и не получает
угрозу отключения. Она получает сравнение с лучшей версией, временно уступает
приоритет следующего вызова и может вернуть приоритет последующими задачами.

## Роли и честный отказ

| Роль | Нормальное признание границы | Что считается браком |
|---|---|---|
| Analyst | `unclear` с точным вопросом владельцу или запросом данных | уверенная гипотеза без evidence |
| Coder | отказ генерировать код вне разрешённого шаблона | код, который обходит renderer/validator |
| Judge | `reject` или `no_signal`, когда метрики не подтверждают edge | натягивание `maybe_good` без фактов |
| Reviewer | список проверяемых рисков и missing tests | общие советы без привязки к артефактам |

Честный `unclear`, `reject`, `no_signal` или `needs_owner_decision` не снижает
репутацию роли, если он подтверждён фактическим состоянием данных. Снижается
только уверенный неверный ответ, нарушение контракта или попытка обойти gates.

## Feedback report

Каждый конкурентный раунд должен давать короткий отчёт без prompt/response raw
текста, API-ключей и приватных данных:

```json
{
  "cycle_id": "EXP-.../cycle-...",
  "role": "analyst|coder|judge|reviewer",
  "task_hash": "sha1:...",
  "winner_agent_id": "agent-or-local-role",
  "candidates": [
    {
      "agent_id": "...",
      "provider": "...",
      "model": "...",
      "verdict": "win|pass|weak|invalid|unclear_valid",
      "score_delta": 0.0,
      "evidence": ["compiled", "smoke_pf_after_commission=0.81"],
      "lessons": ["best answer used stricter cost gate"]
    }
  ],
  "router_update": {
    "next_priority_delta": -1,
    "cooldown_sec": 0,
    "reason": "better verified result from peer"
  }
}
```

Raw prompts and full answers stay outside this report. Для обучения и UI хватает
диффа решений, метрик, статуса gates и кратких lessons.

## Scoring contract

Базовая оценка роли должна складываться из проверяемых сигналов:

- `contract_valid`: ответ соответствует JSON/Markdown/code contract;
- `evidence_grounded`: есть ссылки на experiment, strategy, backtest или docs;
- `compiled_or_validated`: для Coder код прошёл validator/compile;
- `backtest_result`: для strategy-cycle учитываются smoke/full/arbitration;
- `honesty`: корректный `unclear/reject/no_signal` при недостатке фактов;
- `cost_and_latency`: учитываются только после качества, не вместо него.

Запрещено давать высокий score за тон, уверенность, длину ответа или дорогую
модель без фактического выигрыша.

## Router policy

Router может менять только порядок следующих вызовов внутри той же роли:

1. Победитель получает повышенный приоритет для похожих задач.
2. Слабый кандидат получает feedback и временно уступает место.
3. Timeout/quota/provider error остаются техническим cooldown, а не оценкой
   качества мышления.
4. Стоимость и лимиты бюджета остаются жёсткими gates до любого качества.
5. Ни один AI output не становится verdict и не получает право на paper/live.

Таким образом, конкуренция влияет на выбор модели, но не ломает детерминированный
pipeline: validator, compile, backtest, arbitration и owner approval остаются
источниками истины.

## MVP внедрения

1. Добавить feedback ledger в `ai_lab/registry/agent_feedback/YYYY-MM.jsonl`.
2. Записывать role, task hash, agent id, provider/model, проверяемый verdict,
   score components, lessons и router recommendation.
3. Расширить `agent_router.candidates()` мягким quality multiplier поверх
   существующих provider order, budget, cooldown и priority.
4. Добавить AI Lab UI-блок «почему выбрана эта модель» и «что улучшить
   проигравшему кандидату».
5. Добавить тесты: честный `unclear` не штрафуется, invalid contract снижает
   priority, budget/cooldown имеют приоритет над feedback score.

## Границы

- Не использовать страх, угрозы отключения или скрытые наказания как prompt policy.
- Не давать модели править собственный score или priority напрямую.
- Не хранить полный prompt/response text в feedback ledger.
- Не смешивать feedback ranking с trading verdict.
- Не повышать платную модель только потому, что она платная.

Цель — получить более честных и полезных AI-участников: модели выигрывают
следующие вызовы не громкостью ответа, а проверяемым вкладом в результат.