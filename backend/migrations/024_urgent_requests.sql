-- Urgent requests: the date the goods are needed by, and whether to treat the request as urgent.

IF COL_LENGTH('dbo.PurchaseRequests', 'needed_by') IS NULL
    ALTER TABLE dbo.PurchaseRequests ADD needed_by DATE NULL;
GO

IF COL_LENGTH('dbo.PurchaseRequests', 'urgent') IS NULL
    ALTER TABLE dbo.PurchaseRequests ADD urgent BIT NOT NULL CONSTRAINT DF_PurchaseRequests_urgent DEFAULT 0;
GO
