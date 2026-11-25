
IF OBJECT_ID('dbo.PurchaseRequestItems', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.PurchaseRequestItems (
        item_id              UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
        purchase_request_id  UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES dbo.PurchaseRequests(purchase_request_id),
        description          NVARCHAR(255)    NOT NULL,
        quantity             INT              NOT NULL,
        created_at           DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_PurchaseRequestItems_purchase_request_id')
BEGIN
    CREATE INDEX IX_PurchaseRequestItems_purchase_request_id ON dbo.PurchaseRequestItems(purchase_request_id);
END
GO

-- Old single item/quantity columns are superseded by PurchaseRequestItems.
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.PurchaseRequests') AND name = 'item')
BEGIN
    ALTER TABLE dbo.PurchaseRequests DROP COLUMN item;
END
GO

IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.PurchaseRequests') AND name = 'quantity')
BEGIN
    ALTER TABLE dbo.PurchaseRequests DROP COLUMN quantity;
END
GO
