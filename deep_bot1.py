import os
import logging
import asyncio
import json
import re
import random  # For shuffling and random selections
from datetime import time, timedelta

import telegram
from telegram import Update, Poll, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    PollAnswerHandler,
    filters,
    ContextTypes,
    CallbackContext,
    ConversationHandler,
)
import google.generativeai as genai
from telegram.constants import ParseMode
"""
----------------------------------------------------------------
 **Configuration Settings**:
 This section contains the app's configurations, including
 API keys, database settings, and environment variables.
----------------------------------------------------------------
"""

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states for interactive polls
POLL_TYPE, POLL_QUESTION, POLL_OPTIONS, POLL_CORRECT = range(4)

# Conversation states for daily quiz:
DAILYQUIZ_TOPIC, DAILYQUIZ_COUNT = range(2)

# API keys and constants
TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ACCESS_CODE = os.getenv("ACCESS_CODE")
POLL_DURATION = 86400  # seconds for polls
QUIZ_INTERVAL = 86400  # seconds between daily quiz questions

# The channel chat ID for non-personal commands
CHANNEL_CHAT_ID = -1002374021898
#CHANNEL_CHAT_ID = -1002467381512

ALWAYS_AUTHORIZED_USERNAMES = {"satyam_8726p", "eXclusivelyStudio"}


# Initialize Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

# Global variables
AUTHORIZED_USER_IDS = set()
user_scores = {}         # Placeholder dictionary for leaderboard tracking
subscriptions = {}       # {user_id: set of topics}
FLASHCARD_DATA = {}      # {user_id: {"question": ..., "answer": ...}}

"""
----------------------------------------------------------
 This section contains the **COMMAND LIST** with all
 available user commands and their descriptions.
----------------------------------------------------------
"""

commands_list = [
    BotCommand("start", "Show the welcome menu (personal)"),
    BotCommand("auth", "Authorize user (personal)"),
    BotCommand("search", "Get study guide (Hindi) (personal)"),
    BotCommand("subscribe", "Subscribe to GK topic (personal)"),
    BotCommand("unsubscribe", "Unsubscribe from GK topic (personal)"),
    BotCommand("subscriptions", "List your subscriptions (personal)"),
    BotCommand("announce", "Announce (personal)"),
    BotCommand("help", "Show available commands (personal)"),
    BotCommand("poll", "Create interactive poll (channel)"),
    BotCommand("dailyquiz", "Daily GK quiz (bilingual) (channel)"),
    BotCommand("flashcard", "Flashcard (Hindi) (channel)"),
    BotCommand("flip", "Reveal flashcard answer (channel)"),
    BotCommand("fact", "Random GK fact (Hindi) (channel)"),
    BotCommand("news", "GK/Current affairs news (Hindi) (channel)"),
    BotCommand("alerts", "Exam alerts (Hindi) (channel)"),
    BotCommand("leaderboard", "View leaderboard (channel)"),
    BotCommand("mocktest", "Mock test (bilingual) (channel)"),
    BotCommand("stop", "Stop the ongoing daily quiz (channel)")
]

"""
--------------------------------------------------------
 **Helper Functions**: Utility functions used across 
 the project for optimized performance and reusability.
--------------------------------------------------------
"""

def escape_markdown(text: str) -> str:
    escape_chars = "_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in escape_chars else c for c in text)

def clean_response_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()

"""
------------------------------------------------------
 **Personal Command Handlers**: This section deals with
 user-specific requests, authentication, and private data.
------------------------------------------------------
"""

# These commands send responses privately (to the user's personal chat).

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user:
        return
    if not is_authorized(update.effective_user):  # Use the function!
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="🔒 You are not authorized. Use /auth <access_code>",
        )
        return
    await context.bot.send_message(chat_id=update.effective_user.id,
                                   text="Welcome to InfoBot! To view available commands, type '/' or use /help.")

def is_authorized(user: telegram.User) -> bool:
    """Checks if a user is authorized, either by ID or username."""
    if user.id in AUTHORIZED_USER_IDS:
        return True
    if user.username in ALWAYS_AUTHORIZED_USERNAMES:
        return True
    return False

