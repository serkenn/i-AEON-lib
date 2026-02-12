"""食料在庫 SQLite データベース層"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .models import ParsedProduct, ProductInfo, ReceiptProducts

DB_PATH = Path.cwd() / "food_inventory.db"


class FoodInventoryDB:
    """食料在庫データベース"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    def _init_db(self):
        """テーブル作成"""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                category TEXT DEFAULT '',
                subcategory TEXT DEFAULT '',
                content_amount REAL,
                content_unit TEXT DEFAULT '',
                manufacturer TEXT DEFAULT '',
                is_food INTEGER DEFAULT 1,
                storage_type TEXT DEFAULT '常温',
                shelf_life_days INTEGER,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL REFERENCES products(id),
                receipt_id TEXT NOT NULL,
                store_name TEXT DEFAULT '',
                price INTEGER DEFAULT 0,
                quantity INTEGER DEFAULT 1,
                discount INTEGER DEFAULT 0,
                purchased_at TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_id INTEGER NOT NULL REFERENCES purchases(id),
                status TEXT DEFAULT 'in_stock' CHECK(status IN ('in_stock', 'consumed', 'expired')),
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS search_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT NOT NULL UNIQUE,
                search_result TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            );

            CREATE INDEX IF NOT EXISTS idx_purchases_receipt_id ON purchases(receipt_id);
            CREATE INDEX IF NOT EXISTS idx_inventory_status ON inventory(status);
            CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
        """)
        self.conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── 商品マスタ ──

    def upsert_product(self, name: str, info: Optional[ProductInfo] = None) -> int:
        """商品をマスタに登録（既存なら更新）。product_id を返す。"""
        row = self.conn.execute(
            "SELECT id FROM products WHERE name = ?", (name,)
        ).fetchone()

        if row:
            product_id = row["id"]
            if info:
                self.conn.execute("""
                    UPDATE products SET
                        category = ?, subcategory = ?, content_amount = ?,
                        content_unit = ?, manufacturer = ?, is_food = ?,
                        storage_type = ?, updated_at = datetime('now', 'localtime')
                    WHERE id = ?
                """, (
                    info.category, info.subcategory, info.content_amount,
                    info.content_unit, info.manufacturer, int(info.is_food),
                    info.storage_type, product_id,
                ))
                self.conn.commit()
            return product_id

        if info:
            cur = self.conn.execute("""
                INSERT INTO products (name, category, subcategory, content_amount,
                    content_unit, manufacturer, is_food, storage_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                name, info.category, info.subcategory, info.content_amount,
                info.content_unit, info.manufacturer, int(info.is_food),
                info.storage_type,
            ))
        else:
            cur = self.conn.execute(
                "INSERT INTO products (name) VALUES (?)", (name,)
            )
        self.conn.commit()
        return cur.lastrowid

    # ── レシートインポート ──

    def is_receipt_imported(self, receipt_id: str) -> bool:
        """このレシートが既にインポート済みか確認"""
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM purchases WHERE receipt_id = ?",
            (receipt_id,),
        ).fetchone()
        return row["cnt"] > 0

    def import_receipt(
        self,
        receipt: ReceiptProducts,
        product_infos: Optional[dict[str, ProductInfo]] = None,
    ) -> int:
        """レシート全体をDBにインポート。登録件数を返す。

        Args:
            receipt: パース済みレシート商品リスト
            product_infos: 商品名→ProductInfo のマッピング（検索結果）
        """
        if self.is_receipt_imported(receipt.receipt_id):
            return 0

        product_infos = product_infos or {}
        count = 0

        for product in receipt.products:
            info = product_infos.get(product.name)
            product_id = self.upsert_product(product.name, info)

            cur = self.conn.execute("""
                INSERT INTO purchases (product_id, receipt_id, store_name,
                    price, quantity, discount, purchased_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                product_id, receipt.receipt_id, receipt.store_name,
                product.price, product.quantity, product.discount,
                receipt.purchased_at,
            ))
            purchase_id = cur.lastrowid

            # 在庫レコードを作成（数量分）
            for _ in range(product.quantity):
                self.conn.execute(
                    "INSERT INTO inventory (purchase_id) VALUES (?)",
                    (purchase_id,),
                )
            count += 1

        self.conn.commit()
        return count

    # ── 在庫照会 ──

    def get_in_stock_items(self) -> list[dict]:
        """在庫一覧を取得（Cookpad/LLM用）"""
        rows = self.conn.execute("""
            SELECT
                p.name, p.category, p.subcategory, p.storage_type,
                p.content_amount, p.content_unit,
                SUM(pu.quantity) as total_quantity,
                MAX(pu.purchased_at) as last_purchased,
                pu.store_name,
                p.shelf_life_days
            FROM inventory i
            JOIN purchases pu ON pu.id = i.purchase_id
            JOIN products p ON p.id = pu.product_id
            WHERE i.status = 'in_stock'
            GROUP BY p.id
            ORDER BY pu.purchased_at DESC
        """).fetchall()
        return [dict(r) for r in rows]

    def get_expiring_soon(self, days: int = 3) -> list[dict]:
        """期限切れ間近の在庫を取得（LLM用）"""
        rows = self.conn.execute("""
            SELECT
                p.name, p.category, p.storage_type,
                p.shelf_life_days,
                pu.purchased_at,
                date(pu.purchased_at, '+' || p.shelf_life_days || ' days') as expires_at,
                julianday(date(pu.purchased_at, '+' || p.shelf_life_days || ' days'))
                    - julianday('now', 'localtime') as days_remaining
            FROM inventory i
            JOIN purchases pu ON pu.id = i.purchase_id
            JOIN products p ON p.id = pu.product_id
            WHERE i.status = 'in_stock'
              AND p.shelf_life_days IS NOT NULL
              AND julianday(date(pu.purchased_at, '+' || p.shelf_life_days || ' days'))
                  - julianday('now', 'localtime') <= ?
            ORDER BY days_remaining ASC
        """, (days,)).fetchall()
        return [dict(r) for r in rows]

    def mark_consumed(self, product_name: str, count: int = 1) -> int:
        """在庫を消費済みにマーク。更新件数を返す。"""
        rows = self.conn.execute("""
            SELECT i.id FROM inventory i
            JOIN purchases pu ON pu.id = i.purchase_id
            JOIN products p ON p.id = pu.product_id
            WHERE p.name = ? AND i.status = 'in_stock'
            ORDER BY pu.purchased_at ASC
            LIMIT ?
        """, (product_name, count)).fetchall()

        updated = 0
        for row in rows:
            self.conn.execute(
                "UPDATE inventory SET status = 'consumed', updated_at = datetime('now', 'localtime') WHERE id = ?",
                (row["id"],),
            )
            updated += 1
        self.conn.commit()
        return updated

    # ── 検索キャッシュ ──

    def get_search_cache(self, product_name: str) -> Optional[dict]:
        """検索キャッシュを取得"""
        row = self.conn.execute(
            "SELECT search_result FROM search_cache WHERE product_name = ?",
            (product_name,),
        ).fetchone()
        if row:
            return json.loads(row["search_result"])
        return None

    def set_search_cache(self, product_name: str, result: dict):
        """検索結果をキャッシュに保存"""
        self.conn.execute("""
            INSERT OR REPLACE INTO search_cache (product_name, search_result)
            VALUES (?, ?)
        """, (product_name, json.dumps(result, ensure_ascii=False)))
        self.conn.commit()
