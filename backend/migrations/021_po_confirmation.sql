-- Tracking whether the supplier has confirmed a purchase order we sent: when, how often we asked, and any problem they raised.

IF COL_LENGTH('dbo.PurchaseOrders', 'acknowledged_at') IS NULL
    ALTER TABLE dbo.PurchaseOrders ADD acknowledged_at DATETIME2 NULL;
GO

IF COL_LENGTH('dbo.PurchaseOrders', 'acknowledged_by') IS NULL
    ALTER TABLE dbo.PurchaseOrders ADD acknowledged_by NVARCHAR(255) NULL;   -- the supplier's address, or the person who confirmed it by phone
GO

IF COL_LENGTH('dbo.PurchaseOrders', 'confirm_chase_count') IS NULL
    ALTER TABLE dbo.PurchaseOrders
        ADD confirm_chase_count INT NOT NULL CONSTRAINT DF_PurchaseOrders_confirm_chase_count DEFAULT 0;
GO

IF COL_LENGTH('dbo.PurchaseOrders', 'last_confirm_chase_at') IS NULL
    ALTER TABLE dbo.PurchaseOrders ADD last_confirm_chase_at DATETIME2 NULL;
GO

IF COL_LENGTH('dbo.PurchaseOrders', 'confirm_escalated_at') IS NULL
    ALTER TABLE dbo.PurchaseOrders ADD confirm_escalated_at DATETIME2 NULL;
GO

IF COL_LENGTH('dbo.PurchaseOrders', 'vendor_issue') IS NULL
    ALTER TABLE dbo.PurchaseOrders ADD vendor_issue NVARCHAR(500) NULL;      -- what the supplier said was wrong, until someone deals with it
GO

-- Orders delivered before confirmations were tracked: the supplier plainly had them.
UPDATE dbo.PurchaseOrders
   SET acknowledged_at = COALESCE(delivered_at, sent_at, created_at), acknowledged_by = '(delivered before confirmations were tracked)'
 WHERE acknowledged_at IS NULL AND delivery_status = 'delivered';
GO