async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user:
        return
    if context.args and context.args[0] == ACCESS_CODE:
        AUTHORIZED_USER_IDS.add(update.effective_user.id)
        await context.bot.send_message(chat_id=update.effective_user.id,
                                       text="✅ Authorization successful!")
    else:
        await context.bot.send_message(chat_id=update.effective_user.id,
                                       text="❌ Invalid access code")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = "Available Commands:\n\n"
    for cmd in commands_list:
        help_text += f"/{cmd.command} - {cmd.description}\n"
    await context.bot.send_message(chat_id=update.effective_user.id, text=help_text)

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user:
        return
    if update.effective_user.id not in AUTHORIZED_USER_IDS:
        await context.bot.send_message(chat_id=update.effective_user.id,
                                       text="🔒 You are not authorized. Use /auth <access_code>")
        return
    if not context.args:
        await context.bot.send_message(chat_id=update.effective_user.id,
                                       text="❌ Please provide a search query. Usage: /search <topic>")
        return
    query = " ".join(context.args)
    prompt = (f"Generate a comprehensive study guide for one day examinations on the topic '{query}' in Hindi. "
              "Organize the guide into exactly 5 sections. Each section should contain exactly 10 important points. "
              "Format the output with clear section headers (e.g., 'Section 1', 'Section 2', etc.) and list each point as a numbered item. "
              "Do not include any additional commentary or explanation.")
    response = model.generate_content(prompt)
    logger.info(f"Gemini response for search query '{query}': {response.text}")
    result_text = clean_response_text(response.text)
    if len(result_text) > 4000:
        chunks = [result_text[i:i+4000] for i in range(0, len(result_text), 4000)]
        for chunk in chunks:
            await context.bot.send_message(chat_id=update.effective_user.id, text=chunk)
    else:
        await context.bot.send_message(chat_id=update.effective_user.id, text=result_text)

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user:
        return
    if update.effective_user.id not in AUTHORIZED_USER_IDS:
        return
    if not context.args:
        await context.bot.send_message(chat_id=update.effective_user.id,
                                       text="❌ Usage: /subscribe <topic>")
        return
    topic = " ".join(context.args).strip()
    user_id = update.effective_user.id
    subscriptions.setdefault(user_id, set()).add(topic)
    await context.bot.send_message(chat_id=update.effective_user.id,
                                   text=f"✅ Subscribed to topic: {topic}")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user:
        return
    if update.effective_user.id not in AUTHORIZED_USER_IDS:
        return
    if not context.args:
        await context.bot.send_message(chat_id=update.effective_user.id,
                                       text="❌ Usage: /unsubscribe <topic>")
        return
    topic = " ".join(context.args).strip()
    user_id = update.effective_user.id
    if user_id in subscriptions and topic in subscriptions[user_id]:
        subscriptions[user_id].remove(topic)
        await context.bot.send_message(chat_id=update.effective_user.id,
                                       text=f"✅ Unsubscribed from topic: {topic}")
    else:
        await context.bot.send_message(chat_id=update.effective_user.id,
                                       text=f"❌ You are not subscribed to topic: {topic}")

async def subscriptions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user:
        return
    user_id = update.effective_user.id
    subs = subscriptions.get(user_id, set())
    if not subs:
        await context.bot.send_message(chat_id=update.effective_user.id, text="You have no subscriptions.")
    else:
        await context.bot.send_message(chat_id=update.effective_user.id,
                                       text="Your subscriptions:\n" + "\n".join(subs))

