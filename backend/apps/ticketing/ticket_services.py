from io import BytesIO

import qrcode
from qrcode.image.svg import SvgPathImage

from django.core import signing

from apps.ticketing.models import IssuedTicket


TICKET_TOKEN_SALT = "event-registration.ticket.v1"


def issue_ticket(*, registration):
    quantity = registration.ticket_hold.quantity if registration.ticket_hold_id else 1
    existing = IssuedTicket.objects.filter(registration=registration).count()
    tickets = [
        IssuedTicket(registration=registration)
        for _ in range(max(0, quantity - existing))
    ]
    if tickets:
        IssuedTicket.objects.bulk_create(tickets)
    return IssuedTicket.objects.filter(registration=registration).order_by("issued_at")


def build_ticket_token(ticket):
    return signing.dumps(
        {"ticket_reference": str(ticket.reference)},
        salt=TICKET_TOKEN_SALT,
    )


def build_ticket_qr_svg(ticket):
    token = build_ticket_token(ticket)
    qr = qrcode.QRCode(box_size=8, border=4)
    qr.add_data(token)
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    output = BytesIO()
    image.save(output)
    return output.getvalue().decode("utf-8")


def resolve_ticket_token(token):
    payload = signing.loads(token, salt=TICKET_TOKEN_SALT)
    reference = payload.get("ticket_reference")
    if not reference:
        raise signing.BadSignature("Ticket reference is missing.")
    return IssuedTicket.objects.select_related(
        "registration__event",
        "registration__attendee",
        "registration__ticket_tier",
    ).get(reference=reference)
