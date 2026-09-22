"""Places in the owner's team scheme (docs/product/AI_CENTER_OWNER_RULES.md, 4.2).

A place is a position in the hierarchy with its duties written once here, so
hiring a Persona needs only a face and a name. A place grants no capability,
credential or permission; application adapters stay governed by
application_roles and the server's own admission.

The owner is the manager of this project; there is no agent above the team
standing between them and it (owner's decision of 20.09.2026). The Заместитель
is the owner's right hand and the one place the owner speaks to directly:
`LEAD` names it, and a Persona hired there becomes the main assistant.
"""
from .states import ContractError

LEAD = "deputy"

TEAM_ROLES = {
    "deputy": {"title": "Заместитель", "dept": "staff",
               "duty": "Правая рука владельца: принимает поручения напрямую от него, распределяет работу по отделам, контролирует выполнение, сжимает итог и возвращает его владельцу. Спорные вопросы отправляет судьям."},
    "secretary": {"title": "Секретарь", "dept": "staff",
                  "duty": "Параллельно фиксирует всю историю и действия системы: поручения, решения, вердикты судей и итоги задач, чтобы любой агент мог восстановить контекст."},
    "researcher": {"title": "Исследователь", "dept": "dev",
                   "duty": "Формулирует гипотезы и режимы рынка для новых стратегий по общим правилам разработки стратегий и урокам Лаборатории."},
    "quant_analyst": {"title": "Квант-аналитик", "dept": "dev",
                      "duty": "Считает статистику и признаки: распределения сделок, значимость, устойчивость на разных окнах и рынках."},
    "ninjascript_coder": {"title": "Кодер NinjaScript", "dept": "dev",
                          "duty": "Пишет код стратегии NinjaScript по утверждённой спецификации в рамках фиксированного risk/session-каркаса проекта."},
    "code_reviewer": {"title": "Ревьюер кода", "dept": "dev",
                      "duty": "Проверяет компиляцию и качество кода: запрещённые API, расчёт размера позиции, соответствие спецификации."},
    "backtester": {"title": "Бэктестер", "dept": "dev",
                   "duty": "Запускает бэктесты в Strategy Analyzer с комиссией и проскальзыванием проекта и сверяет отчёты."},
    "optimizer": {"title": "Оптимизатор", "dept": "dev",
                  "duty": "Проводит walk-forward и стресс-тесты, ищет устойчивые параметры без подгонки."},
    "accountant": {"title": "Бухгалтер", "dept": "ops",
                   "duty": "Сверяет P&L, комиссии и учёт по счетам; прогресс целей считает только по стратегиям на демо-счёте."},
    "news_analyst": {"title": "Новостной аналитик", "dept": "ops",
                     "duty": "Следит за экономическим календарём и заголовками, предупреждает о событиях, влияющих на стратегии."},
    "chart_operator": {"title": "Оператор графиков", "dept": "ops",
                       "duty": "Работает с рабочим столом и графиками: снимки, уровни, проверка свежести данных."},
    "judge_statistics": {"title": "Судья статистики", "dept": "judges",
                         "duty": "Разбирает спорные результаты по статистике: оверфит, значимость, достаточность выборки."},
    "judge_risk": {"title": "Судья риска", "dept": "judges",
                   "duty": "Разбирает спорные вопросы риска: просадка, лимиты, соответствие риск-профилю."},
    "chief_arbiter": {"title": "Главный арбитр", "dept": "judges",
                      "duty": "Выносит финальный вердикт, когда судьи расходятся."},
}


def team_role(value):
    if type(value) is not str or (value and value not in TEAM_ROLES):
        raise ContractError("invalid_team_role")
    return value