async def announce(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Check if the user is authorized
    if not update.effective_user or update.effective_user.id not in AUTHORIZED_USER_IDS:
        return

    # Ensure the user provided an announcement message
    if not context.args:
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="❌ Usage: /announce <announcement message>"
        )
        return

    # Compose the announcement text from the command arguments
    user_text = " ".join(context.args)
    # Escape user text so reserved characters (like !) are handled
    escaped_announcement_text = escape_markdown(user_text)
    # Prepare a decorative header line by escaping it
    header_line = escape_markdown("====================")
    # Prepare a decorative footer text and escape it
    footer_text = escape_markdown("Stay tuned for more updates!")
    
    # Build the decorated message.
    # Note: We leave Markdown formatting markers (like '*' for bold) intact.
    decorated_message = (
        f"📢 *{header_line}*\n"
        f"     *ANNOUNCEMENT*\n"
        f"📢 *{header_line}*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{escaped_announcement_text}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"_{footer_text}_"
    )
    
    # Send the decorated announcement to the designated channel.
    await context.bot.send_message(
        chat_id=CHANNEL_CHAT_ID,
        text=decorated_message,
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    # Confirm to the user that the announcement has been sent.
    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="✅ Announcement sent to the channel."
    )


"""    
-------------------------------------------------
 This section manages **personal data**.
 Handles logs, metadata, and public API responses.
-------------------------------------------------
"""

# These commands send responses to the channel (CHANNEL_CHAT_ID).

async def start_poll_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user.id not in AUTHORIZED_USER_IDS:
        await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                       text="🔒 You are not authorized")
        return ConversationHandler.END
    await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                   text="📊 Should this poll be anonymous? (yes/no)")
    return POLL_TYPE

async def receive_poll_type_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_input = update.message.text.strip().lower()
    if user_input not in ['yes', 'no']:
        await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                       text="❌ Please answer with 'yes' or 'no'")
        return POLL_TYPE
    context.user_data['is_anonymous'] = True
    await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                   text="✍️ Please enter your poll question:")
    return POLL_QUESTION

async def receive_question_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['question'] = update.message.text.strip()
    await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                   text="📝 Enter poll options separated by commas:")
    return POLL_OPTIONS

async def receive_options_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    options = [opt.strip() for opt in update.message.text.split(',') if opt.strip()]
    if len(options) < 2:
        await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                       text="❌ Need at least 2 options. Please try again:")
        return POLL_OPTIONS
    context.user_data['options'] = options[:10]
    await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                   text="✅ Please enter the number (1-based) of the correct answer:")
    return POLL_CORRECT

async def receive_correct_option_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        index = int(update.message.text.strip()) - 1
        options = context.user_data.get('options')
        if index < 0 or index >= len(options):
            raise ValueError("Invalid index")
    except Exception as e:
        await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                       text="❌ Please enter a valid option number.")
        return POLL_CORRECT
    try:
        message = await context.bot.send_poll(
            chat_id=CHANNEL_CHAT_ID,
            question=context.user_data['question'][:300],
            options=context.user_data['options'],
            is_anonymous=True,
            type='quiz',
            correct_option_id=index
        )
        context.job_queue.run_once(
            close_poll,
            POLL_DURATION,
            data={"chat_id": CHANNEL_CHAT_ID, "message_id": message.message_id}
        )
    except Exception as e:
        logger.error(f"Poll creation error: {e}")
        await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                       text="❌ Failed to create poll")
    context.user_data.clear()
    return ConversationHandler.END

