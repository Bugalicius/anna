DELETE FROM pending_escalations WHERE phone_e164 LIKE '%3192059211%';
DELETE FROM remarketing_queue WHERE contact_id IN (SELECT id FROM contacts WHERE phone_e164='553192059211');
DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE contact_id IN (SELECT id FROM contacts WHERE phone_e164='553192059211'));
DELETE FROM conversations WHERE contact_id IN (SELECT id FROM contacts WHERE phone_e164='553192059211');
DELETE FROM contacts WHERE phone_e164='553192059211';
SELECT id, phone_e164, stage FROM contacts WHERE phone_e164='553192059211';
