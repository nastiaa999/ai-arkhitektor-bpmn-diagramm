"""
Превращает issues линтера в вопросы для диалога-уточнения с пользователем.
Ничего не чинит сам — только формулирует вопрос на русском и отдаёт
его в формате, который ждёт фронтенд (Человек 2): ключи question/step.
"""
from __future__ import annotations

CLARIFIABLE_CODES = {"L06"}  


def _get(obj, name, default=None):
    """issue может быть и dataclass/объектом, и dict — читаем универсально."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _steps_list(ir) -> list:
    """ir может быть и dict, и объектом ProcessIR (pydantic/dataclass)."""
    if isinstance(ir, dict):
        return ir.get("steps", [])
    return getattr(ir, "steps", []) or []


def _step_field(step, name, default=None):
    if isinstance(step, dict):
        return step.get(name, default)
    return getattr(step, name, default)


def _step_name(ir, step_id: str) -> str:
    for s in _steps_list(ir):
        if _step_field(s, "id") == step_id:
            return _step_field(s, "name") or step_id
    return step_id

def issues_to_questions(issues, ir: dict) -> list[dict]:
    """
    issues  — список Issue из lint(ir_raw) (L01..L14)
    ir      — уже залинтованный ProcessIR (как dict)

    Возвращает список:
    {
        "question":  str,   # текст вопроса, показываем пользователю
        "step":      str,   # название шага, к которому относится вопрос
        "code":      str,   # код правила (L06, L09, ...) — для отладки/фильтров
        "step_ids":  [str], # id шагов — для подсветки на диаграмме (UI уже это использует)
        "src":       [int], # номера предложений — тоже для подсветки
    }
    """
    questions: list[dict] = []

    for issue in issues:
        code = _get(issue, "code")
        if code not in CLARIFIABLE_CODES:
            continue

        step_ids = _get(issue, "step_ids", []) or []
        src = _get(issue, "src", []) or []
        step_label = _step_name(ir, step_ids[0]) if step_ids else ""

        if code == "L06":
            question = (
                f'После шага «{step_label}» дальнейшие действия в тексте не описаны. '
                f'Чем завершается процесс в этом случае? '
                f'(Мы автоматически поставили здесь конец процесса — '
                f'уточните, если это не так.)'
            )
        else:  # L09
            question = (
                f'Не понятно, что происходит после «{step_label}» — '
                f'похоже, в описании пропущен шаг. Опишите, что должно произойти.'
            )

        questions.append({
            "question": question,
            "step": step_label,
            "code": code,
            "step_ids": step_ids,
            "src": src,
        })

    return questions
