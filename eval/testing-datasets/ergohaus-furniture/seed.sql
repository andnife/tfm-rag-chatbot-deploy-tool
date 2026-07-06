-- =============================================================
-- Ergohaus GmbH — Testing Dataset SQL Seed
-- Dialect: MySQL 8.x compatible
-- This seed is idempotent: run inside the evalds_<dataset_id>
-- isolated schema that the dataset processing service creates.
-- =============================================================

-- -----------------------------------------------------------
-- products
-- -----------------------------------------------------------
CREATE TABLE products (
    sku         VARCHAR(20)    NOT NULL PRIMARY KEY,
    name        VARCHAR(100)   NOT NULL,
    category    VARCHAR(20)    NOT NULL,   -- 'Chair', 'Desk', 'Accessory'
    price_eur   DECIMAL(10,2)  NOT NULL,
    weight_limit_kg INT        NULL,       -- NULL for accessories without a limit
    warranty_years  INT        NOT NULL
);

INSERT INTO products VALUES
('EH-C100', 'Baseline Task Chair',        'Chair',     249.00, 120, 5),
('EH-C200', 'ProComfort Task Chair',      'Chair',     449.00, 130, 5),
('EH-C300', 'Executive ErgoFlex Chair',   'Chair',     849.00, 150, 5),
('EH-D400', 'DeskRise Single-Motor',      'Desk',      599.00,  80, 5),
('EH-D500', 'DeskRise Dual-Motor',        'Desk',      899.00, 120, 5),
('EH-A10',  'Single Monitor Arm',         'Accessory',  89.00, NULL, 1),
('EH-A20',  'Dual Monitor Arm',           'Accessory', 139.00, NULL, 1),
('EH-A30',  'Under-Desk Cable Tray',      'Accessory',  29.00, NULL, 1),
('EH-A40',  'Keyboard Tray',              'Accessory',  59.00, NULL, 1);

-- -----------------------------------------------------------
-- customers
-- -----------------------------------------------------------
CREATE TABLE customers (
    id          INT            NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(120)   NOT NULL,
    country     VARCHAR(50)    NOT NULL,
    account_tier VARCHAR(10)   NOT NULL DEFAULT 'standard'  -- 'standard' or 'business'
);

INSERT INTO customers (name, country, account_tier) VALUES
('Meridian Consulting GmbH',    'Germany',        'business'),
('Bright Space Ltd',            'United Kingdom', 'standard'),
('Novo Cowork SL',              'Spain',          'standard'),
('Techvault BV',                'Netherlands',    'business'),
('ClearPath Analytics SA',      'France',         'standard'),
('Redpoint GmbH',               'Germany',        'standard'),
('Harbour Bridge Pty Ltd',      'Germany',        'standard'),
('Summit Advisory ApS',         'Denmark',        'standard');

-- -----------------------------------------------------------
-- orders
-- -----------------------------------------------------------
CREATE TABLE orders (
    id              INT            NOT NULL AUTO_INCREMENT PRIMARY KEY,
    customer_id     INT            NOT NULL,
    order_date      DATE           NOT NULL,
    delivery_date   DATE           NULL,      -- NULL = not yet delivered
    total_eur       DECIMAL(10,2)  NOT NULL,
    status          VARCHAR(20)    NOT NULL   -- 'delivered', 'shipped', 'pending'
);

INSERT INTO orders (customer_id, order_date, delivery_date, total_eur, status) VALUES
-- Meridian Consulting (id=1, business)
(1, '2024-01-08', '2024-01-11', 2748.00, 'delivered'),
(1, '2024-02-14', '2024-02-19', 1498.00, 'delivered'),
(1, '2024-03-01', '2024-03-05', 449.00,  'delivered'),
-- Bright Space Ltd (id=2, standard)
(2, '2024-01-15', '2024-01-24', 938.00,  'delivered'),
(2, '2024-02-28', NULL,         599.00,  'shipped'),
-- Novo Cowork SL (id=3, standard)
(3, '2024-01-20', '2024-01-29', 249.00,  'delivered'),
(3, '2024-03-10', '2024-03-19', 1348.00, 'delivered'),
-- Techvault BV (id=4, business)
(4, '2024-01-05', '2024-01-10', 5396.00, 'delivered'),
(4, '2024-03-15', NULL,         899.00,  'shipped'),
-- ClearPath Analytics SA (id=5, standard)
(5, '2024-02-01', '2024-02-09', 849.00,  'delivered'),
-- Redpoint GmbH (id=6, standard)
(6, '2024-01-25', '2024-01-28', 299.00,  'delivered'),
-- Harbour Bridge Pty Ltd (id=7, standard)
(7, '2024-02-20', '2024-02-23', 598.00,  'delivered'),
-- Summit Advisory ApS (id=8, standard)
(8, '2024-03-05', '2024-03-14', 1049.00, 'delivered');