async def handle_auto_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or update.effective_user.id not in AUTHORIZED_USER_IDS:
        return
    text = update.message.text.strip()
    if not text.endswith("?"):
        return
    prompt = (
        f"Given the simple question: \"{text}\", perform the following steps:\n"
        "Step 0: Enhance and rephrase the question to make it more complex, formal, and engaging. Ensure that the enhanced question is provided in bilingual format (English | हिंदी).\n"
        "Step 1: Generate one correct option and three incorrect options for the enhanced question. Do not order them yet.\n"
        "Step 2: Randomly shuffle these four options so that the correct option is not predictably placed at the first position. "
        "To simulate randomness, generate a random integer between 0 and 3 and place the correct option at that index, filling in the remaining positions with the distractors in any order.\n"
        "Step 3: Return a JSON object with exactly three keys:\n"
        "  - \"question\": a string representing the enhanced question in bilingual format,\n"
        "  - \"options\": an array of exactly 4 option strings in the final shuffled order in bilingual format,\n"
        "  - \"correct_index\": an integer (0-indexed) indicating the index of the correct answer in the options array.\n"
        "Do not include any additional text, commentary, or explanation."
    )
    response = model.generate_content(prompt)
    logger.info(f"Gemini response for auto quiz question '{text}': {response.text}")
    clean_text = clean_response_text(response.text)
    try:
        data = json.loads(clean_text)
    except Exception as e:
        logger.error(f"Error parsing JSON from Gemini for question '{text}': {e}")
        await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                       text="❌ Failed to generate quiz poll from Gemini.")
        return
    options = data.get("options")
    correct_index = data.get("correct_index")
    if not isinstance(options, list) or len(options) != 4:
        logger.error(f"Gemini did not return exactly 4 options for question '{text}'.")
        await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                       text="❌ Gemini did not return exactly 4 options. Please try again.")
        return
    if not isinstance(correct_index, int) or correct_index < 0 or correct_index >= len(options):
        logger.warning(f"Invalid correct_index for question '{text}'. Defaulting to 0.")
        correct_index = 0

    # Truncate options to 95 characters and add "..." if truncated
    truncated_options = []
    for option in options:
        if len(option) > 95:
            truncated_options.append(option[:95] + "...")
        else:
            truncated_options.append(option)
    options = truncated_options # Replace original options with truncated ones


    original_correct_option = options[correct_index] # Use truncated options now
    random.shuffle(options)
    correct_index = options.index(original_correct_option)
    try:
        message = await context.bot.send_poll(
            chat_id=CHANNEL_CHAT_ID,
            question=text[:300],
            options=options,
            is_anonymous=True,
            type='quiz',
            correct_option_id=correct_index
        )
        context.job_queue.run_once(
            close_poll,
            POLL_DURATION,
            data={"chat_id": CHANNEL_CHAT_ID, "message_id": message.message_id}
        )
    except Exception as e:
        logger.error(f"Error sending auto quiz poll for question '{text}': {e}")
        await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                       text="❌ Failed to send quiz poll.")


# -------------------- Daily Quiz Conversation Handler -------------------- #
# Now the daily quiz conversation first asks for a topic and then for the number of questions.
async def start_dailyquiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                   text="Please enter the quiz topic ")
    return DAILYQUIZ_TOPIC

async def receive_dailyquiz_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    topic = update.message.text.strip()
    context.chat_data["dailyquiz_topic"] = topic
    await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                   text="Number of questions ")
    return DAILYQUIZ_COUNT

async def receive_dailyquiz_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        count = int(update.message.text.strip())
    except Exception as e:
        await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                       text="❌ Please enter a valid number.")
        return DAILYQUIZ_COUNT
    context.chat_data["dailyquiz_count"] = count
    context.chat_data["dailyquiz_active"] = True
    context.chat_data["dailyquiz_scores"] = {}
    context.chat_data["dailyquiz_polls"] = {}
    await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                   text=f"Starting daily quiz on topic: {context.chat_data.get('dailyquiz_topic')} for {count} questions.")
    asyncio.create_task(run_dailyquiz(context))
    return ConversationHandler.END

async def stop_dailyquiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.chat_data["dailyquiz_active"] = False
    await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                   text="Daily quiz stopped.")
    return ConversationHandler.END

