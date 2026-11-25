-- Delivery tracking on purchase orders: chase late vendors, escalate, record receipt.

IF COL_LENGTH('dbo.PurchaseOrders', 'delivery_status') IS NULL
    ALTER TABLE dbo.PurchaseOrders
        ADD delivery_status NVARCHAR(20) NOT NULL
            CONSTRAINT DF_PurchaseOrders_delivery_status DEFAULT 'pending';   -- pending | delivered
GO

IF COL_LENGTH('dbo.PurchaseOrders', 'chase_count') IS NULL
    ALTER TABLE dbo.PurchaseOrders
        ADD chase_count INT NOT NULL CONSTRAINT DF_PurchaseOrders_chase_count DEFAULT 0;
GO

IF COL_LENGTH('dbo.PurchaseOrders', 'last_chased_at') IS NULL
    ALTER TABLE dbo.PurchaseOrders ADD last_chased_at DATETIME2 NULL;
GO

IF COL_LENGTH('dbo.PurchaseOrders', 'escalated_at') IS NULL
    ALTER TABLE dbo.PurchaseOrders ADD escalated_at DATETIME2 NULL;
GO

IF COL_LENGTH('dbo.PurchaseOrders', 'delivered_at') IS NULL
    ALTER TABLE dbo.PurchaseOrders ADD delivered_at DATETIME2 NULL;
GO

IF COL_LENGTH('dbo.PurchaseOrders', 'received_by') IS NULL
    ALTER TABLE dbo.PurchaseOrders ADD received_by NVARCHAR(255) NULL;
GO

IF COL_LENGTH('dbo.PurchaseOrders', 'delivery_note') IS NULL
    ALTER TABLE dbo.PurchaseOrders ADD delivery_note NVARCHAR(MAX) NULL;
GO
