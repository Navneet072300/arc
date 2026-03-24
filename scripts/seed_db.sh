#!/usr/bin/env bash
# Insert a test admin user (password: admin1234)
set -euo pipefail

PGPASSWORD=postgres psql -h localhost -U postgres -d serverless_pg <<'SQL'
INSERT INTO users (id, email, hashed_password, full_name, is_active, is_admin)
VALUES (
  gen_random_uuid(),
  'admin@example.com',
  '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj2p8k7B5z8e',  -- admin1234
  'Admin User',
  true,
  true
)
ON CONFLICT (email) DO NOTHING;
SQL

echo "Seeded admin@example.com / admin1234"
