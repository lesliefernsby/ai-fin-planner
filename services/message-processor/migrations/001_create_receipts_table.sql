
CREATE TABLE IF NOT EXISTS receipts (
  id           SERIAL PRIMARY KEY,
  user_id      BIGINT NOT NULL,
  username     TEXT,
  total_amount TEXT,
  date         DATE,
  raw          JSONB NOT NULL,
  created_at   TIMESTAMPTZ DEFAULT now()
);