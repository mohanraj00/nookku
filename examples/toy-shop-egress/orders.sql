CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, status TEXT NOT NULL, items TEXT NOT NULL);
DELETE FROM orders;
INSERT INTO orders VALUES
  ('7310', 'delivered', '1 wooden train set'),
  ('7311', 'shipped', '2 mugs'),
  ('7312', 'packed', '1 teapot set');
