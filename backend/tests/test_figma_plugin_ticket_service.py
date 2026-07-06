import datetime
import pytest
from sqlalchemy.orm import Session
from src.db.models import ProductProject, Brand, FigmaPluginExportTicket
from src.services.figma_plugin_ticket_service import (
    ALPHABET,
    FigmaPluginTicketService,
    TicketExpired,
    TicketAlreadyRedeemed,
    TicketNotFound,
)


def test_ticket_code_alphabet_provides_at_least_forty_bits_of_entropy():
    assert len(ALPHABET) ** 8 >= 2 ** 40


def test_ticket_stores_hash_not_plain_code(db_session: Session):
    brand = Brand(id="b-ticket-1", workspace_id="ws-ticket-1", name="Ticket Brand")
    db_session.add(brand)
    db_session.commit()
    project = ProductProject(
        id="p-ticket-1",
        workspace_id="ws-ticket-1",
        brand_id="b-ticket-1",
        name="Ticket Project"
    )
    db_session.add(project)
    db_session.commit()

    service = FigmaPluginTicketService(db_session)
    payload = {"schema_version": "1.0", "cuts": []}
    asset_map = {"asset_1": "some_id"}
    
    issued = service.issue(project, "user-1", payload, asset_map)
    
    assert issued.code.startswith("SF-")
    # Verify code is not saved in plain text
    row = db_session.get(FigmaPluginExportTicket, issued.id)
    assert issued.code not in row.code_hash
    assert row.status == "issued"


def test_ticket_expires_after_ten_minutes(db_session: Session):
    brand = Brand(id="b-ticket-2", workspace_id="ws-ticket-1", name="Ticket Brand")
    db_session.add(brand)
    db_session.commit()
    project = ProductProject(
        id="p-ticket-2",
        workspace_id="ws-ticket-1",
        brand_id="b-ticket-2",
        name="Ticket Project"
    )
    db_session.add(project)
    db_session.commit()

    service = FigmaPluginTicketService(db_session)
    payload = {"schema_version": "1.0"}
    
    issued = service.issue(project, "user-1", payload, {})
    
    # Manually expire ticket in database
    row = db_session.get(FigmaPluginExportTicket, issued.id)
    row.expires_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=1)
    db_session.commit()
    
    with pytest.raises(TicketExpired):
        service.redeem(issued.code)


def test_ticket_can_be_redeemed_only_once(db_session: Session):
    brand = Brand(id="b-ticket-3", workspace_id="ws-ticket-1", name="Ticket Brand")
    db_session.add(brand)
    db_session.commit()
    project = ProductProject(
        id="p-ticket-3",
        workspace_id="ws-ticket-1",
        brand_id="b-ticket-3",
        name="Ticket Project"
    )
    db_session.add(project)
    db_session.commit()

    service = FigmaPluginTicketService(db_session)
    payload = {"schema_version": "1.0"}
    
    issued = service.issue(project, "user-1", payload, {})
    
    result = service.redeem(issued.code)
    assert result.payload["schema_version"] == "1.0"
    
    with pytest.raises(TicketAlreadyRedeemed):
        service.redeem(issued.code)


def test_redeem_returns_asset_session_without_persisting_plain_token(db_session: Session):
    brand = Brand(id="b-ticket-4", workspace_id="ws-ticket-1", name="Ticket Brand")
    db_session.add(brand)
    db_session.commit()
    project = ProductProject(
        id="p-ticket-4",
        workspace_id="ws-ticket-1",
        brand_id="b-ticket-4",
        name="Ticket Project"
    )
    db_session.add(project)
    db_session.commit()

    service = FigmaPluginTicketService(db_session)
    payload = {"schema_version": "1.0"}
    
    issued = service.issue(project, "user-1", payload, {})
    result = service.redeem(issued.code)
    
    assert result.asset_session_token
    row = db_session.get(FigmaPluginExportTicket, issued.id)
    assert result.asset_session_token not in row.session_token_hash


def test_ticket_service_rejects_missing_or_short_secret(db_session: Session, monkeypatch):
    monkeypatch.setattr(
        "src.services.figma_plugin_ticket_service.settings.SELLFORM_FIGMA_PLUGIN_TICKET_SECRET",
        "",
    )

    with pytest.raises(RuntimeError, match="SELLFORM_FIGMA_PLUGIN_TICKET_SECRET"):
        FigmaPluginTicketService(db_session)

    monkeypatch.setattr(
        "src.services.figma_plugin_ticket_service.settings.SELLFORM_FIGMA_PLUGIN_TICKET_SECRET",
        "too-short",
    )

    with pytest.raises(RuntimeError, match="SELLFORM_FIGMA_PLUGIN_TICKET_SECRET"):
        FigmaPluginTicketService(db_session)
