from dotenv import load_dotenv
import discord
import logging
import os
import sys

logger = logging.getLogger(__name__)

# Load .env file for basic configuration
load_dotenv()

# Fetch our token
token = os.getenv('DISCORD_TOKEN')
if token is None:
    logger.error('Failed to get discord token! Set DISCORD_TOKEN in .env!')
    sys.exit(1)

intents = discord.Intents.default()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    logger.info(f'Logged in as {client.user}')

client.run(token)

