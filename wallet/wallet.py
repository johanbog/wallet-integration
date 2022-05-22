import json
import os
from datetime import datetime
from functools import lru_cache
from typing import Any, Literal, Optional, Union

import patito as pt
import polars as pl
import requests
from dotenv import load_dotenv
import pandas as pd

load_dotenv()

access_token = os.environ.get("ACCESS_TOKEN")
URL_BASE = "https://api.sparebank1.no/personal/banking"
headers = {
    "accept": "application/vnd.sparebank1.v1+json;charset=utf-8",
    "Authorization": f"Bearer {access_token}",
}

IGNORE_ACCOUNTS = "Bogen-fond"
ACCOUNTS = {
    "Johannes": {
        "mail": os.environ.get("MAIL_JOHANNES"),
        "accounts": [
            "Johannes",
            "Johannes Credit Card",
        ],
    },
    "Family": {
        "mail": os.environ.get("MAIL_FAMILY"),
        "accounts": [
            "Family Shared Expenses",
            "Household Income",
            "BOLIGSPARING FOR UNGDOM",
            "SPAREKONTO",
        ],
    },
    "Minji": {
        "mail": os.environ.get("MAIL_MINJI"),
        "accounts": [
            "Minji Song",
        ],
    },
}


class Account(pt.Model):
    key: str
    name: str
    number: Optional[int]

    def __init__(self, accountNumber: Union[str, int], **data):
        if accountNumber == "K1955118490":
            accountNumber = 42024603940
            data["name"] = "Johannes Credit Card"
            print(data)
        super().__init__(number=accountNumber, **data)


class Transaction(pt.Model):
    name: str
    description: Optional[str]
    amount: float = pt.Field(dtype=pl.Float32)
    remoteAccountNumber: Optional[int]
    date: datetime = pt.Field(dtype=pl.Date)

    class Config:
        frozen = True

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

    @property
    @lru_cache()
    def remote_account(self) -> Optional[Account]:
        if not self.remoteAccountNumber:
            return
        return Wallet.account_from_number(self.remoteAccountNumber)


class Wallet:
    test = False

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

    @classmethod
    def account_from_name(cls, name: str) -> Optional[Account]:
        for account in cls.accounts():
            if account.name == name:
                return account

    @classmethod
    @lru_cache
    def transactions(cls, account: Account, **kwargs) -> pt.DataFrame:
        url = cls.url("transactions", accountKey=account.key, **kwargs)
        transactions = pd.DataFrame(cls.request(url)["transactions"])

        transactions = transactions.reindex(sorted(transactions.columns), axis=1)
        df = Transaction.DataFrame(transactions)
        if not df.is_empty():
            df = (
                df.with_column(
                    (pl.col("date") // 1000)
                    .apply(datetime.fromtimestamp)
                    .apply(datetime.date)
                )
                .drop()
                .cast()
                .with_column(pl.lit(account.name).alias("name"))
            )
        return df

    @classmethod
    def request(cls, url: str) -> dict:
        response = requests.get(url, headers=headers)
        if response.ok:
            return json.loads(response.text)
        raise ValueError(url, response)

    @classmethod
    def send_email(cls, account_group: str, from_date: str) -> pl.DataFrame:
        transactions = []
        for account_name in ACCOUNTS[account_group]["accounts"]:
            account = cls.account_from_name(account_name)
            assert account is not None
            df = cls.transactions(account, fromDate=from_date)
            if not df.is_empty():
                transactions.append(df)
        df = clean_data(pl.concat(transactions))
        return df


def get_transfer_account(number: int) -> Optional[str]:
    acct = Wallet.account_from_number(number)
    if acct:
        if acct.name in IGNORE_ACCOUNTS:
            return f"Payment t/f {acct.name}"
        return f"Transfer t/f {acct.name}"


def clean_data(df: pl.DataFrame) -> pl.DataFrame:
    if df.is_empty():
        return df
    return (
        df.with_column(
            pl.when(
                pl.col("remoteAccountNumber").apply(get_transfer_account).is_not_null()
            )
            .then(pl.col("remoteAccountNumber").apply(get_transfer_account))
            .otherwise(pl.col("description"))
            .alias("description"),
        )
    ).rename(
        {
            "remoteAccountNumber": "payee",
            "description": "note",
            "name": "tag",
        }
    )
