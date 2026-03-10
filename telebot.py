import telegram
import logging
import asyncio
from collections import Counter
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURATION ---
# IMPORTANT: Replace "YOUR_TELEGRAM_BOT_TOKEN" with the token you get from BotFather on Telegram.
TELEGRAM_BOT_TOKEN = "8375508549:AAHivOSKoSP93J0R1XeboxxcacHbevH4MFk"

# --- GAME SETTINGS ---
MIN_PLAYERS_TO_START = 3  # Minimum number of players required for the game to start.
WAIT_TIME_SECONDS = 90    # Initial time for players to join the game (1.5 minutes).
ROUND_TIME_SECONDS = 60   # Time players have to submit their number each round.
ELIMINATION_SCORE = -5    # Score at which a player is eliminated.

# --- GLOBAL STATE MANAGEMENT ---
# This dictionary will hold the state of all games running in different group chats.
# Key: chat_id, Value: game state object
games = {}
# This dictionary maps a player's user_id to the chat_id of the game they are in.
# This helps the bot know where to route private messages.
player_to_game_map = {}

# --- LOGGING SETUP ---
# This helps in debugging by printing information to your console.
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# --- HELPER & UTILITY FUNCTIONS ---
async def send_message_to_chat(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str):
    """A helper function to safely send messages to a chat."""
    try:
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Error sending message to {chat_id}: {e}")

# --- COMMAND HANDLERS ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command, sent when a user first interacts with the bot."""
    await update.message.reply_text(
        "Welcome! I am the King of Diamonds Bot.\n"
        "Add me to a group chat and use /start_game to begin a new match.\n"
        "Use /rules to see how to play."
    )

async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /rules command to explain the game."""
    rules_text = (
        "<b>♦️ King of Diamonds: Rules ♦️</b>\n\n"
        "This is a game of logic and wits.\n\n"
        "1. Each round, all players secretly choose a number between 0 and 100.\n"
        "2. The average of all numbers is calculated and multiplied by 0.8. This is the 'Target Number'.\n"
        "3. The player whose number is closest to the Target Number wins the round and is safe.\n"
        "4. All other players lose 1 point.\n"
        f"5. If your score reaches {ELIMINATION_SCORE}, you are <b>ELIMINATED</b>.\n\n"
        "<b>🚨 SPECIAL RULE 🚨</b>\n"
        "If two or more players choose the same number, and that number is NOT the winning number, all players who chose it are <b>IMMEDIATELY ELIMINATED</b>.\n\n"
        "The last player standing wins. Good luck."
    )
    await update.message.reply_text(rules_text, parse_mode='HTML')

async def start_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Starts a new game in the group chat."""
    chat_id = update.message.chat_id
    if chat_id in games:
        await update.message.reply_text("A game is already in progress in this chat!")
        return

    games[chat_id] = {
        "status": "waiting",
        "players": {},
        "round": 0,
        "timer": None
    }

    # =================================================================================
    # ✨✨✨ VIDEO INTEGRATION POINT ✨✨✨
    # This is where you send a video to welcome players to the game.
    # Replace 'path/to/your/welcome_video.mp4' with the actual file path or a public URL.
    try:
        if ("sending local file"):
            with open('document_6260367227120262997.mp4', 'rb') as video:
                await context.bot.send_video(chat_id=chat_id, video=video)

        # If sending a URL (replace with your video's URL):
        await context.bot.send_video(
            chat_id=chat_id, 
            video="https://file-examples.com/storage/fe92e8a57762a874b59560f/2017/04/file_example_MP4_480_1_5MG.mp4"
        )
        logger.info("Welcome video sent successfully.")
    except Exception as e:
        logger.error(f"Could not send welcome video: {e}")
        await update.message.reply_text("<i>(Imagine a cool intro video here)</i>", parse_mode='HTML')
    # =================================================================================

    timer_job = context.job_queue.run_once(
        start_game_auto,
        WAIT_TIME_SECONDS,
        chat_id=chat_id,
        name=f"start_{chat_id}"
    )
    games[chat_id]['timer'] = timer_job

    await update.message.reply_text(
        f"<b>♦️ A new game of King of Diamonds has started! ♦️</b>\n\n"
        f"Players can now join. Use the <code>/join_game</code> command.\n\n"
        f"The game will automatically begin in {WAIT_TIME_SECONDS} seconds.",
        parse_mode='HTML'
    )