async def run_dailyquiz(context: ContextTypes.DEFAULT_TYPE) -> None:
    topic = context.chat_data.get("dailyquiz_topic")
    count = context.chat_data.get("dailyquiz_count", 25)
    if not topic:
        return
    for i in range(count):
        if not context.chat_data.get("dailyquiz_active", True):
            break
        prompt = (f"Generate one GK quiz random question on the topic '{topic}' suitable for daily practice in competitive exams. "
                  "Provide one question and 4 multiple-choice options in random order. "
                  "Ensure that the question is in bilingual format (English | हिंदी). "
                  "Return the result in JSON format with keys: \"question\", \"options\", \"correct_index\".")
        response = model.generate_content(prompt)
        try:
            data = json.loads(clean_response_text(response.text))
        except Exception as e:
            logger.error(f"Error parsing JSON for daily quiz question: {e}")
            continue
        question = data.get("question", "Daily Quiz")
        options = data.get("options")
        correct_index = data.get("correct_index", 0)
        if not isinstance(options, list) or len(options) != 4:
            continue
        original_correct_option = options[correct_index]
        random.shuffle(options)
        correct_index = options.index(original_correct_option)
        try:
            poll_message = await context.bot.send_poll(
                chat_id=CHANNEL_CHAT_ID,
                question=question[:300],
                options=options,
                is_anonymous=True,
                type='quiz',
                correct_option_id=correct_index
            )
            poll_id = poll_message.poll.id
            context.chat_data["dailyquiz_polls"][poll_id] = correct_index
        except Exception as e:
            logger.error(f"Error sending daily quiz poll: {e}")
        await asyncio.sleep(QUIZ_INTERVAL)
    scores = context.chat_data.get("dailyquiz_scores", {})
    if not scores:
        leaderboard_text = "No correct answers were recorded."
    else:
        leaderboard_text = "Daily Quiz Leaderboard:\n"
        for user_id, score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
            leaderboard_text += f"User {user_id}: {score} points\n"
    await context.bot.send_message(chat_id=CHANNEL_CHAT_ID, text=leaderboard_text)
    context.chat_data["dailyquiz_active"] = False
    context.chat_data["dailyquiz_polls"] = {}
    context.chat_data["dailyquiz_scores"] = {}

async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    answer = update.poll_answer
    poll_id = answer.poll_id
    dailyquiz_polls = context.chat_data.get("dailyquiz_polls", {})
    if poll_id not in dailyquiz_polls:
        return
    correct_option = dailyquiz_polls[poll_id]
    user_id = answer.user.id
    if correct_option in answer.option_ids:
        scores = context.chat_data.setdefault("dailyquiz_scores", {})
        scores[user_id] = scores.get(user_id, 0) + 1





"""   
-------------------------------------------------
 This section manages **non-personal data**.
 Handles logs, metadata, and public API responses.
-------------------------------------------------
"""

async def flashcard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or update.effective_user.id not in AUTHORIZED_USER_IDS:
        return
    prompt = (
        "Generate a GK flashcard for competitive exam preparation in Hindi. "
        "Return the result in JSON format with exactly two keys: "
        "\"question\": string (in Hindi), and \"answer\": string (in Hindi). "
        "Do not include any additional text."
    )
    response = model.generate_content(prompt)
    logger.info(f"Gemini response for flashcard: {response.text}")
    try:
        data = json.loads(clean_response_text(response.text))
    except Exception as e:
        logger.error(f"Error parsing JSON for flashcard: {e}")
        await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                       text="❌ Failed to generate flashcard.")
        return
    question = data.get("question", "Flashcard Question")
    answer = data.get("answer", "Flashcard Answer")
    FLASHCARD_DATA[update.effective_user.id] = {"question": question, "answer": answer}
    await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                   text=f"📇 Flashcard:\n\n*Question:* {question}\n\nUse /flip to reveal the answer.",
                                   parse_mode=ParseMode.MARKDOWN)

async def flip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in FLASHCARD_DATA:
        await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                       text="❌ No flashcard available. Use /flashcard to get one.")
        return
    answer = FLASHCARD_DATA[user_id]["answer"]
    await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                   text=f"📝 Answer: {answer}")

async def fact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or update.effective_user.id not in AUTHORIZED_USER_IDS:
        return
    prompt = (
        "Generate one interesting and concise GK fact in Hindi related to competitive exams in one sentence. "
        "Do not include any extra text."
    )
    response = model.generate_content(prompt)
    logger.info(f"Gemini response for fact: {response.text}")
    fact_text = clean_response_text(response.text)
    await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                   text=f"💡 Fact: {fact_text}")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or update.effective_user.id not in AUTHORIZED_USER_IDS:
        return
    topic = " ".join(context.args) if context.args else ""
    prompt = (
        f"Generate a brief current affairs update in Hindi relevant to competitive exams and GK news. "
        f"{'Include details about ' + topic if topic else ''} "
        "Keep the summary concise and do not include any extra commentary."
    )
    response = model.generate_content(prompt)
    logger.info(f"Gemini response for news{(' on ' + topic) if topic else ''}: {response.text}")
    news_text = clean_response_text(response.text)
    await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                   text=f"📰 News Update:\n{news_text}")

