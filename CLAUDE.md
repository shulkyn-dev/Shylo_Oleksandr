# Telegram-бот на Claude
Головний файл — bot.py. Залежності — requirements.txt.
Бот на VPS DigitalOcean. Шлях: /root/my-bot
Сервіс: mybot.service. Автодеплой: autodeploy.sh щохвилини робить git pull.
Workflow: коміт у main -> сервер оновлюється за хвилину.

## Git Relay

Git Relay дозволяє виконувати shell-команди на сервері через git-репозиторій.

### Як це працює

1. Запишіть команду у `cmds/pending.json`:
   ```json
   {"id":"<унікальний-id>","cmd":"<команда>"}
   ```
2. Закомітьте та запуштьте у `main`.
3. `cmd_runner.py` (запущений як systemd-сервіс) опитує файл кожні 5 секунд.
4. Після виконання результат з'являється у `cmds/result.json` (автоматичний коміт/пуш).

### Формат result.json

```json
{
  "id": "<id команди>",
  "cmd": "<виконана команда>",
  "returncode": 0,
  "output": "<останні 3000 символів stdout+stderr>",
  "error": null
}
```

### Встановлення сервісу на сервері

```bash
cp cmdrunner.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now cmdrunner
```

### Файли

| Файл | Призначення |
|------|-------------|
| `cmd_runner.py` | Основний скрипт-раннер |
| `cmdrunner.service` | systemd-юніт (User=root, Restart=always) |
| `cmds/pending.json` | Вхідна команда |
| `cmds/result.json` | Результат виконання |

### Параметри

- Таймаут: **120 секунд**
- Максимум виводу: **3000 символів** (останні)
- Інтервал опитування: **5 секунд**
- Середовище: читає `/root/my-bot/.env` (містить `GITHUB_TOKEN`)
