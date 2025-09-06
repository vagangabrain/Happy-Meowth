import os
import discord
import asyncio
import aiohttp
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
http_session = None

async def initialize_predictor():
    """Initialize the predictor asynchronously"""
    global predictor
    try:
        predictor = Prediction()
        print("Predictor initialized successfully")
    except Exception as e:
        print(f"Failed to initialize predictor: {e}")

async def initialize_database():
    """Initialize MongoDB connection with optimized settings"""
    global db_client, db
    try:
        if not MONGODB_URI:
            print("Warning: MONGODB_URI not set, collection features disabled")
            return

        print(f"Attempting to connect to MongoDB...")

        # Optimized connection settings for Railway/Atlas
        connection_config = {
            "serverSelectionTimeoutMS": 3000,  # Reduced from 5000
            "connectTimeoutMS": 5000,          # Reduced from 10000
            "socketTimeoutMS": 10000,          # Reduced from 20000
            "maxPoolSize": 10,                 # Increased for better concurrency
            "minPoolSize": 1,                  # Keep some connections alive
            "maxIdleTimeMS": 30000,           # Keep connections alive longer
            "retryWrites": True,
            "w": "majority"
        }

        print("Connecting with optimized settings...")
        db_client = AsyncIOMotorClient(MONGODB_URI, **connection_config)

        # Test connection with shorter timeout
        await asyncio.wait_for(db_client.admin.command('ping'), timeout=3)
        db = db_client.pokemon_collector
        print("✅ Database initialized successfully")

        # Create indexes for better performance
        await create_database_indexes()

    except asyncio.TimeoutError:
        print("❌ Database connection timeout - database features disabled")
        db_client = None
        db = None
    except Exception as e:
        print(f"❌ Database connection failed: {str(e)[:100]} - database features disabled")
        db_client = None
        db = None

async def create_database_indexes():
    """Create database indexes for better query performance"""
    if db is None:
        return

    try:
        # Index for collections
        await db.collections.create_index([("user_id", 1), ("guild_id", 1)])
        await db.collections.create_index("pokemon")

        # Index for shiny hunts
        await db.shiny_hunts.create_index([("user_id", 1), ("guild_id", 1)])
        await db.shiny_hunts.create_index("pokemon")

        # Index for AFK users
        await db.collection_afk_users.create_index([("user_id", 1), ("guild_id", 1)])
        await db.shiny_hunt_afk_users.create_index([("user_id", 1), ("guild_id", 1)])

        # Index for rare pings
        await db.rare_pings.create_index([("user_id", 1), ("guild_id", 1)])

        # Index for guild settings
        await db.guild_settings.create_index("guild_id")

        print("✅ Database indexes created")
    except Exception as e:
        print(f"Warning: Could not create indexes: {e}")

async def initialize_http_session():
    """Initialize aiohttp session for async HTTP requests"""
    global http_session

    # Configure session with optimized settings
    timeout = aiohttp.ClientTimeout(total=10, connect=3)  # Shorter timeouts
    connector = aiohttp.TCPConnector(
        limit=100,          # Connection pool limit
        limit_per_host=10,  # Per-host limit
        keepalive_timeout=30,
        enable_cleanup_closed=True
    )

    http_session = aiohttp.ClientSession(
        timeout=timeout,
        connector=connector,
        headers={
            'User-Agent': 'Pokemon-Helper-Bot/1.0'
        }
    )
    print("✅ HTTP session initialized")

async def keep_alive():
    """Keep Railway container alive by making periodic requests"""
    while True:
        try:
            await asyncio.sleep(240)  # 4 minutes (Railway sleeps after 5 min)
            # Simple internal ping to keep container active
            if http_session:
                async with http_session.get('https://httpbin.org/status/200') as resp:
                    pass  # Just make a request to stay alive
        except Exception:
            pass  # Ignore errors in keep-alive

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    # Initialize components in parallel where possible
    await initialize_http_session()

    initialization_tasks = [
        initialize_predictor(),
        initialize_database()
    ]

    await asyncio.gather(*initialization_tasks, return_exceptions=True)

    # Load cogs
    try:
        await bot.load_extension('cogs.general')
        await bot.load_extension('cogs.collection')
        print("All cogs loaded successfully")
    except Exception as e:
        print(f"Error loading cogs: {e}")

    # Start keep-alive task for Railway
    asyncio.create_task(keep_alive())

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
    await bot.process_commands(after)

async def cleanup():
    """Clean up resources on shutdown"""
    global http_session, db_client

    if http_session:
        await http_session.close()

    if db_client:
        db_client.close()

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
    finally:
        # Cleanup resources
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(cleanup())
        except:
            pass

if __name__ == "__main__":
    main()