async def alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or update.effective_user.id not in AUTHORIZED_USER_IDS:
        return
    alert_message = (
        "📅 *आगामी परीक्षा सूचना:*\n\n"
        "1. IIT JEE रजिस्ट्रेशन की अंतिम तिथि: 15 मई 2025\n"
        "2. NEET परीक्षा की तिथि: 10 जून 2025\n"
        "3. UPSC प्रारंभिक परीक्षा: 1 अगस्त 2025\n"
        "4. GATE परीक्षा: 20 सितंबर 2025\n"
        "5. CAT परीक्षा: 5 नवम्बर 2025"
    )
    await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                   text=alert_message,
                                   parse_mode=ParseMode.MARKDOWN)

async def leaderboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or update.effective_user.id not in AUTHORIZED_USER_IDS:
        return
    scores = context.chat_data.get("dailyquiz_scores", {})
    if not scores:
        await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                       text="Good luck to all participants for the daily quiz!")
        return
    leaderboard_text = "Daily Quiz Leaderboard:\n"
    for user_id, score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
        leaderboard_text += f"User {user_id}: {score} points\n"
    await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                   text=leaderboard_text,
                                   parse_mode=ParseMode.MARKDOWN)

async def mocktest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or update.effective_user.id not in AUTHORIZED_USER_IDS:
        return
    if not context.args:
        await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                       text="❌ Usage: /mocktest <topic>")
        return
    topic = " ".join(context.args)
    prompt = (
        f"Generate 5 multiple-choice questions for a mock test on the topic '{topic}' for competitive exams. "
        "For each question, provide 4 options and indicate the correct answer. "
        "Ensure that both the question and each option are provided in bilingual format (English | हिंदी). "
        "Return the result as a JSON array of objects. Each object should have the following keys: "
        "\"question\": string (in bilingual format), \"options\": array of exactly 4 strings (each in bilingual format), "
        "and \"correct_index\": integer (0-indexed). "
        "Do not include any extra text."
    )
    response = model.generate_content(prompt)
    logger.info(f"Gemini response for mock test on '{topic}': {response.text}")
    try:
        questions = json.loads(clean_response_text(response.text))
    except Exception as e:
        logger.error(f"Error parsing JSON for mock test: {e}")
        await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                       text="❌ Failed to generate mock test.")
        return
    if not isinstance(questions, list) or len(questions) == 0:
        await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                       text="❌ Mock test generation failed. Please try again.")
        return
    for idx, q in enumerate(questions, start=1):
        q_text = q.get("question", "Question")
        opts = q.get("options", [])
        correct = q.get("correct_index", 0)
        if not isinstance(opts, list) or len(opts) != 4:
            continue
        original_correct_option = opts[correct]
        random.shuffle(opts)
        new_correct = opts.index(original_correct_option)
        answer_line = f"(Correct Answer: Option {new_correct + 1})"
        message = f"*Question {idx}:* {q_text}\n"
        for i, opt in enumerate(opts, start=1):
            message += f"{i}. {opt}\n"
        message += answer_line
        await context.bot.send_message(chat_id=CHANNEL_CHAT_ID,
                                       text=message,
                                       parse_mode=ParseMode.MARKDOWN)








