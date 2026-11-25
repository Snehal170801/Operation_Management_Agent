-- Partial deliveries: what has arrived so far (batches, newest last) and whether the rest was written off.

IF COL_LENGTH('dbo.PurchaseOrders', 'received_json') IS NULL
    ALTER TABLE dbo.PurchaseOrders ADD received_json NVARCHAR(MAX) NULL;    -- [{"at", "by", "note", "items": {"<item>": quantity}}]
GO

IF COL_LENGTH('dbo.PurchaseOrders', 'short_closed_at') IS NULL
    ALTER TABLE dbo.PurchaseOrders ADD short_closed_at DATETIME2 NULL;      -- the supplier will not send the rest and a person accepted that
GO
