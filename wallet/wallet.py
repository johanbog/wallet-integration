import json
import os
from datetime import datetime
from functools import lru_cache
from typing import Any, Literal, Optional, Union

import patito as pt
import polars as pl
import requests
from dotenv import load_dotenv

load_dotenv()

access_token = os.environ.get("ACCESS_TOKEN")
URL_BASE = "https://api.sparebank1.no/personal/banking"
headers = {
    "accept": "application/vnd.sparebank1.v1+json;charset=utf-8",
    "Authorization": f"Bearer {access_token}",
}

IGNORE_ACCOUNTS = "Bogen-fond"


class Account(pt.Model):
    key: str
    name: str
    number: Optional[int]

    def __init__(self, accountNumber: Union[str, int], **data):
        if accountNumber == "K1955118490":
            accountNumber = 42024603940
            data["name"] = "Johannes Credit Card"
        super().__init__(number=accountNumber, **data)


class Transaction(pt.Model):
    accountName: str
    description: Optional[str]
    amount: float
    remoteAccountNumber: Optional[int]
    date: Optional[datetime]

    def __init__(
        self,
        date: int,
        description: Optional[str] = None,
        remoteAccountNumber: Optional[int] = None,
        **data: Any,
    ) -> None:
        parsed_date = datetime.fromtimestamp(int(date / 1000))
        if description is None and remoteAccountNumber is not None:
            description = (
                f"Transfer to/from {Wallet.account_from_number(remoteAccountNumber)}"
            )
        super().__init__(date=parsed_date, description=description, **data)

    class Config:
        frozen = True

    @property
    @lru_cache()
    def remote_account(self) -> Optional[Account]:
        if not self.remoteAccountNumber:
            return
        return Wallet.account_from_number(self.remoteAccountNumber)


class Wallet:
    def __init__(self) -> None:
        pass

    @classmethod
    def url(cls, t: Literal["accounts", "transactions"], **kwargs) -> str:
        _url = f"{URL_BASE}/{t}"
        if kwargs:
            _url += "?" + "&".join([f"{key}={value}" for key, value in kwargs.items()])
        return _url

    @classmethod
    @lru_cache
    def accounts(cls) -> tuple[Account]:
        accounts_raw = cls.request(cls.url("accounts", includeCreditCardAccounts=True))[
            "accounts"
        ]
        return tuple(Account(**acc) for acc in accounts_raw if acc["name"])

    @classmethod
    def account_from_number(cls, number: Optional[int]) -> Optional[Account]:
        for account in cls.accounts():
            if account.number == number:
                return account
        return

    @classmethod
    @lru_cache
    def transactions(cls, account: Account, **kwargs) -> pl.DataFrame:
        url = cls.url("transactions", accountKey=account.key, **kwargs)
        transactions_raw = cls.request(url)["transactions"]
        return transactions_raw

    @classmethod
    def request(cls, url: str) -> dict:
        response = requests.get(url, headers=headers)
        if response.ok:
            return json.loads(response.text)
        raise ValueError(url, response)
