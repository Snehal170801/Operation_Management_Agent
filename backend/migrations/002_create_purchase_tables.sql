
IF OBJECT_ID('dbo.PurchaseRequests', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.PurchaseRequests (
        purchase_request_id UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
        case_id              UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES dbo.Cases(case_id),
        item                 NVARCHAR(255)    NOT NULL,
        quantity             INT              NOT NULL,
        cost_center          NVARCHAR(100)    NULL,
        raw_request          NVARCHAR(MAX)    NOT NULL,
        created_at           DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_PurchaseRequests_case_id')
BEGIN
    CREATE INDEX IX_PurchaseRequests_case_id ON dbo.PurchaseRequests(case_id);
END
GO
