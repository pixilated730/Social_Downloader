# config.py
import yaml
import dotenv
from pathlib import Path

config_dir = Path(__file__).parent.parent.resolve() / "config"

# load yaml config
with open(config_dir / "config.yml", 'r') as f:
    config_yaml = yaml.safe_load(f)

with open(config_dir / "domains.yml", 'r') as d:
    domains = yaml.safe_load(d)

# load .env config
config_env = dotenv.dotenv_values(config_dir / "config.env")

# Load mongodb_uri from either config.yaml or config.env
mongodb_uri = config_yaml.get("mongodb_uri") or config_env.get("MONGODB_URI")

# Check if mongodb_uri is set
if not mongodb_uri:
    raise ValueError("MongoDB URI not set in config files")

telegram_token = config_yaml.get("telegram_token")
# admin
channel_admin_id = config_yaml.get("channel_admin")
admin_chat_id = config_yaml.get("admin_chat_id")
admin_usernames = config_yaml.get("admin_usernames")

download_dir = "downloads"