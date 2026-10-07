-- Yuqta POC demo business data.
--
-- Loaded automatically on backend startup when the customers table is empty
-- (python -m app.db.seed --if-empty), or on demand with python -m app.db.seed.
-- The loader runs this file in one transaction. With psql use:  psql -1 -f seed.sql
--
-- Reloading resets business reference data only; meeting data is untouched.
--
-- Periods: previous month = 2026-08, current month = 2026-09.
--   Revenue  previous 2,390,000  current 1,950,000  change -440,000 (-18.4%)
--   Decline  Acme -190,000 | Beta -120,000 | Gamma -80,000 | Other -50,000
--   Acme order units 1,000 -> 690 (-31%)
--   Beta renewal overdue

TRUNCATE TABLE renewals, revenue, orders, customers RESTART IDENTITY CASCADE;

INSERT INTO customers (id, name, industry, account_owner, status) VALUES
  ('C001', 'Acme',  'Retail',        'Rahul', 'At Risk'),
  ('C002', 'Beta',  'Technology',    'Priya', 'At Risk'),
  ('C003', 'Gamma', 'Manufacturing', 'Amit',  'Healthy');

-- customer_id NULL = long-tail "Other" accounts.
INSERT INTO revenue (period_start, customer_id, amount) VALUES
  ('2026-08-01', 'C001', 820000.00),
  ('2026-08-01', 'C002', 540000.00),
  ('2026-08-01', 'C003', 610000.00),
  ('2026-08-01', NULL,   420000.00),
  ('2026-09-01', 'C001', 630000.00),
  ('2026-09-01', 'C002', 420000.00),
  ('2026-09-01', 'C003', 530000.00),
  ('2026-09-01', NULL,   370000.00);

-- Order amounts per customer and month match recognised revenue above.
INSERT INTO orders (customer_id, order_date, units, amount) VALUES
  -- Acme: 1,000 units -> 690 units (-31%)
  ('C001', '2026-08-04', 250, 205000.00),
  ('C001', '2026-08-11', 250, 205000.00),
  ('C001', '2026-08-18', 250, 205000.00),
  ('C001', '2026-08-25', 250, 205000.00),
  ('C001', '2026-09-08', 230, 210000.00),
  ('C001', '2026-09-15', 230, 210000.00),
  ('C001', '2026-09-22', 230, 210000.00),
  -- Beta: 600 units -> 470 units
  ('C002', '2026-08-06', 300, 270000.00),
  ('C002', '2026-08-20', 300, 270000.00),
  ('C002', '2026-09-09', 235, 210000.00),
  ('C002', '2026-09-23', 235, 210000.00),
  -- Gamma: 800 units -> 700 units
  ('C003', '2026-08-07', 400, 305000.00),
  ('C003', '2026-08-21', 400, 305000.00),
  ('C003', '2026-09-10', 350, 265000.00),
  ('C003', '2026-09-24', 350, 265000.00);

INSERT INTO renewals (customer_id, contract_value, due_date, status, renewed_on) VALUES
  ('C001', 2400000.00, '2027-01-31', 'upcoming', NULL),
  ('C002', 1500000.00, '2026-09-15', 'overdue',  NULL),
  ('C003', 1800000.00, '2026-06-30', 'renewed',  '2026-06-24');
