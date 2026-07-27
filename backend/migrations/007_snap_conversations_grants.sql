-- The app role could INSERT into snap_messages but lacked USAGE on the
-- auto-created BIGSERIAL sequence backing its id column, so every insert failed
-- with "permission denied for sequence snap_messages_id_seq".
GRANT USAGE, SELECT ON SEQUENCE snap_messages_id_seq TO peercopilot_app;
