import os
from abc import ABC
from typing import Final
from dotenv import load_dotenv  # <-- Import this

# Load variables from .env file
load_dotenv()  # <-- Call this before accessing environment variables

class EnvKeys(ABC):
    TOKEN: Final = os.environ.get('TOKEN')
    OWNER_ID: Final = os.environ.get('OWNER_ID')
    ACCESS_TOKEN: Final = os.environ.get('ACCESS_TOKEN')
    ACCOUNT_NUMBER: Final = os.environ.get('ACCOUNT_NUMBER')

    BLOCKCYPHER_TOKEN: Final = os.environ.get('BLOCKCYPHER_TOKEN')

    SHK_API_KEY: Final = os.environ.get('SHK_API_KEY')
    SHK_MERCHANT_ID: Final = os.environ.get('SHK_MERCHANT_ID')
    NOWPAYMENTS_API_KEY: Final = os.environ.get('NOWPAYMENTS_API_KEY', 'PHXJH8R-3F3MRDT-M28PW7S-E0MV698')

    NOWPAYMENTS_IPN_URL: Final = os.environ.get('NOWPAYMENTS_IPN_URL')
    NOWPAYMENTS_IPN_SECRET: Final = os.environ.get('NOWPAYMENTS_IPN_SECRET')

