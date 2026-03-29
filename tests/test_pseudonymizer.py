from scripts.pseudonymizer import Pseudonymizer

def test_same_phone_gets_same_id():
    p = Pseudonymizer()
    id1 = p.get_id("5531999999999@s.whatsapp.net")
    id2 = p.get_id("5531999999999@s.whatsapp.net")
    assert id1 == id2

def test_different_phones_get_different_ids():
    p = Pseudonymizer()
    id1 = p.get_id("5531999999999@s.whatsapp.net")
    id2 = p.get_id("5532888888888@s.whatsapp.net")
    assert id1 != id2

def test_id_does_not_contain_phone():
    p = Pseudonymizer()
    phone = "5531999999999"
    pid = p.get_id(f"{phone}@s.whatsapp.net")
    assert phone not in pid

def test_pseudonymize_conversation_replaces_jid():
    p = Pseudonymizer()
    messages = [
        {"from_me": False, "text": "Oi, sou Maria"},
        {"from_me": True, "text": "Olá Maria!"},
    ]
    result = p.pseudonymize("5531999999999@s.whatsapp.net", messages)
    assert result["contact_id"].startswith("contact_")
    assert "5531999999999" not in result["contact_id"]
    assert len(result["messages"]) == 2
