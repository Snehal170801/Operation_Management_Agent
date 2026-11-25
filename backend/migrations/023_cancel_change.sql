-- Cancelling an order that was already emailed to the supplier: ask them, wait for their answer, chase if silent.

IF COL_LENGTH('dbo.PurchaseOrders', 'cancel_requested_at') IS NULL
    ALTER TABLE dbo.PurchaseOrders ADD cancel_requested_at DATETIME2 NULL;
GO
IF COL_LENGTH('dbo.PurchaseOrders', 'cancel_requested_by') IS NULL
    ALTER TABLE dbo.PurchaseOrders ADD cancel_requested_by NVARCHAR(255) NULL;
GO
IF COL_LENGTH('dbo.PurchaseOrders', 'cancel_reason') IS NULL
    ALTER TABLE dbo.PurchaseOrders ADD cancel_reason NVARCHAR(500) NULL;
GO
IF COL_LENGTH('dbo.PurchaseOrders', 'cancel_chase_count') IS NULL
    ALTER TABLE dbo.PurchaseOrders ADD cancel_chase_count INT NOT NULL CONSTRAINT DF_PurchaseOrders_cancel_chase_count DEFAULT 0;
GO
IF COL_LENGTH('dbo.PurchaseOrders', 'last_cancel_chase_at') IS NULL
    ALTER TABLE dbo.PurchaseOrders ADD last_cancel_chase_at DATETIME2 NULL;
GO
IF COL_LENGTH('dbo.PurchaseOrders', 'cancel_escalated_at') IS NULL
    ALTER TABLE dbo.PurchaseOrders ADD cancel_escalated_at DATETIME2 NULL;
GO
IF COL_LENGTH('dbo.PurchaseOrders', 'cancel_refused_at') IS NULL
    ALTER TABLE dbo.PurchaseOrders ADD cancel_refused_at DATETIME2 NULL;     -- the supplier said they will not cancel
GO
