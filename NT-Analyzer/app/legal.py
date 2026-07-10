"""Terms of use / disclaimer for StratForge AI.

StratForge AI is a personal, non-commercial hobby project. The author does not
sell the software and does not receive direct payment for it — only voluntary
donations. Every user accepts full responsibility for their own use, trading
decisions and results. This module is the single source of truth for the terms
text and its version; registration requires explicit acceptance.
"""
from __future__ import annotations

from typing import Any, Dict


TERMS_VERSION = "2026-07-07"
TERMS_TITLE = "Условия использования и отказ от ответственности"

# Plain-text sections (rendered as an accessible list in the UI). Kept in the
# module so both the API and the registration flow share one wording.
TERMS_SECTIONS = (
    ("Личный некоммерческий проект",
     "StratForge AI — это личный любительский проект. Автор разрабатывает его дома "
     "самостоятельно как энтузиаст, не продаёт программу и не получает за неё прямой "
     "оплаты. Единственная форма поддержки — добровольные пожертвования (донаты)."),
    ("Пожертвования добровольны",
     "Донаты и любые взносы — это добровольная поддержка разработки, а не покупка "
     "услуги или гарантий. Они не подлежат возврату и не создают обязательств автора "
     "перед пользователем."),
    ("Полная ответственность пользователя",
     "Вы используете приложение исключительно на свой страх и риск. Все торговые и "
     "инвестиционные решения, а также их финансовые последствия — полностью ваша "
     "ответственность. Автор не несёт ответственности за любые убытки, упущенную "
     "выгоду или ущерб."),
    ("Без гарантий",
     "Приложение предоставляется «как есть», без каких-либо гарантий работоспособности, "
     "точности данных, доступности или пригодности для конкретных целей. Возможны "
     "ошибки, перерывы и изменения функциональности."),
    ("Не финансовый совет",
     "Материалы, аналитика и сигналы носят информационный характер и не являются "
     "индивидуальной инвестиционной рекомендацией или финансовым советом."),
    ("Доступ и данные",
     "Доступ подтверждается через Telegram, персональные данные хранятся в "
     "зашифрованном виде (Windows DPAPI). Владелец может ограничить или отозвать доступ. "
     "Пользователь обязуется не пытаться получить функции, которые ему не разрешены."),
    ("Согласие",
     "Продолжая регистрацию и используя приложение, вы подтверждаете, что прочитали и "
     "принимаете эти условия и берёте все риски на себя."),
)


def terms_payload() -> Dict[str, Any]:
    return {
        "version": TERMS_VERSION,
        "title": TERMS_TITLE,
        "sections": [{"heading": h, "body": b} for h, b in TERMS_SECTIONS],
    }
