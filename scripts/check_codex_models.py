"""Small live SDK smoke check using synthetic mail, not private mailbox contents."""
from src.reporting.sdk import SDKWorker

messages = [
    {
        "id": "hotel",
        "text": "Dusit направил замечания к обновлённой планировке Suite в отеле.",
    },
    {
        "id": "birthday",
        "text": "Коллеги, поздравляем с днём рождения! Приглашаем на чай.",
    },
    {
        "id": "marina",
        "text": "Подрядчик направил график монтажа плавучих понтонов яхтенной марины.",
    },
    {
        "id": "procurement",
        "text": "ИСК направил сравнение стоимости мебели и BOQ апартаментов.",
    },
]
with SDKWorker() as worker:
    print(
        "ChatGPT authentication verified. Required models available:",
        {"gpt-5.6-luna", "gpt-5.6-terra"}.issubset(worker.available),
        flush=True,
    )
    result = worker.ask(
        "triage",
        'Отбери письма по отелю и апартаментам. Верни {"relevant_ids":["id"]}.',
        {"messages": messages},
    )
    if set(result.get("relevant_ids", [])) != {"hotel", "procurement"}:
        raise SystemExit("Model smoke check failed: relevance mismatch")
    print("Luna relevance smoke check passed.", worker.usage)
