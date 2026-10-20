"""One-click unsubscribe from alerts (roadmap P6 s80): no sign-in, no questions, no maze.

Every alert and renewal e-mail carries a signed link to this page and the RFC 8058 headers.
A mail client's one-click button POSTs here and the subscription is cancelled; a person who
opens the link sees one button that does the same. Opening the link alone changes nothing,
because mail scanners open links (the same rule as the sign-in link, `account`).

Not behind CSRF: the POST comes from a mail client, with no session, and the signed token is
what authorises it. Cancelling stops alerts at once and renews nothing; the period paid is not
refunded, and the page says so. It can be undone from the account until the period ends.
"""

import uuid

from flask import Blueprint, abort, current_app, render_template, request

from app.config import load_settings
from app.db import session_factory
from app.models import Subscription
from app.orders import numbering, subscriptions

bp = Blueprint("unsubscribe", __name__)


def _sessions():
    return session_factory(load_settings())


@bp.route("/otkazi-sledenje/<token>", methods=["GET", "POST"])
def page(token: str):
    subscription_id = subscriptions.from_token(current_app.config["SECRET_KEY"], token)
    if subscription_id is None:
        abort(404)
    with _sessions()() as db:
        subscription = db.get(Subscription, uuid.UUID(subscription_id))
        if subscription is None:
            abort(404)
        if request.method == "POST":
            subscriptions.cancel(db, subscription, ip=request.remote_addr)
            db.commit()
        done = subscription.cancelled_at is not None
        return render_template(
            "unsubscribe/page.html",
            done=done,
            until=subscription.renews_on,
            running=subscription.renews_on > numbering.today(),
        )
