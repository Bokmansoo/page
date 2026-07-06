import datetime
import hashlib
import hmac
import secrets
from sqlalchemy.orm import Session
from src.config import settings
from src.db.models import FigmaPluginExportTicket, ProductProject


class TicketExpired(Exception):
    pass


class TicketAlreadyRedeemed(Exception):
    pass


class TicketNotFound(Exception):
    pass


class TicketConfigurationError(RuntimeError):
    pass


ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
MIN_SECRET_LENGTH = 32


def _new_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(8))
    return f"SF-{raw[:4]}-{raw[4:]}"


def _digest(value: str, secret: str) -> str:
    if len(secret.strip()) < MIN_SECRET_LENGTH:
        raise TicketConfigurationError(
            "SELLFORM_FIGMA_PLUGIN_TICKET_SECRET must contain at least 32 characters."
        )
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


class FigmaPluginTicketService:
    def __init__(self, db: Session):
        self.db = db
        self.secret = settings.SELLFORM_FIGMA_PLUGIN_TICKET_SECRET.strip()
        if len(self.secret) < MIN_SECRET_LENGTH:
            raise TicketConfigurationError(
                "SELLFORM_FIGMA_PLUGIN_TICKET_SECRET must contain at least 32 characters."
            )

    def issue(
        self,
        project: ProductProject,
        user_id: str,
        payload: dict,
        asset_map: dict
    ) -> FigmaPluginExportTicket:
        code = _new_code()
        code_hash = _digest(code, self.secret)

        ttl = settings.SELLFORM_FIGMA_PLUGIN_TICKET_TTL_SECONDS
        expires_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=ttl)

        ticket = FigmaPluginExportTicket(
            project_id=project.id,
            workspace_id=project.workspace_id,
            created_by=user_id,
            code_hash=code_hash,
            payload_json=payload,
            asset_map_json=asset_map,
            status="issued",
            expires_at=expires_at
        )
        self.db.add(ticket)
        self.db.commit()
        self.db.refresh(ticket)

        # Attach plaintext code to return (not saved in database)
        ticket.code = code
        return ticket

    def redeem(self, code: str):
        # Normalize code format
        normalized = code.strip().replace(" ", "").upper()
        # If user entered SFXXXXYYYY instead of SF-XXXX-YYYY
        if normalized.startswith("SF") and len(normalized) == 10 and "-" not in code:
            normalized = f"SF-{normalized[2:6]}-{normalized[6:]}"

        code_hash = _digest(normalized, self.secret)

        # Row locking to prevent concurrent double-redemption
        ticket = self.db.query(FigmaPluginExportTicket).filter(
            FigmaPluginExportTicket.code_hash == code_hash
        ).with_for_update().first()

        if not ticket:
            raise TicketNotFound("Ticket not found.")

        if ticket.status == "redeemed":
            raise TicketAlreadyRedeemed("Ticket has already been redeemed.")

        now = datetime.datetime.utcnow()
        if ticket.expires_at < now:
            # Mark failed/expired if we want, or just raise
            ticket.status = "expired"
            self.db.commit()
            raise TicketExpired("Ticket has expired.")

        # Generate temporary asset session
        asset_session_token = secrets.token_hex(32)
        session_token_hash = _digest(asset_session_token, self.secret)
        session_ttl = settings.SELLFORM_FIGMA_PLUGIN_SESSION_TTL_SECONDS
        session_expires_at = now + datetime.timedelta(seconds=session_ttl)

        ticket.status = "redeemed"
        ticket.redeemed_at = now
        ticket.session_token_hash = session_token_hash
        ticket.session_expires_at = session_expires_at

        self.db.commit()
        self.db.refresh(ticket)

        # Return result with raw token
        class RedeemResult:
            def __init__(self, ticket_row, token):
                self.ticket_id = ticket_row.id
                self.payload = ticket_row.payload_json
                self.asset_map = ticket_row.asset_map_json
                self.asset_session_token = token
                self.asset_session_expires_at = ticket_row.session_expires_at

        return RedeemResult(ticket, asset_session_token)
