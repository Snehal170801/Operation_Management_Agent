-- Wrong or damaged goods: a recorded problem with a delivery, what was agreed with the supplier, and any credit.

IF OBJECT_ID('dbo.GoodsIssues', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.GoodsIssues (
        issue_id            UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
        case_id             UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES dbo.Cases(case_id),
        purchase_order_id   UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES dbo.PurchaseOrders(purchase_order_id),
        kind                NVARCHAR(20)     NOT NULL,                 -- damaged | wrong_item | not_as_described | other
        items_json          NVARCHAR(MAX)    NOT NULL,                 -- [{"description", "quantity"}] affected
        description         NVARCHAR(500)    NULL,
        reported_by         NVARCHAR(255)    NOT NULL,
        reported_at         DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
        status              NVARCHAR(20)     NOT NULL DEFAULT 'open',  -- open | resolved
        supplier_told_at    DATETIME2        NULL,
        supplier_replied_at DATETIME2        NULL,
        chase_count         INT              NOT NULL DEFAULT 0,
        last_chased_at      DATETIME2        NULL,
        escalated_at        DATETIME2        NULL,
        resolution          NVARCHAR(20)     NULL,                     -- replaced | credit | accepted
        credit_amount       DECIMAL(12,2)    NULL,
        resolution_note     NVARCHAR(500)    NULL,
        resolved_by         NVARCHAR(255)    NULL,
        resolved_at         DATETIME2        NULL
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_GoodsIssues_case_id')
    CREATE INDEX IX_GoodsIssues_case_id ON dbo.GoodsIssues(case_id);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_GoodsIssues_status')
    CREATE INDEX IX_GoodsIssues_status ON dbo.GoodsIssues(status);
GO
