# YourSocialDownloaderBOT: **Fast. No daily limit. & Reliable**

```Created By pixilated```

## Features
⚡ Features:
• Fast downloads
• High quality videos
• Multiple platform support
• Progress tracking

## Bot commands
- `/start` - Start the bot
- `/cancle` – Cancle a ongoing download  
- `/help` – Show help menu
- `/stats` - Show stats download 

## Run On Docker 

1. Get your Telegram bot token from [@BotFather](https://t.me/BotFather)

2. Edit `config/config.example.yml` to set your tokens and run 2 commands below (*if you're advanced user, you can also edit* `config/config.example.env`):
```bash
mv conf/config.yml config/
mv conf/config.env config/
```

🔥 And now **run**:

```bash
docker compose --env-file config/config.env up --build
```

## Quick Run 

1. Get your Telegram bot token from [@BotFather](https://t.me/BotFather)

2. Edit `conf/config.yml` to set your tokens and run 2 commands below (*if you're advanced user, you can also edit* `conf/config.env`):
```bash
mkdir config
mv conf/config.yml config/
mv config/config.env config/
python3 -m venv venv && source venv/bin/activate
python3 run.py
``` 