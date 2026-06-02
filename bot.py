import os, logging, math, datetime, re
for v in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy","ALL_PROXY","all_proxy"):
    os.environ.pop(v, None)
from dotenv import load_dotenv
import anthropic
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
history: dict[int, list[dict]] = {}

# ── Tools ──────────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "web_search",
        "description": "Search the web using DuckDuckGo. Returns a list of results with title, url, and snippet.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_url",
        "description": "Fetch the text content of a web page by URL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "max_chars": {"type": "integer", "description": "Max characters to return (default 3000)", "default": 3000},
            },
            "required": ["url"],
        },
    },
    {
        "name": "calculator",
        "description": "Evaluate a mathematical expression. Supports +,-,*,/,**,sqrt,sin,cos,tan,log,pi,e.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Math expression to evaluate"}
            },
            "required": ["expression"],
        },
    },
    {
        "name": "get_datetime",
        "description": "Get the current date and time (Kyiv timezone).",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def tool_web_search(query: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; bot/1.0)"}
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=headers,
            timeout=10,
        )
        soup = BeautifulSoup(r.text, "html.parser")
        results = []
        for item in soup.select(".result")[:6]:
            title_el = item.select_one(".result__title")
            url_el = item.select_one(".result__url")
            snip_el = item.select_one(".result__snippet")
            title = title_el.get_text(strip=True) if title_el else ""
            url = url_el.get_text(strip=True) if url_el else ""
            snip = snip_el.get_text(strip=True) if snip_el else ""
            if title:
                results.append(f"**{title}**\n{url}\n{snip}")
        return "\n\n".join(results) if results else "No results found."
    except Exception as e:
        return f"Search error: {e}"


def tool_fetch_url(url: str, max_chars: int = 3000) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; bot/1.0)"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:max_chars]
    except Exception as e:
        return f"Fetch error: {e}"


def tool_calculator(expression: str) -> str:
    allowed = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
    allowed.update({"pi": math.pi, "e": math.e, "abs": abs, "round": round})
    try:
        # block anything that looks dangerous
        if re.search(r"[a-zA-Z_][a-zA-Z_0-9]*\s*\(", expression):
            # allow only known math functions
            used = re.findall(r"[a-zA-Z_][a-zA-Z_0-9]*", expression)
            for name in used:
                if name not in allowed:
                    return f"Unknown function or variable: {name}"
        result = eval(expression, {"__builtins__": {}}, allowed)  # noqa: S307
        return str(result)
    except Exception as e:
        return f"Calculation error: {e}"


def tool_get_datetime() -> str:
    try:
        from zoneinfo import ZoneInfo
        now = datetime.datetime.now(ZoneInfo("Europe/Kyiv"))
    except Exception:
        now = datetime.datetime.utcnow()
    return now.strftime("%Y-%m-%d %H:%M:%S %Z")


def execute_tool(name: str, inputs: dict) -> str:
    if name == "web_search":
        return tool_web_search(inputs["query"])
    if name == "fetch_url":
        return tool_fetch_url(inputs["url"], inputs.get("max_chars", 3000))
    if name == "calculator":
        return tool_calculator(inputs["expression"])
    if name == "get_datetime":
        return tool_get_datetime()
    return f"Unknown tool: {name}"


# ── Agentic loop ───────────────────────────────────────────────────────────────

MAX_ITERATIONS = 10

def run_agent(messages: list[dict]) -> str:
    """Run the agentic loop and return the final text response."""
    for _ in range(MAX_ITERATIONS):
        resp = claude.messages.create(
            model="claude-opus-4-7",
            max_tokens=4096,
            system=(
                "Ти корисний україномовний асистент з доступом до інструментів. "
                "Використовуй інструменти коли потрібна актуальна інформація, "
                "обчислення або вміст сторінок. Відповідай чітко та по суті."
            ),
            tools=TOOLS,
            messages=messages,
        )

        # collect any text blocks for a final answer
        text_blocks = [b.text for b in resp.content if hasattr(b, "text")]
        tool_uses = [b for b in resp.content if b.type == "tool_use"]

        if resp.stop_reason == "end_turn" or not tool_uses:
            return "\n".join(text_blocks) or "…"

        # append assistant turn with all content blocks
        messages.append({"role": "assistant", "content": resp.content})

        # execute each tool and build tool_result blocks
        tool_results = []
        for tu in tool_uses:
            log.info("Tool call: %s %s", tu.name, tu.input)
            output = execute_tool(tu.name, tu.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": output,
            })

        messages.append({"role": "user", "content": tool_results})

    return "Перевищено ліміт ітерацій агента."


# ── Telegram handlers ──────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привіт! Я агент із інструментами:\n"
        "🔍 Пошук у вебі\n"
        "🌐 Читання сторінок\n"
        "🧮 Калькулятор\n"
        "🕐 Дата і час\n\n"
        "/reset — очистити розмову"
    )


async def reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    history.pop(update.effective_user.id, None)
    await update.message.reply_text("Розмову очищено.")


async def chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_text = update.message.text
    history.setdefault(uid, []).append({"role": "user", "content": user_text})
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        # pass a copy so the agent loop can extend it freely
        messages = list(history[uid])
        reply = run_agent(messages)
        # save only the final user+assistant exchange to keep history clean
        history[uid].append({"role": "assistant", "content": reply})
        history[uid] = history[uid][-40:]
        await update.message.reply_text(reply)
    except Exception:
        log.exception("chat error")
        await update.message.reply_text("Помилка. Спробуй ще раз.")


def main():
    app = ApplicationBuilder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    log.info("Agent bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