async def join_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Allows a player to join a game that is in the 'waiting' state."""
    chat_id = update.message.chat_id
    user = update.message.from_user
    
    if chat_id not in games:
        await update.message.reply_text("No game is currently waiting for players in this chat.")
        return
    if games[chat_id]['status'] != 'waiting':
        await update.message.reply_text("You can't join right now, the game has already started!")
        return
    if user.id in games[chat_id]['players']:
        await update.message.reply_text("You're already in the game!")
        return

    games[chat_id]['players'][user.id] = {
        "username": user.first_name,
        "score": 0,
        "choice": None
    }
    player_to_game_map[user.id] = chat_id
    
    player_list = "\n".join([p['username'] for p in games[chat_id]['players'].values()])
    await update.message.reply_text(
        f"{user.first_name} has joined the game!\n\n"
        f"<b>Current Players:</b>\n{player_list}",
        parse_mode='HTML'
    )

async def leave_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Allows a player to leave the game."""
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    username = update.message.from_user.first_name

    if chat_id not in games or user_id not in games[chat_id]['players']:
        await update.message.reply_text("You are not currently in a game in this chat.")
        return

    del games[chat_id]['players'][user_id]
    if user_id in player_to_game_map:
        del player_to_game_map[user_id]

    await update.message.reply_text(f"{username} has left the game.")
    
    if games[chat_id]['status'] == "running" and len(games[chat_id]['players']) < 2:
        await check_game_over(context, chat_id)


async def extend_wait_time_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Extends the waiting time for players to join."""
    chat_id = update.message.chat_id
    if chat_id not in games or games[chat_id]['status'] != 'waiting':
        await update.message.reply_text("There is no game waiting to be extended.")
        return

    # Remove the old timer and set a new one
    old_job = games[chat_id]['timer']
    if old_job:
        old_job.schedule_removal()

    new_timer_job = context.job_queue.run_once(
        start_game_auto,
        WAIT_TIME_SECONDS,
        chat_id=chat_id,
        name=f"start_{chat_id}"
    )
    games[chat_id]['timer'] = new_timer_job
    await update.message.reply_text(f"The waiting time has been extended by {WAIT_TIME_SECONDS} seconds!")


# --- GAME LOGIC ---
async def start_game_auto(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Automatically starts the game after the wait time if enough players have joined."""
    job = context.job
    chat_id = job.chat_id
    
    if chat_id not in games:
        return # Game was cancelled or ended prematurely

    player_count = len(games[chat_id]['players'])
    if player_count < MIN_PLAYERS_TO_START:
        await send_message_to_chat(
            context,
            chat_id,
            f"Not enough players joined. The game requires at least {MIN_PLAYERS_TO_START} players.\nGame cancelled."
        )
        del games[chat_id]
        return

    games[chat_id]['status'] = 'running'
    await send_message_to_chat(
        context,
        chat_id,
        "The time is up! The game is now starting..."
    )
    await start_new_round(context, chat_id)

