from app.models import Contact
from app.tags import Tag, get_tag


def test_get_tag_mapeia_stage_new_para_novo_lead():
    contact = Contact(phone_hash="hash-new", stage="new")
    assert get_tag(contact) == Tag.NOVO_LEAD


def test_get_tag_mapeia_stage_cold_lead_para_novo_lead():
    contact = Contact(phone_hash="hash-cold", stage="cold_lead")
    assert get_tag(contact) == Tag.NOVO_LEAD


def test_get_tag_mapeia_remarketing_sequence_para_remarketing():
    contact = Contact(phone_hash="hash-rmkt", stage="remarketing_sequence")
    assert get_tag(contact) == Tag.REMARKETING