"""
███╗   ███╗██╗   ██╗████████╗██╗   ██╗██████╗ ██╗     ███████╗
████╗ ████║██║   ██║╚══██╔══╝██║   ██║██╔══██╗██║     ██╔════╝
██╔████╔██║██║   ██║   ██║   ██║   ██║██████╔╝██║     █████╗  
██║╚██╔╝██║██║   ██║   ██║   ██║   ██║██╔═══╝ ██║     ██╔══╝  
██║ ╚═╝ ██║╚██████╔╝   ██║   ╚██████╔╝██║     ███████╗███████╗
╚═╝     ╚═╝ ╚═════╝    ╚═╝    ╚═════╝ ╚═╝     ╚══════╝╚══════╝
--------------------------------------------------------------
 This section handles **multiple-question processing**.
 It supports various question formats and dynamic input handling.
--------------------------------------------------------------
"""
async def handle_TQ(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Processes the /TQ command. Expects the message text to contain multiple numbered questions.
    For each question, it uses Gemini to generate a quiz poll and sends that poll to the channel.
    """
    # Check if the user is authorized
    if not update.effective_user or update.effective_user.id not in AUTHORIZED_USER_IDS:
        return

    # Get the full text and remove the command prefix (/TQ)
    full_text = update.message.text
    # Partition the command ("/TQ") from the rest of the text
    text_body = full_text.partition(" ")[2].strip()
    if not text_body:
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="❌ Please provide the questions after /TQ command."
        )
        return

    # Split the text into lines and extract lines that look like numbered questions (e.g., "1. ...")
    lines = text_body.split("\n")
    questions = []
    for line in lines:
        stripped_line = line.strip()
        if re.match(r'^\d+\.', stripped_line):
            # Remove the leading number and dot, then strip again
            question_text = re.sub(r'^\d+\.\s*', '', stripped_line)
            if question_text:
                questions.append(question_text)

    # If no numbered questions found, treat the whole text as one question.
    if not questions:
        questions = [text_body]

    # Process each question one by one.
    for question in questions:
        # Prepare a Gemini prompt. This prompt instructs Gemini to:
        #  - Enhance and rephrase the question into bilingual format (English | हिंदी)
        #  - Generate one correct option and three distractors in random order.
        #  - Return a JSON object with keys: "question", "options", "correct_index"
        prompt = (
            f"Given the following question: \"{question}\", perform the following steps:\n"
            "Step 0: Enhance and rephrase the question to make it more complex, formal, and engaging in format हिंदी.\n"
            "Step 1: Generate one correct option and three incorrect options (distractors) for the enhanced question.\n"
            "Step 2: Randomly shuffle these four options so that the correct answer is not always in the same position.\n"
            "Step 3: Return a JSON object with exactly three keys:\n"
            "  - \"question\": a string representing the enhanced question in bilingual format,\n"
            "  - \"options\": an array of exactly 4 option strings in the final shuffled order,\n"
            "  - \"correct_index\": an integer (0-indexed) indicating the index of the correct answer in the options array.\n"
            "Do not include any additional text or explanation."
        )
        response = model.generate_content(prompt)
        logger.info(f"Gemini response for TQ question '{question}': {response.text}")
        clean_text = clean_response_text(response.text)
        try:
            data = json.loads(clean_text)
        except Exception as e:
            logger.error(f"Error parsing JSON for TQ question '{question}': {e}")
            continue

        # Use Gemini-generated data; if not available, fall back to the original question text.
        generated_question = data.get("question", question)
        options = data.get("options")
        correct_index = data.get("correct_index", 0)
        if not isinstance(options, list) or len(options) != 4:
            logger.error(f"Gemini did not return exactly 4 options for question '{question}'. Skipping.")
            continue
        if not isinstance(correct_index, int) or correct_index < 0 or correct_index >= len(options):
            logger.warning(f"Invalid correct_index for question '{question}'. Defaulting to 0.")
            correct_index = 0

        # Although Gemini is asked to randomize, we can enforce randomness:
        original_correct_option = options[correct_index]
        random.shuffle(options)
        correct_index = options.index(original_correct_option)

        try:
            message = await context.bot.send_poll(
                chat_id=CHANNEL_CHAT_ID,
                question=generated_question[:300],
                options=options,
                is_anonymous=True,
                type='quiz',
                correct_option_id=correct_index
            )
            # Schedule the poll to close after POLL_DURATION seconds.
            context.job_queue.run_once(
                close_poll,
                POLL_DURATION,
                data={"chat_id": CHANNEL_CHAT_ID, "message_id": message.message_id}
            )
        except Exception as e:
            logger.error(f"Error sending TQ quiz poll for question '{question}': {e}")
        # Wait a short time before processing the next question.
        await asyncio.sleep(15)






# ---------------------------Image to Question--------------------------- #
"""
   ██████╗ ██████╗ ███╗   ███╗██╗███╗   ██╗ ██████╗ 
  ██╔════╝██╔═══██╗████╗ ████║██║████╗  ██║██╔════╝ 
  ██║     ██║   ██║██╔████╔██║██║██╔██╗ ██║██║  ███╗
  ██║     ██║   ██║██║╚██╔╝██║██║██║╚██╗██║██║   ██║
  ╚██████╗╚██████╔╝██║ ╚═╝ ██║██║██║ ╚████║╚██████╔╝
   ╚═════╝ ╚═════╝ ╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝ ╚═════╝ 
"""




async def close_poll(context: CallbackContext):
    """Stops the poll and reveals the correct answer."""
    job = context.job
    chat_id = job.data['chat_id']
    message_id = job.data['message_id']
    try:
        await context.bot.stop_poll(chat_id, message_id)
    except Exception as e:
        logger.error(f"Error stopping poll: {e}")


# -------------------- Error Handler -------------------- #
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception:", exc_info=context.error)








# --------------------------- Main Application --------------------------- #
"""
███╗   ███╗ █████╗ ██╗███╗   ██╗
████╗ ████║██╔══██╗██║████╗  ██║
██╔████╔██║███████║██║██╔██╗ ██║
██║╚██╔╝██║██╔══██║██║██║╚██╗██║
██║ ╚═╝ ██║██║  ██║██║██║ ╚████║
╚═╝     ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝
"""

if __name__ == "__main__":
    application = Application.builder() \
        .token(TELEGRAM_BOT_TOKEN) \
        .post_init(lambda app: app.bot.set_my_commands(commands_list)) \
        .build()

    # Conversation handler for interactive polls (for /poll in channel).
    poll_conv = ConversationHandler(
        entry_points=[CommandHandler('poll', start_poll_channel)],
        states={
            POLL_TYPE: [MessageHandler(filters.TEXT, receive_poll_type_channel)],
            POLL_QUESTION: [MessageHandler(filters.TEXT, receive_question_channel)],
            POLL_OPTIONS: [MessageHandler(filters.TEXT, receive_options_channel)],
            POLL_CORRECT: [MessageHandler(filters.TEXT, receive_correct_option_channel)]
        },
        fallbacks=[]
    )

    # Conversation handler for daily quiz.
    dailyquiz_conv = ConversationHandler(
        entry_points=[CommandHandler("dailyquiz", start_dailyquiz)],
        states={
            DAILYQUIZ_TOPIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_dailyquiz_topic)],
            DAILYQUIZ_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_dailyquiz_count)]
        },
        fallbacks=[CommandHandler("stop", stop_dailyquiz)]
    )

    # Personal command handlers.
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("auth", auth))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("search", search))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    application.add_handler(CommandHandler("subscriptions", subscriptions_cmd))
    application.add_handler(CommandHandler("announce", announce))

    # Add the poll conversation handler.
    application.add_handler(poll_conv)

    # Add the daily quiz conversation handler.
    application.add_handler(dailyquiz_conv)

    # Also add a global /stop command so that if the daily quiz is running, /stop stops it.
    application.add_handler(CommandHandler("stop", stop_dailyquiz))

    # Auto-generated quiz polls for simple text questions.
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_auto_quiz))

    # Non-personal command handlers (send to channel).
    application.add_handler(CommandHandler("flashcard", flashcard))
    application.add_handler(CommandHandler("flip", flip))
    application.add_handler(CommandHandler("fact", fact))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("alerts", alerts))
    application.add_handler(CommandHandler("leaderboard", leaderboard_cmd))
    application.add_handler(CommandHandler("mocktest", mocktest))
    application.add_handler(CommandHandler("TQ", handle_TQ))
    # application.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_IQ))
    

    # Poll answer handler for daily quiz scoring.
    application.add_handler(PollAnswerHandler(poll_answer_handler))

    application.add_error_handler(error_handler)

    application.run_polling()