async def start_new_round(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Initiates a new round of the game."""
    if chat_id not in games or games[chat_id]['status'] != 'running':
        return

    game = games[chat_id]
    game['round'] += 1

    # Reset choices for the new round
    for player_id in game['players']:
        game['players'][player_id]['choice'] = None

    scoreboard = "<b>Current Scores:</b>\n"
    for player in game['players'].values():
        scoreboard += f"{player['username']}: {player['score']}\n"
    
    context.job_queue.run_once(
        end_round,
        ROUND_TIME_SECONDS,
        chat_id=chat_id,
        name=f"end_round_{chat_id}"
    )

    await send_message_to_chat(
        context,
        chat_id,
        f"<b>♦️ Round {game['round']} has begun! ♦️</b>\n\n"
        f"{scoreboard}\n"
        f"All players, please send me your chosen number (0-100) in a <b>private message</b>.\n\n"
        f"You have {ROUND_TIME_SECONDS} seconds.",
    )

async def end_round(context: ContextTypes.DEFAULT_TYPE):
    """Ends the current round, calculates results, and checks for eliminations."""
    job = context.job
    chat_id = job.chat_id
    
    if chat_id not in games or games[chat_id]['status'] != 'running':
        return

    game = games[chat_id]
    await send_message_to_chat(context, chat_id, f"<b>Round {game['round']} has ended!</b> Calculating results...")
    await asyncio.sleep(2)

    players = game['players']
    submitted_choices = {pid: p['choice'] for pid, p in players.items() if p['choice'] is not None}
    eliminated_this_round = {} # {pid: "reason"}
    
    # --- Round Calculation ---
    round_summary = ""
    if not submitted_choices:
        round_summary = "No one submitted a number. Everyone loses 1 point."
        for pid in players:
            players[pid]['score'] -= 1
    else:
        # Step 1: Calculate target number
        average = sum(submitted_choices.values()) / len(submitted_choices)
        target = average * 0.8
        
        # Step 2: Find the winning number
        winning_number = min(submitted_choices.values(), key=lambda x: abs(x - target))
        winners = {pid for pid, choice in submitted_choices.items() if choice == winning_number}
        
        round_summary = (
            f"<b>Choices:</b> {', '.join([f'{p["username"]}: {p["choice"] if p["choice"] is not None else "N/A"}' for p in players.values()])}\n"
            f"Average of choices: {average:.2f}\n"
            f"Target Number (Average * 0.8): <b>{target:.2f}</b>\n"
            f"Winning Number (Closest Choice): <b>{winning_number}</b>\n\n"
            f"🏆 <b>Round Winner(s):</b> {', '.join([players[pid]['username'] for pid in winners])}"
        )

        # Step 3: Check for special elimination rule
        choice_counts = Counter(submitted_choices.values())
        duplicate_choices = {num for num, count in choice_counts.items() if count > 1 and num != winning_number}
        
        if duplicate_choices:
            for pid, pdata in list(players.items()):
                if pdata['choice'] in duplicate_choices:
                    eliminated_this_round[pid] = f"eliminated by special rule (chose {pdata['choice']})."

        # Step 4: Apply penalties to non-winners
        for pid in players:
            if pid not in winners and pid not in eliminated_this_round:
                if players[pid]['choice'] is None:
                    players[pid]['score'] -= 2 # Harsher penalty for not choosing
                else:
                    players[pid]['score'] -= 1

    # Step 5: Check for score-based eliminations and process all eliminations
    elimination_messages = []
    for pid, pdata in list(players.items()):
        if pid in eliminated_this_round:
            elimination_messages.append(f"☠️ {pdata['username']} has been {eliminated_this_round[pid]}")
        elif pdata['score'] <= ELIMINATION_SCORE:
            elimination_messages.append(f"☠️ {pdata['username']} has been eliminated for reaching a score of {pdata['score']}.")
            eliminated_this_round[pid] = "score elimination"

    await send_message_to_chat(context, chat_id, round_summary)
    await asyncio.sleep(2)
    
    if elimination_messages:
        full_elim_msg = "\n".join(elimination_messages)
        await send_message_to_chat(context, chat_id, full_elim_msg)

        for pid in eliminated_this_round:
            if pid in players:
                # =========================================================================
                # ✨✨✨ VIDEO INTEGRATION POINT ✨✨✨
                # This is where you send a video when a player is eliminated.
                try:
                    Replace ('document_6260367227120262761.mp4')
                    await context.bot.send_video(
                         chat_id=chat_id,
                         video="https://file-examples.com/storage/fe92e8a57762a874b59560f/2017/04/file_example_MP4_480_1_5MG.mp4"
                    )
                    logger.info(f"Elimination video sent for user {pid}")
                except Exception as e:
                    logger.error(f"Could not send elimination video: {e}")
                    await send_message_to_chat(context, chat_id, f"<i>(Imagine {players[pid]['username']} getting eliminated dramatically)</i>")
                # =========================================================================
                del players[pid]
                if pid in player_to_game_map:
                    del player_to_game_map[pid]
                await asyncio.sleep(1)

    # --- Check for Game Over ---
    if not await check_game_over(context, chat_id):
        # If the game is not over, start the next round
        await asyncio.sleep(3)
        await start_new_round(context, chat_id)

async def check_game_over(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
    """Checks if the game has ended and announces the winner. Returns True if game is over."""
    if chat_id not in games:
        return True
        
    players = games[chat_id]['players']
    
    if len(players) <= 1:
        if len(players) == 1:
            winner = list(players.values())[0]
            await send_message_to_chat(
                context,
                chat_id,
                f"<b>GAME OVER!</b>\n\n🎉 The final survivor and winner is <b>{winner['username']}</b>! Congratulations! 🎉"
            )
        else:
            await send_message_to_chat(context, chat_id, "<b>GAME OVER!</b>\n\nEveryone has been eliminated. There is no winner.")
        
        # Clean up game state
        for pid in list(players.keys()):
            if pid in player_to_game_map:
                del player_to_game_map[pid]
        del games[chat_id]
        return True
    return False

# --- MESSAGE HANDLER (for private messages) ---
async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles number submissions from players in private chat."""
    user = update.message.from_user
    text = update.message.text

    if user.id not in player_to_game_map:
        await update.message.reply_text("You are not currently in an active game.")
        return

    chat_id = player_to_game_map[user.id]
    game = games.get(chat_id)

    if not game or game['status'] != 'running':
        await update.message.reply_text("The game is not currently in a running round.")
        return

    if game['players'][user.id]['choice'] is not None:
        await update.message.reply_text("You have already submitted your number for this round.")
        return

    try:
        number = int(text)
        if 0 <= number <= 100:
            game['players'][user.id]['choice'] = number
            await update.message.reply_text(f"Your choice of <b>{number}</b> has been recorded. Good luck.", parse_mode='HTML')
            logger.info(f"User {user.id} in chat {chat_id} chose {number}")
        else:
            await update.message.reply_text("Invalid number. Please choose a number between 0 and 100.")
    except ValueError:
        await update.message.reply_text("That's not a valid number. Please send only a number (e.g., 42).")

# --- MAIN FUNCTION ---
def main() -> None:
    """Start the bot."""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("rules", rules_command))
    application.add_handler(CommandHandler("start_game", start_game_command, filters=filters.ChatType.GROUPS))
    application.add_handler(CommandHandler("join_game", join_game_command, filters=filters.ChatType.GROUPS))
    application.add_handler(CommandHandler("leave_game", leave_game_command, filters=filters.ChatType.GROUPS))
    application.add_handler(CommandHandler("extend_wait_time", extend_wait_time_command, filters=filters.ChatType.GROUPS))

    # Message handler for private chats to get player choices
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_private_message))

    # Run the bot until the user presses Ctrl-C
    logger.info("Bot is starting...")
    application.run_polling()
    logger.info("Bot has stopped.")

if __name__ == "__main__":
    main()
