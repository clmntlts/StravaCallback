"""Envoi email (SMTP Gmail, stdlib) avec corps HTML + pièces jointes.

Chemin déterministe et headless : ne dépend d'aucun connecteur. Auth par
variables d'environnement (jamais commitées) :

    GMAIL_ADDRESS       adresse d'envoi (compte Gmail)
    GMAIL_APP_PASSWORD  mot de passe d'application Google (16 car.)
    MAIL_TO             destinataire (défaut : GMAIL_ADDRESS)

Un mot de passe d'application se crée sur https://myaccount.google.com/apppasswords
(nécessite la validation en 2 étapes). Alternative : le connecteur Gmail peut
être utilisé directement au runtime par l'agent, sans ce module.
"""

from __future__ import annotations

import mimetypes
import os
import smtplib
from email.message import EmailMessage
from typing import List, Optional

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def _guess_mime(path: str):
    ctype, _ = mimetypes.guess_type(path)
    if path.lower().endswith(".fit") or ctype is None:
        return "application", "octet-stream"
    maintype, subtype = ctype.split("/", 1)
    return maintype, subtype


def send_email(subject: str, html_body: str, attachments: Optional[List[str]] = None,
               to_addr: Optional[str] = None, text_body: Optional[str] = None) -> str:
    sender = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    to_addr = to_addr or os.environ.get("MAIL_TO") or sender
    if not (sender and password and to_addr):
        raise RuntimeError(
            "Env manquantes : définis GMAIL_ADDRESS, GMAIL_APP_PASSWORD "
            "(et MAIL_TO pour le destinataire)."
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_addr
    msg.set_content(text_body or "Ouvre cet email dans un client HTML pour le résumé. "
                                 "Séances .FIT et dashboard en pièces jointes.")
    msg.add_alternative(html_body, subtype="html")

    for path in attachments or []:
        with open(path, "rb") as f:
            data = f.read()
        maintype, subtype = _guess_mime(path)
        msg.add_attachment(data, maintype=maintype, subtype=subtype,
                           filename=os.path.basename(path))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.login(sender, password)
        s.send_message(msg)
    return to_addr


def email_body_html(dashboard_html: str) -> str:
    """Corps HTML de l'email = le dashboard (déjà auto-suffisant)."""
    return dashboard_html