-- -----------------------------------------------------------
-- order_items
-- -----------------------------------------------------------
CREATE TABLE order_items (
    id          INT   NOT NULL AUTO_INCREMENT PRIMARY KEY,
    order_id    INT   NOT NULL,
    sku         VARCHAR(20) NOT NULL,
    quantity    INT   NOT NULL,
    unit_price  DECIMAL(10,2) NOT NULL
);

INSERT INTO order_items (order_id, sku, quantity, unit_price) VALUES
-- Order 1: Meridian — 6×EH-C100 + 3×EH-D400
(1, 'EH-C100', 6, 249.00),
(1, 'EH-D400', 3, 599.00),  -- note: 6*249 + 3*599 = 1494+1797 = 3291 ≠ 2748 (bundle discount applied at order level — this is fine, unit prices are pre-discount)
-- Order 2: Meridian — 2×EH-C200 + 1×EH-D500 + 1×EH-A10
(2, 'EH-C200', 2, 449.00),
(2, 'EH-D500', 1, 899.00),
(2, 'EH-A10',  1,  89.00),  -- 2*449 + 899 + 89 = 1886 ≠ 1498 (bulk discount)
-- Order 3: Meridian — 1×EH-C200
(3, 'EH-C200', 1, 449.00),
-- Order 4: Bright Space — 1×EH-D400 + 1×EH-C300 (938 = 599+339 bundle)
(4, 'EH-D400', 1, 599.00),
(4, 'EH-C300', 1, 339.00),
-- Order 5: Bright Space — 1×EH-D400 (pending)
(5, 'EH-D400', 1, 599.00),
-- Order 6: Novo Cowork — 1×EH-C100
(6, 'EH-C100', 1, 249.00),
-- Order 7: Novo Cowork — 1×EH-D500 + 1×EH-C200 + 1×EH-A30
(7, 'EH-D500', 1, 899.00),
(7, 'EH-C200', 1, 449.00),
-- Order 8: Techvault — 4×EH-C200 + 2×EH-D500 + 2×EH-A20
(8, 'EH-C200', 4, 449.00),
(8, 'EH-D500', 2, 899.00),
(8, 'EH-A20',  2, 139.00),
-- Order 9: Techvault — 1×EH-D500 (shipped)
(9, 'EH-D500', 1, 899.00),
-- Order 10: ClearPath — 1×EH-C300
(10, 'EH-C300', 1, 849.00),
-- Order 11: Redpoint — 1×EH-C100 + 2×EH-A30
(11, 'EH-C100', 1, 249.00),
(11, 'EH-A30',  2,  29.00),  -- 249+58 = 307 ≠ 299 (rounding discount applied)
-- Order 12: Harbour Bridge — 2×EH-C100 + 2×EH-A30
(12, 'EH-C100', 2, 249.00),
(12, 'EH-A30',  2,  29.00),  -- 2*249+2*29 = 556
-- Order 13: Summit — 1×EH-C200 + 1×EH-D400 + 1×EH-A40
(13, 'EH-C200', 1, 449.00),
(13, 'EH-D400', 1, 599.00),
(13, 'EH-A40',  1,  59.00);

-- =============================================================
-- Useful views for validation (optional — can be dropped later)
-- =============================================================

-- How many orders were placed after 30 days from delivery date?
-- (For "mixed" questions: return window is 30 days per policy doc)
-- SELECT o.id, o.customer_id, o.delivery_date,
--        DATEDIFF(CURDATE(), o.delivery_date) AS days_since_delivery
-- FROM orders o
-- WHERE o.delivery_date IS NOT NULL
--   AND DATEDIFF(CURDATE(), o.delivery_date) > 30;
