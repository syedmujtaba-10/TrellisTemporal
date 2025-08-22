CREATE TABLE IF NOT EXISTS orders (
  id           VARCHAR(64) PRIMARY KEY,
  state        ENUM('received','validated','awaiting_approval','approved','payment_charged',
                    'shipping','shipped','canceled','failed') NOT NULL,
  address_json JSON NULL,
  created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS payments (
  payment_id   VARCHAR(64) PRIMARY KEY,
  order_id     VARCHAR(64) NOT NULL,
  status       ENUM('pending','charged','failed') NOT NULL,
  amount       DECIMAL(10,2) NOT NULL,
  created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_pay_order FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS shipments (
  id           BIGINT AUTO_INCREMENT PRIMARY KEY,
  order_id     VARCHAR(64) NOT NULL,
  status       ENUM('prepared','dispatched','failed') NOT NULL,
  payload_json JSON NULL,
  ts           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_ship_order (order_id)
);

CREATE TABLE IF NOT EXISTS events (
  id           BIGINT AUTO_INCREMENT PRIMARY KEY,
  order_id     VARCHAR(64) NOT NULL,
  type         VARCHAR(64) NOT NULL,
  payload_json JSON NULL,
  ts           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_evt_order_ts (order_id, ts)
);
