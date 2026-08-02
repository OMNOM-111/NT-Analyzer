from __future__ import annotations

from app.ai_lab import dialogue_policy, domain_agents


def test_public_policy_encodes_company_hierarchy_and_human_brevity() -> None:
    policy = dialogue_policy.prompt(role="viktor", max_chars=1200)

    assert "Viktor is his right hand" in policy
    assert "Manager coordinates work below Viktor" in policy
    assert "routine answer is 1-4 short sentences" in policy
    assert "must not appear more than once" in policy
    assert "task/mission/incident ids" in policy


def test_public_reply_filter_removes_private_footer_and_duplicate_lines() -> None:
    reply = dialogue_policy.clean_public_reply(
        "Дмитрий Сергеевич, проверку закончил.\n"
        "Проверку закончил.\n"
        "Проверку закончил.\n"
        "model: gpt-5-mini\nprovider: azure_foundry"
    )

    assert reply.lower().count("проверку закончил.") == 1
    assert "gpt-5-mini" not in reply
    assert "azure_foundry" not in reply


def test_public_reply_can_suppress_routine_repeated_vocative() -> None:
    reply = dialogue_policy.clean_public_reply(
        "Дмитрий Сергеевич, работа уже идёт.\nДмитрий Сергеевич, вернусь с итогом.",
        remove_vocative=True,
    )

    assert reply == "Работа уже идёт.\nВернусь с итогом."


def test_adjacent_employee_replies_do_not_repeat_formal_address() -> None:
    reply = dialogue_policy.avoid_adjacent_vocative(
        "Дмитрий Сергеевич, рекомендую повторить проверку.",
        ["Обычный прошлый ответ.", "Дмитрий Сергеевич, работу начал."],
    )

    assert reply == "Рекомендую повторить проверку."


def test_specialist_handoff_is_brief_and_has_correct_hierarchy() -> None:
    note = domain_agents._handoff_note("ivan", "marina")

    assert note == (
        "Иван передал вопрос Марине — это задача по бухгалтерии и финансам. "
        "Ответ будет в этом диалоге."
    )
    assert "Дмитрий Сергеевич" not in note
    assert "это не" not in note.lower()


def test_generated_executive_answer_has_hard_cap_and_keeps_decision_question() -> None:
    verbose = (
        "Дмитрий Сергеевич, фактическая проблема подтверждена. "
        + "Подробность, которая не меняет решение. " * 80
        + "Рекомендую сначала восстановить точную версию и выполнить один контрольный тест. "
        + "Запускаем этот вариант?"
        + "\nmodel: should-not-be-public\nprovider: private"
    )

    reply = dialogue_policy.compact_model_reply(verbose, max_chars=900)

    assert len(reply) <= 900
    assert "фактическая проблема подтверждена" in reply
    assert "Рекомендую" in reply
    assert reply.endswith("Запускаем этот вариант?")
    assert "should-not-be-public" not in reply
    assert reply.count("Дмитрий Сергеевич") <= 1
