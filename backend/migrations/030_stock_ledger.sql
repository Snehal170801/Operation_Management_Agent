-- Stock history: one row for every change to a stock count (who, when, old value, new value, why, and the case if there is one).
-- Rows are never edited or deleted, and carry the item's name as it was, so the history survives if the item is removed later.

IF OBJECT_ID('dbo.StockLedger', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.StockLedger (
        entry_id          UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
        stock_id          UNIQUEIDENTIFIER NULL,                 -- the stock row at the time (no foreign key: the history outlives the row)
        item_description  NVARCHAR(255)    NOT NULL,
        old_quantity      INT              NOT NULL,             -- 0 when the item was just created
        new_quantity      INT              NOT NULL,
        reason            NVARCHAR(40)     NOT NULL,             -- created | manual | fulfilled_from_stock | restock_received | goods_issue | ...
        actor             NVARCHAR(150)    NOT NULL,             -- the signed-in person's username, or the agent that acted
        case_id           UNIQUEIDENTIFIER NULL,                 -- the case that caused it, if any
        note              NVARCHAR(300)    NULL,
        created_at        DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_StockLedger_item')
    CREATE INDEX IX_StockLedger_item ON dbo.StockLedger (item_description, created_at DESC);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_StockLedger_case')
    CREATE INDEX IX_StockLedger_case ON dbo.StockLedger (case_id) WHERE case_id IS NOT NULL;
GO
