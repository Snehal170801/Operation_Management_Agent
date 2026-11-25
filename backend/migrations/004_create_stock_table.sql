
IF OBJECT_ID('dbo.Stock', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.Stock (
        stock_id            UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
        item_description    NVARCHAR(255)    NOT NULL,
        quantity_available  INT              NOT NULL DEFAULT 0,
        updated_at          DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_Stock_item_description')
BEGIN
    CREATE UNIQUE INDEX UX_Stock_item_description ON dbo.Stock(item_description);
END
GO
