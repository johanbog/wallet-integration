import os
import smtplib
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart

import polars as pl

from wallet.config import ACCOUNTS

sender_email = os.environ.get("SEND_EMAIL")
password = os.environ.get("SEND_EMAIL_PASSWORD")


def send(df: pl.DataFrame, account_group: str) -> None:
    assert sender_email
    assert password
    receiver_email = ACCOUNTS[account_group]["mail"]

    msg = MIMEMultipart()
    msg["Subject"] = "send to wallet"
    msg["From"] = sender_email
    msg["To"] = receiver_email
    filename = f"temp_{account_group}.csv"
    df.to_csv(filename)
    with open(filename, "rb") as att:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(att.read())
    os.remove(filename)
    part.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(part)

    with smtplib.SMTP("smtp.mail.yahoo.com", 587) as server:
        server.starttls()
        server.login(sender_email, password)
        server.sendmail(sender_email, receiver_email, msg.as_bytes())
