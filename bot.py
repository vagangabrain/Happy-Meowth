import os
import discord
import asyncio
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient
from predict import Prediction

TOKEN = os.getenv("DISCORD_TOKEN")
MONGODB_URI = os.getenv("MONGODB_URI")

# Bot setup with command prefix
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='m!', intents=intents, help_command=None)

# Global variables for database and predictor
db_client = None
db = None
predictor = None

async def initialize_predictor():
    """Initialize the predictor asynchronously"""
    global predictor
    try:
        predictor = Prediction()
        print("Predictor initialized successfully")
    except Exception as e:
        print(f"Failed to initialize predictor: {e}")

async def initialize_database():
    """Initialize MongoDB connection"""
    global db_client, db
    try:
        if not MONGODB_URI:
            print("Warning: MONGODB_URI not set, collection features disabled")
            return

        print(f"Attempting to connect to MongoDB...")
        print(f"URI starts with: {MONGODB_URI[:30]}...")

        # Try different TLS configurations for Railway compatibility
        tls_configs = [
            {
                "serverSelectionTimeoutMS": 5000,
                "connectTimeoutMS": 10000,
                "socketTimeoutMS": 20000,
                "maxPoolSize": 1
            },
            {
                "tls": True,
                "tlsAllowInvalidCertificates": True,
                "serverSelectionTimeoutMS": 5000,
                "connectTimeoutMS": 10000,
                "socketTimeoutMS": 20000,
                "maxPoolSize": 1
            },
            {
                "tls": True,
                "tlsInsecure": True,
                "serverSelectionTimeoutMS": 5000,
                "connectTimeoutMS": 10000,
                "socketTimeoutMS": 20000,
                "maxPoolSize": 1
            }
        ]

        for i, config in enumerate(tls_configs, 1):
            try:
                print(f"Trying TLS configuration {i}: {list(config.keys())}")
                db_client = AsyncIOMotorClient(MONGODB_URI, **config)
                await asyncio.wait_for(db_client.admin.command('ping'), timeout=5)
                db = db_client.pokemon_collector
                print(f"✅ Database initialized successfully with configuration {i}")
                return
            except asyncio.TimeoutError:
                print(f"❌ Config {i} failed: Connection timeout")
            except Exception as e:
                print(f"❌ Config {i} failed: {str(e)[:100]}...")

            if 'db_client' in locals() and db_client:
                db_client.close()
            db_client = None
            db = None

        print("❌ All TLS configurations failed - database features will be disabled")

    except Exception as e:
        print(f"❌ Critical error in database initialization: {e}")
        db_client = None
        db = None

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    if predictor is None:
        await initialize_predictor()

    if db is None:
        await initialize_database()

    # Load cogs
    await bot.load_extension('cogs.general')
    await bot.load_extension('cogs.collection')
    print("All cogs loaded successfully")

@bot.event
async def on_message_edit(before, after):
    """Event handler for when a message is edited"""
    # Ignore bot messages
    if after.author.bot:
        return

    # Ignore if message content hasn't changed (e.g., just an embed update)
    if before.content == after.content:
        return

    # Process the edited message as if it were a new command
    # This allows commands to work in edited messages
    await bot.process_commands(after)

def main():
    if not TOKEN:
        print("Error: DISCORD_TOKEN environment variable not set")
        return

    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        print("Error: Invalid Discord token")
    except Exception as e:
        print(f"Error starting bot: {e}")

if __name__ == "__main__":
    main()
